import base64
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote

import yaml

from subbench.models import Node
from subbench.output import _rename_uri, write_outputs


def make_node(name: str, country: str | None = None, speed: float | None = None) -> Node:
    node = Node(
        uri=f"vless://id@{name}.example:443?security=tls#{name}",
        scheme="vless",
        name=name,
        clash={"name": name, "type": "vless", "server": f"{name}.example", "port": 443, "uuid": "id"},
        source="source-01",
        latency_ms=100,
        speed_mbps=speed,
    )
    if country:
        node.metadata["country_code"] = country
    return node


class OutputTests(unittest.TestCase):
    def test_vless_fragment_is_replaced(self):
        rendered = _rename_uri("vless://id@example.com:443?security=tls#old", "vless", "🇺🇸 美国 01")
        self.assertEqual(unquote(rendered.split("#", 1)[1]), "🇺🇸 美国 01")

    def test_vmess_display_name_is_replaced(self):
        payload = base64.urlsafe_b64encode(json.dumps({"ps": "old", "add": "example.com"}).encode()).decode().rstrip("=")
        rendered = _rename_uri(f"vmess://{payload}", "vmess", "🇯🇵 日本 01")
        encoded = rendered.split("://", 1)[1]
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        self.assertEqual(json.loads(decoded)["ps"], "🇯🇵 日本 01")

    def test_empty_subscription_is_refused(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "public"
            with self.assertRaisesRegex(ValueError, "empty"):
                write_outputs(output, [], [])
            self.assertFalse(output.exists())

    def test_empty_subscription_keeps_previous_clash_output(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "public"
            output.mkdir()
            clash_path = output / "clash.yaml"
            clash_path.write_text("last-known-good", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "empty"):
                write_outputs(output, [], [])
            self.assertEqual(clash_path.read_text(encoding="utf-8"), "last-known-good")

    def test_output_uses_short_country_number_names_and_hides_original_names(self):
        nodes = [
            make_node("untrusted source name one", "JP", 12.5),
            make_node("untrusted source name two", "JP"),
            make_node("very long upstream label", "US", 6.2),
            make_node("other upstream label"),
        ]
        with TemporaryDirectory() as directory:
            output = Path(directory)
            write_outputs(output, nodes, [])
            clash = yaml.safe_load((output / "clash.yaml").read_text(encoding="utf-8"))
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            raw_uris = (output / "v2ray-raw.txt").read_text(encoding="utf-8").splitlines()
        names = [proxy["name"] for proxy in clash["proxies"]]
        self.assertEqual(names, ["🇯🇵 日本 01", "🇯🇵 日本 02", "🇺🇸 美国 01", "🌐 未知 01"])
        self.assertTrue(all("upstream" not in name and "source" not in name for name in names))
        self.assertTrue(all(unquote(uri.split("#", 1)[1]) in names for uri in raw_uris))
        self.assertTrue(all("original_name" not in item for item in report["nodes"]))

    def test_output_generates_manual_auto_speed_and_region_groups(self):
        nodes = [make_node("one", "HK", 20.0), make_node("two", "JP", 5.0), make_node("three", "JP")]
        with TemporaryDirectory() as directory:
            output = Path(directory)
            write_outputs(output, nodes, [])
            clash = yaml.safe_load((output / "clash.yaml").read_text(encoding="utf-8"))
        groups = {item["name"]: item for item in clash["proxy-groups"]}
        self.assertEqual(clash["rules"], ["MATCH,🎯 手动选择"])
        self.assertEqual(groups["🚀 自动优选"]["url"], "https://cp.cloudflare.com/generate_204")
        self.assertIn("🇭🇰 香港", groups)
        self.assertIn("🇯🇵 日本", groups)
        self.assertEqual(groups["⚡ 速度优选"]["proxies"][:2], ["🚀 自动优选", "🇭🇰 香港 01"])
        self.assertIn("🌐 全部节点", groups["🎯 手动选择"]["proxies"])


if __name__ == "__main__":
    unittest.main()
