import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import requests
import yaml

from subbench.benchmark import MihomoBenchmark, _parse_geo_payload, write_mihomo_config
from subbench.cli import _fair_candidate_selection, _filter_benchmarked_nodes
from subbench.models import Node


def make_node(name: str, latency: int = 100, speed: float | None = None, error: str | None = None) -> Node:
    return Node(
        uri=f"vless://id@example.com:443#{name}",
        scheme="vless",
        name=name,
        clash={"name": name, "type": "vless", "server": "example.com", "port": 443, "uuid": "id"},
        source="test",
        latency_ms=latency,
        speed_mbps=speed,
        error=error,
    )


class BenchmarkTests(unittest.TestCase):
    def test_fair_candidate_selection_does_not_use_global_prefix(self):
        nodes = [
            make_node(f"source-a-{index}") for index in range(8)
        ] + [
            Node(
                uri=f"vless://id-{index}@other.example.com:443#b-{index}",
                scheme="vless",
                name=f"source-b-{index}",
                clash={"name": f"source-b-{index}", "type": "vless", "server": "other.example.com", "port": 443, "uuid": f"id-{index}"},
                source="source-02",
            ) for index in range(2)
        ]
        for node in nodes[:8]:
            node.source = "source-01"
        selected = _fair_candidate_selection(nodes, 4, {})
        self.assertEqual({node.source for node in selected}, {"source-01", "source-02"})

    def test_low_yield_source_is_demoted_after_three_runs(self):
        nodes = [
            make_node(f"a-{index}") for index in range(8)
        ] + [
            Node(
                uri=f"vless://id-{index}@other.example.com:443#b-{index}",
                scheme="vless",
                name=f"b-{index}",
                clash={"name": f"b-{index}", "type": "vless", "server": "other.example.com", "port": 443, "uuid": f"b-{index}"},
                source="source-02",
            ) for index in range(8)
        ]
        for node in nodes[:8]:
            node.source = "source-01"
        selected = _fair_candidate_selection(nodes, 8, {"source-01": {"low_yield_streak": 3}, "source-02": {}})
        self.assertGreaterEqual(sum(node.source == "source-02" for node in selected), 4)

    def test_zero_speed_limit_tests_every_latency_valid_node(self):
        nodes = [make_node("one", 100), make_node("two", 200), make_node("three", 300)]
        benchmark = MihomoBenchmark(
            binary=Path("mihomo"),
            workdir=Path(".work-test"),
            nodes=nodes,
            latency_url="https://www.google.com/generate_204",
            speed_url="https://example.com/test.bin",
            geo_url="https://api.country.is/",
            timeout_ms=8000,
            speed_bytes=1000,
            speed_limit=0,
            speed_timeout_seconds=15,
            workers=1,
        )
        benchmark.benchmark_latency = lambda candidates: candidates
        tested: list[str] = []

        def fake_speed(node: Node) -> Node:
            tested.append(node.name)
            node.speed_mbps = 1.0
            return node

        benchmark.speed = fake_speed
        benchmark.benchmark(nodes)
        self.assertEqual(tested, ["one", "two", "three"])

    def test_filter_rejects_incomplete_or_failed_measurements(self):
        nodes = [
            make_node("good", 100, 5.0),
            make_node("no-speed", 100),
            make_node("speed-error", 100, error="speed: timeout"),
            make_node("too-slow", 100, 0.1),
            make_node("too-late", 4000, 5.0),
        ]
        filtered = _filter_benchmarked_nodes(nodes, max_latency=3000, min_speed=0.5)
        self.assertEqual([node.name for node in filtered], ["good"])

    def test_filter_allows_latency_only_when_speed_is_disabled(self):
        nodes = [make_node("latency-only", 100), make_node("too-late", 4000)]
        filtered = _filter_benchmarked_nodes(
            nodes,
            max_latency=3000,
            min_speed=0.1,
            require_speed=False,
        )
        self.assertEqual([node.name for node in filtered], ["latency-only"])

    def test_speed_disabled_skips_location_checks(self):
        nodes = [make_node("source name one", 100), make_node("source name two", 200)]
        benchmark = MihomoBenchmark(
            binary=Path("mihomo"),
            workdir=Path(".work-test"),
            nodes=nodes,
            latency_url="https://www.gstatic.com/generate_204",
            speed_url="https://example.com/test.bin",
            geo_url="https://www.cloudflare.com/cdn-cgi/trace",
            timeout_ms=5000,
            speed_bytes=1000,
            speed_limit=0,
            speed_timeout_seconds=8,
            workers=1,
            speed_enabled=False,
        )
        benchmark.benchmark_latency = lambda candidates: candidates
        benchmark.geolocate = lambda node, proxy_port=None: self.fail("location lookup must stay disabled")
        benchmark.speed = lambda node: self.fail("speed test must stay disabled")
        tested = benchmark.benchmark(nodes)
        self.assertEqual([node.name for node in tested], ["source name one", "source name two"])

    def test_cloudflare_trace_geo_payload(self):
        country, exit_ip = _parse_geo_payload("ip=203.0.113.10\nloc=JP\ncolo=NRT\n")
        self.assertEqual(country, "JP")
        self.assertEqual(exit_ip, "203.0.113.10")

    def test_json_geo_payload(self):
        country, exit_ip = _parse_geo_payload('{"ip":"203.0.113.20","country":"SG"}')
        self.assertEqual(country, "SG")
        self.assertEqual(exit_ip, "203.0.113.20")

    def test_transient_google_204_failure_is_retried(self):
        node = make_node("one")
        benchmark = MihomoBenchmark(
            binary=Path("mihomo"),
            workdir=Path(".work-test"),
            nodes=[node],
            latency_url="https://www.google.com/generate_204",
            speed_url="https://example.com/test.bin",
            geo_url="https://api.country.is/",
            timeout_ms=8000,
            speed_bytes=1000,
            speed_limit=0,
            speed_timeout_seconds=8,
            workers=1,
            latency_attempts=2,
        )

        class SuccessfulResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"delay": 123}

        with patch(
            "subbench.benchmark.requests.get",
            side_effect=[requests.RequestException("temporary"), SuccessfulResponse()],
        ) as request:
            benchmark.latency(node)

        self.assertEqual(request.call_count, 2)
        self.assertEqual(node.latency_ms, 123)
        self.assertIsNone(node.error)

    def test_benchmark_traffic_is_routed_through_selected_node(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "benchmark.yaml"
            write_mihomo_config(path, [make_node("one")])
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(document["rules"], ["MATCH,BENCHMARK"])
        self.assertEqual(document["proxy-groups"], [{"name": "BENCHMARK", "type": "select", "proxies": ["one"]}])

    def test_each_node_can_use_a_dedicated_local_listener(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "benchmark.yaml"
            write_mihomo_config(path, [make_node("one")], {"one": 20000})
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(
            document["listeners"],
            [
                {
                    "name": "benchmark-0001",
                    "type": "mixed",
                    "listen": "127.0.0.1",
                    "port": 20000,
                    "proxy": "one",
                }
            ],
        )

    def test_reality_short_id_with_leading_zero_is_quoted(self):
        node = make_node("reality")
        node.clash["tls"] = True
        node.clash["reality-opts"] = {
            "public-key": "XmOcGjsWDWRVvRTF7rV77kRp63qwIYbQ_s-YK3U7FkM",
            "short-id": "09",
        }
        with TemporaryDirectory() as directory:
            path = Path(directory) / "benchmark.yaml"
            write_mihomo_config(path, [node])
            text = path.read_text(encoding="utf-8")
            document = yaml.safe_load(text)

        self.assertIn('short-id: "09"', text)
        self.assertEqual(document["proxies"][0]["reality-opts"]["short-id"], "09")


if __name__ == "__main__":
    unittest.main()
