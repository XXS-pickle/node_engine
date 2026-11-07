import base64
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote

import yaml

from subbench.models import Node
from subbench.output import _branding_suffix, _rename_uri, write_outputs


class OutputTests(unittest.TestCase):
    def test_vless_fragment_is_replaced(self):
        rendered = _rename_uri("vless://id@example.com:443?security=tls#old", "vless", "🇺🇸 美国 | VLESS | 001")
        self.assertEqual(unquote(rendered.split("#", 1)[1]), "🇺🇸 美国 | VLESS | 001")

    def test_vmess_display_name_is_replaced(self):
        payload = base64.urlsafe_b64encode(json.dumps({"ps": "old", "add": "example.com"}).encode()).decode().rstrip("=")
        rendered = _rename_uri(f"vmess://{payload}", "vmess", "🇯🇵 日本 | VMESS | 001")
        encoded = rendered.split("://", 1)[1]
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        self.assertEqual(json.loads(decoded)["ps"], "🇯🇵 日本 | VMESS | 001")

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

    def test_branding_suffix_can_be_provided_by_environment(self):
        previous = os.environ.get("BRANDING_SUFFIX")
        try:
            os.environ["BRANDING_SUFFIX"] = " | test"
            self.assertEqual(_branding_suffix(), " | test")
        finally:
            if previous is None:
                os.environ.pop("BRANDING_SUFFIX", None)
            else:
                os.environ["BRANDING_SUFFIX"] = previous

    def test_channel_branding_is_unique_and_idempotent(self):
        suffix = " | tg@zzyyffxx"
        nodes = [
            Node(
                uri="vless://id@one.example:443?security=tls#Foo",
                scheme="vless",
                name="Foo",
                clash={"name": "Foo", "type": "vless", "server": "one.example", "port": 443, "uuid": "id"},
                source="source-01",
            ),
            Node(
                uri="vless://id@two.example:443?security=tls#Foo",
                scheme="vless",
                name=f"Foo{suffix}",
                clash={"name": f"Foo{suffix}", "type": "vless", "server": "two.example", "port": 443, "uuid": "id"},
                source="source-02",
            ),
            Node(
                uri="vless://id@three.example:443?security=tls#name",
                scheme="vless",
                name="tg@zzyyffxx",
                clash={"name": "tg@zzyyffxx", "type": "vless", "server": "three.example", "port": 443, "uuid": "id"},
                source="source-03",
            ),
        ]
        with TemporaryDirectory() as directory:
            output = Path(directory)
            write_outputs(output, nodes, [])
            clash = yaml.safe_load((output / "clash.yaml").read_text(encoding="utf-8"))
            raw_uris = (output / "v2ray-raw.txt").read_text(encoding="utf-8").splitlines()
        names = [proxy["name"] for proxy in clash["proxies"]]
        self.assertEqual(names, [f"Foo{suffix}", f"Foo_2{suffix}", f"tg@zzyyffxx{suffix}"])
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(name.endswith(suffix) for name in names))
        self.assertTrue(all(unquote(uri.split("#", 1)[1]) in names for uri in raw_uris))


if __name__ == "__main__":
    unittest.main()
