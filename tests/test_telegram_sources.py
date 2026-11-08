import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from subbench.telegram_sources import (
    extract_subscription_urls,
    parse_feed_entries,
    record_dynamic_parse_results,
    refresh_dynamic_sources,
)


RSS = """<?xml version='1.0'?>
<rss><channel><item><guid>message-1</guid><pubDate>Sat, 08 Nov 2026 16:00:00 +0000</pubDate>
<description><![CDATA[New links https://example.com/sub?a=1 and https://example.com/second]]></description>
</item></channel></rss>"""


class TelegramSourceTests(unittest.TestCase):
    def _write_config(self, directory: Path, feeds: list[str]) -> Path:
        path = directory / "telegram.yaml"
        path.write_text(
            "ttl_hours: 24\nmax_message_age_hours: 24\nmax_urls_per_channel: 2\nmax_dynamic_urls: 3\n"
            "channels:\n  - id: fixture\n    feeds:\n" + "".join(f"      - {feed}\n" for feed in feeds),
            encoding="utf-8",
        )
        return path

    def test_parses_rss_entry_and_extracts_public_http_urls(self):
        entries = parse_feed_entries(RSS)
        self.assertEqual(entries[0]["id"], "message-1")
        self.assertEqual(
            extract_subscription_urls(entries[0]["text"]),
            ["https://example.com/sub?a=1", "https://example.com/second"],
        )
        self.assertEqual(
            extract_subscription_urls("http://127.0.0.1/x https://[::1]/x https://t.me/dns68/1"),
            [],
        )

    def test_uses_backup_feed_when_primary_fails_and_sets_expiry_from_publish_time(self):
        now = datetime(2026, 11, 8, 17, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = self._write_config(directory, ["https://primary.example/rss", "https://backup.example/rss"])
            state = directory / "dynamic.json"
            with patch("subbench.telegram_sources._fetch_rss", side_effect=[OSError("offline"), RSS]):
                urls, registry = refresh_dynamic_sources(state, config, now=now)

            self.assertEqual(urls, ["https://example.com/sub?a=1", "https://example.com/second"])
            self.assertEqual(registry["items"][0]["channel"], "fixture")
            self.assertEqual(registry["items"][0]["expires_at"], "2026-11-09T16:00:00+00:00")

    def test_prunes_expired_items_and_removes_repeated_parse_failures(self):
        now = datetime(2099, 11, 8, 17, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = self._write_config(directory, [])
            state = directory / "dynamic.json"
            state.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "items": [
                            {"url": "https://expired.example/sub", "expires_at": (now - timedelta(seconds=1)).isoformat()},
                            {"url": "https://active.example/sub", "expires_at": (now + timedelta(hours=1)).isoformat(), "parse_failures": 1},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            urls, _ = refresh_dynamic_sources(state, config, now=now)
            self.assertEqual(urls, ["https://active.example/sub"])
            record_dynamic_parse_results(state, {"https://active.example/sub": 0})
            self.assertEqual(json.loads(state.read_text(encoding="utf-8"))["items"], [])


if __name__ == "__main__":
    unittest.main()
