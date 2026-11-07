from __future__ import annotations

import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from .models import Node


def _parse_geo_payload(text: str) -> tuple[str | None, str | None]:
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        payload = {}
        for line in text.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                payload[key.strip()] = value.strip()
    country_code = str(payload.get("country") or payload.get("loc") or "").upper()
    if len(country_code) != 2 or not country_code.isalpha():
        country_code = ""
    exit_ip = str(payload.get("ip") or payload.get("clientIp") or "").strip()
    return country_code or None, exit_ip or None


class MihomoBenchmark:
    def __init__(
        self,
        binary: Path,
        workdir: Path,
        nodes: list[Node],
        latency_url: str,
        speed_url: str,
        geo_url: str,
        timeout_ms: int,
        speed_bytes: int,
        speed_limit: int,
        speed_timeout_seconds: int,
        workers: int,
        geo_limit: int = 300,
        speed_workers: int = 8,
        speed_enabled: bool = True,
        latency_attempts: int = 2,
    ) -> None:
        self.binary = binary
        self.workdir = workdir
        self.nodes = nodes
        self.latency_url = latency_url
        self.speed_url = speed_url
        self.geo_urls = [item.strip() for item in geo_url.split(",") if item.strip()]
        self.timeout_ms = timeout_ms
        self.speed_bytes = speed_bytes
        self.speed_limit = max(0, speed_limit)
        self.speed_timeout_seconds = max(1, speed_timeout_seconds)
        self.workers = max(1, workers)
        self.geo_limit = max(0, geo_limit)
        self.speed_workers = max(1, min(speed_workers, self.workers))
        self.latency_attempts = max(1, latency_attempts)
        self.speed_enabled = speed_enabled
        self.controller = "http://127.0.0.1:9090"
        self.proxy_port = 7890
        self.listener_port_base = 20000
        testable_nodes = [node for node in nodes if node.clash]
        if testable_nodes and self.listener_port_base + len(testable_nodes) - 1 > 65535:
            raise ValueError("Too many nodes for dedicated Mihomo benchmark listeners.")
        self.node_proxy_ports = {
            node.name: self.listener_port_base + index
            for index, node in enumerate(testable_nodes)
        }
        self.process: subprocess.Popen[str] | None = None
        self.log_handle = None

    def __enter__(self) -> "MihomoBenchmark":
        self.workdir.mkdir(parents=True, exist_ok=True)
        config_path = self.workdir / "mihomo-benchmark.yaml"
        write_mihomo_config(config_path, self.nodes, self.node_proxy_ports)
        config_path.write_text(
            "external-controller: 127.0.0.1:9090\n"
            + config_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        self.process = subprocess.Popen(
            [str(self.binary), "-d", str(self.workdir), "-f", str(config_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                response = requests.get(f"{self.controller}/version", timeout=1)
                if response.ok:
                    return self
            except requests.RequestException:
                time.sleep(0.25)

        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.log_handle:
            self.log_handle.close()
        raise RuntimeError("Mihomo did not start within 60 seconds.")

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.log_handle:
            self.log_handle.close()

    def _proxy_path(self, name: str) -> str:
        return f"{self.controller}/proxies/{quote(name, safe='')}"

    def latency(self, node: Node) -> Node:
        last_error: Exception | None = None
        for _ in range(self.latency_attempts):
            try:
                response = requests.get(
                    f"{self._proxy_path(node.name)}/delay",
                    params={
                        "url": self.latency_url,
                        "timeout": str(self.timeout_ms),
                        "expected": "204",
                    },
                    timeout=max(2, self.timeout_ms / 1000 + 2),
                )
                response.raise_for_status()
                node.latency_ms = int(response.json()["delay"])
                return node
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                last_error = exc
        if last_error:
            status_code = getattr(getattr(last_error, "response", None), "status_code", None)
            detail = f"HTTP {status_code}" if status_code else type(last_error).__name__
            node.error = f"latency: {detail}"
        return node

    def benchmark_latency(self, nodes: list[Node]) -> list[Node]:
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = [executor.submit(self.latency, node) for node in nodes]
            measured: list[Node] = []
            for future in as_completed(futures):
                measured.append(future.result())
            return measured

    def _proxies_for_port(self, port: int) -> dict[str, str]:
        proxy = f"http://127.0.0.1:{port}"
        return {"http": proxy, "https": proxy}

    def geolocate(self, node: Node, proxy_port: int | None = None) -> None:
        port = proxy_port or self.proxy_port
        for geo_url in self.geo_urls:
            try:
                location = requests.get(
                    geo_url,
                    proxies=self._proxies_for_port(port),
                    timeout=(3, 5),
                )
                location.raise_for_status()
                country_code, exit_ip = _parse_geo_payload(location.text)
                if country_code:
                    node.metadata["country_code"] = country_code
                if exit_ip:
                    node.metadata["exit_ip"] = exit_ip
                if country_code:
                    break
            except requests.RequestException:
                continue

    def select(self, node: Node) -> None:
        selected = requests.put(
            f"{self.controller}/proxies/BENCHMARK",
            json={"name": node.name},
            timeout=10,
        )
        selected.raise_for_status()

    def speed(self, node: Node) -> Node:
        proxy_port = self.node_proxy_ports.get(node.name, self.proxy_port)
        try:
            started = time.monotonic()
            received = 0
            with requests.get(
                self.speed_url,
                proxies=self._proxies_for_port(proxy_port),
                stream=True,
                timeout=(min(10, self.speed_timeout_seconds), self.speed_timeout_seconds),
            ) as response:
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    received += len(chunk)
                    if received >= self.speed_bytes:
                        break
            elapsed = max(time.monotonic() - started, 0.001)
            node.speed_mbps = round(received * 8 / elapsed / 1_000_000, 2)
        except (requests.RequestException, ValueError):
            node.metadata["speed_test_failed"] = True
        return node

    def _geolocate_node(self, node: Node) -> Node:
        self.geolocate(node, self.node_proxy_ports.get(node.name, self.proxy_port))
        return node

    def benchmark(self, nodes: list[Node]) -> list[Node]:
        measured = self.benchmark_latency(nodes)
        valid = [node for node in measured if node.latency_ms is not None and node.error is None]
        valid.sort(key=lambda node: (node.latency_ms or 10**9, node.name))
        if self.speed_enabled:
            speed_candidates = valid if self.speed_limit <= 0 else valid[: self.speed_limit]
            with ThreadPoolExecutor(max_workers=self.speed_workers) as executor:
                list(executor.map(self.speed, speed_candidates))
        valid.sort(
            key=lambda node: (
                node.speed_mbps is None,
                -(node.speed_mbps or 0),
                node.latency_ms or 10**9,
                node.name,
            )
        )
        geo_candidates = valid if self.geo_limit <= 0 else valid[: self.geo_limit]
        with ThreadPoolExecutor(max_workers=min(16, self.workers)) as executor:
            list(executor.map(self._geolocate_node, geo_candidates))
        return valid


def write_mihomo_config(
    path: Path,
    nodes: list[Node],
    listener_ports: dict[str, int] | None = None,
) -> None:
    import yaml

    class QuotedYamlString(str):
        pass

    class MihomoSafeDumper(yaml.SafeDumper):
        pass

    MihomoSafeDumper.add_representer(
        QuotedYamlString,
        lambda dumper, value: dumper.represent_scalar(
            "tag:yaml.org,2002:str",
            value,
            style='"',
        ),
    )

    proxies: list[dict[str, Any]] = []
    for node in nodes:
        if not node.clash:
            continue
        proxy = dict(node.clash)
        reality = proxy.get("reality-opts")
        if isinstance(reality, dict) and "short-id" in reality:
            reality = dict(reality)
            # Go's YAML parser treats an unquoted value such as 09 as a number,
            # drops the leading zero, and Mihomo then rejects the odd-length ID.
            reality["short-id"] = QuotedYamlString(str(reality["short-id"]))
            proxy["reality-opts"] = reality
        proxies.append(proxy)

    names = [node.name for node in nodes if node.clash]
    document = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
        "proxies": proxies,
        "proxy-groups": [
            {"name": "BENCHMARK", "type": "select", "proxies": names},
        ],
        "rules": ["MATCH,BENCHMARK"],
    }
    if listener_ports:
        document["listeners"] = [
            {
                "name": f"benchmark-{index:04d}",
                "type": "mixed",
                "listen": "127.0.0.1",
                "port": listener_ports[node.name],
                "proxy": node.name,
            }
            for index, node in enumerate(nodes, start=1)
            if node.clash and node.name in listener_ports
        ]
    path.write_text(
        yaml.dump(document, Dumper=MihomoSafeDumper, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def validate_clash_config(binary: Path, config_path: Path, workdir: Path) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [str(binary), "-t", "-d", str(workdir), "-f", str(config_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("Mihomo final configuration validation failed.") from None
    if result.returncode != 0:
        raise RuntimeError("Mihomo rejected the final Clash configuration.")
