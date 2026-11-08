from __future__ import annotations

import base64
import binascii
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import yaml

from .models import Node


COUNTRY_NAMES = {
    "HK": "香港",
    "TW": "台湾",
    "JP": "日本",
    "SG": "新加坡",
    "US": "美国",
    "KR": "韩国",
    "GB": "英国",
    "DE": "德国",
    "FR": "法国",
    "CA": "加拿大",
    "NL": "荷兰",
    "AU": "澳大利亚",
    "RU": "俄罗斯",
    "IN": "印度",
    "TR": "土耳其",
    "TH": "泰国",
    "MY": "马来西亚",
    "ID": "印度尼西亚",
    "PH": "菲律宾",
    "VN": "越南",
    "BR": "巴西",
    "AE": "阿联酋",
}


def prepare_names(nodes: list[Node]) -> None:
    """Give Mihomo internal benchmark proxies stable, unique temporary names."""
    used: set[str] = {"AUTO", "PROXY", "BENCHMARK", "DIRECT"}
    for index, node in enumerate(nodes, start=1):
        base = f"node-{index:04d}"
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}-{suffix}"
            suffix += 1
        used.add(candidate)
        node.name = candidate
        if node.clash:
            node.clash["name"] = candidate


def _flag(country_code: str) -> str:
    if len(country_code) != 2 or not country_code.isalpha():
        return "🌐"
    return "".join(chr(0x1F1E6 + ord(letter) - ord("A")) for letter in country_code.upper())


def _region_label(node: Node) -> str:
    country_code = str(node.metadata.get("country_code") or "").upper()
    if not country_code:
        return "🌐 未知"
    return f"{_flag(country_code)} {COUNTRY_NAMES.get(country_code, country_code)}"


def _region_group_label(node: Node) -> str:
    country_code = str(node.metadata.get("country_code") or "").upper()
    if country_code in {"US", "SG", "JP", "HK"}:
        return _region_label(node)
    return "🌐 其他国家"


def _numbered_name(label: str, number: int) -> str:
    width = max(2, len(str(number)))
    return f"{label} {number:0{width}d}"


def _channel_suffix() -> str:
    """Return the optional promotion suffix without exposing source metadata."""
    suffix = " ".join(str(os.environ.get("BRANDING_SUFFIX", "")).split())
    if suffix:
        suffix = " " + suffix
    return suffix[:80]


def apply_display_names(nodes: list[Node]) -> dict[str, list[str]]:
    """Replace source labels with short country/number names and an optional suffix."""
    counters: Counter[str] = Counter()
    grouped: dict[str, list[str]] = defaultdict(list)
    suffix = _channel_suffix()
    for node in nodes:
        label = _region_label(node)
        counters[label] += 1
        base_name = _numbered_name(label, counters[label])
        node.name = f"{base_name}{suffix}" if suffix else base_name
        if node.clash:
            node.clash["name"] = node.name
        grouped[label].append(node.name)
    return dict(grouped)


def _rename_uri(uri: str, scheme: str, name: str) -> str:
    if scheme == "vmess" and uri.startswith("vmess://"):
        try:
            encoded = uri.split("://", 1)[1].split("#", 1)[0]
            padded = encoded + "=" * (-len(encoded) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
            payload["ps"] = name
            rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            return "vmess://" + base64.urlsafe_b64encode(rendered).decode("ascii").rstrip("=")
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
            return uri
    main = uri.split("#", 1)[0]
    return f"{main}#{quote(name, safe='')}"


def _proxy_groups(nodes: list[Node], grouped_names: dict[str, list[str]]) -> list[dict[str, object]]:
    all_names = [node.name for node in nodes]
    speed_names = [node.name for node in nodes if node.speed_mbps is not None]
    grouped_regions: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        grouped_regions[_region_group_label(node)].append(node.name)
    ordered_regions = sorted(grouped_regions, key=lambda label: (-len(grouped_regions[label]), label))
    featured_regions = ordered_regions[:12]
    covered = {name for label in featured_regions for name in grouped_regions[label]}
    other_names = [name for name in all_names if name not in covered]

    groups: list[dict[str, object]] = [
        {
            "name": "🚀 自动优选",
            "type": "url-test",
            "url": "https://cp.cloudflare.com/generate_204",
            "interval": 300,
            "tolerance": 100,
            "proxies": all_names,
        },
        {
            "name": "⚡ 速度优选",
            "type": "select",
            "proxies": ["🚀 自动优选", *speed_names],
        },
    ]
    for label in featured_regions:
        groups.append({"name": label, "type": "select", "proxies": grouped_regions[label]})
    if other_names:
        groups.append({"name": "🌐 其他国家", "type": "select", "proxies": other_names})
    groups.append({"name": "🌐 全部节点", "type": "select", "proxies": all_names})
    manual_choices = [
        "🚀 自动优选",
        "⚡ 速度优选",
        *featured_regions,
        *( ["🌐 其他国家"] if other_names else [] ),
        "🌐 全部节点",
        "DIRECT",
    ]
    return [{"name": "🎯 手动选择", "type": "select", "proxies": manual_choices}, *groups]


def write_outputs(
    output_dir: Path,
    nodes: list[Node],
    source_errors: list[dict[str, str]],
    source_stats: dict[str, dict[str, int]] | None = None,
) -> None:
    if not nodes:
        raise ValueError("Refusing to write empty subscription outputs.")
    output_dir.mkdir(parents=True, exist_ok=True)
    grouped_names = apply_display_names(nodes)

    uris = [_rename_uri(node.uri, node.scheme, node.name) for node in nodes if node.uri]
    raw = "\n".join(uris) + ("\n" if uris else "")
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    (output_dir / "v2ray.txt").write_text(encoded + "\n", encoding="ascii")
    (output_dir / "v2ray-raw.txt").write_text(raw, encoding="utf-8")

    proxies = [node.clash for node in nodes if node.clash]
    names = [proxy["name"] for proxy in proxies]
    if not proxies or len(names) != len(set(names)):
        raise ValueError("Final Clash proxy names are empty or duplicated.")
    clash_config = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
        "proxies": proxies,
        "proxy-groups": _proxy_groups(nodes, grouped_names),
        "rules": ["MATCH,🎯 手动选择"],
    }
    (output_dir / "clash.yaml").write_text(
        yaml.safe_dump(clash_config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "node_count": len(nodes),
        "source_errors": source_errors,
        "source_quality": source_stats or {},
        "nodes": [node.report_dict() for node in nodes],
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    rows = "".join(
        f"<tr><td>{index}</td><td>{node.name}</td><td>{node.scheme}</td>"
        f"<td>{node.latency_ms or '-'} ms</td><td>{node.speed_mbps or '-'} Mbps</td></tr>"
        for index, node in enumerate(nodes, start=1)
    )
    page = f"""<!doctype html>
<meta charset="utf-8">
<title>Node subscriptions</title>
<style>body{{font:16px system-ui,sans-serif;max-width:1000px;margin:40px auto;padding:0 20px}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ddd;padding:8px;text-align:left}}code{{background:#f3f3f3;padding:2px 4px}}</style>
<h1>Node subscriptions</h1>
<p>Generated {report['generated_at']} with {len(nodes)} usable nodes.</p>
<ul><li><a href="v2ray.txt">V2Ray Base64 subscription</a></li><li><a href="clash.yaml">Clash/Mihomo config</a></li><li><a href="v2ray-raw.txt">Raw links</a></li><li><a href="report.json">JSON report</a></li></ul>
<table><thead><tr><th>#</th><th>Name</th><th>Type</th><th>Latency</th><th>Speed</th></tr></thead><tbody>{rows}</tbody></table>
"""
    (output_dir / "index.html").write_text(page, encoding="utf-8")
