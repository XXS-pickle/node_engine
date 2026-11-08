from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree

import requests
import yaml

_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?)]}＞》”’"


@dataclass(frozen=True)
class TelegramChannel:
    channel_id: str
    feeds: tuple[str, ...]


@dataclass(frozen=True)
class TelegramConfig:
    ttl_hours: int
    max_message_age_hours: int
    max_urls_per_channel: int
    max_dynamic_urls: int
    channels: tuple[TelegramChannel, ...]


def load_telegram_config(path: Path) -> TelegramConfig:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return TelegramConfig(24, 24, 5, 15, ())
    raw_channels = document.get("channels") if isinstance(document, dict) else None
    channels: list[TelegramChannel] = []
    for raw in raw_channels if isinstance(raw_channels, list) else []:
        if not isinstance(raw, dict):
            continue
        channel_id = str(raw.get("id", "")).strip()
        raw_feeds = raw.get("feeds")
        if not isinstance(raw_feeds, list):
            raw_feeds = []
        feeds = tuple(
            value.strip()
            for value in raw_feeds
            if isinstance(value, str) and value.strip().startswith(("https://", "http://"))
        )
        if channel_id and feeds:
            channels.append(TelegramChannel(channel_id, feeds))
    return TelegramConfig(
        ttl_hours=max(1, int(document.get("ttl_hours", 24))) if isinstance(document, dict) else 24,
        max_message_age_hours=max(1, int(document.get("max_message_age_hours", 24))) if isinstance(document, dict) else 24,
        max_urls_per_channel=max(1, int(document.get("max_urls_per_channel", 5))) if isinstance(document, dict) else 5,
        max_dynamic_urls=max(1, int(document.get("max_dynamic_urls", 15))) if isinstance(document, dict) else 15,
        channels=tuple(channels),
    )


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _xml_text(element: ElementTree.Element) -> str:
    return " ".join(part.strip() for part in element.itertext() if part and part.strip())


def _child_text(element: ElementTree.Element, local_name: str) -> str | None:
    for child in element:
        if child.tag.rsplit("}", 1)[-1] == local_name:
            return _xml_text(child)
    return None


def parse_feed_entries(document: str) -> list[dict[str, str]]:
    """Project RSS or Atom entries into channel-neutral text/time/id fields."""
    try:
        root = ElementTree.fromstring(document)
    except ElementTree.ParseError:
        return []
    entries: list[dict[str, str]] = []
    for element in root.iter():
        kind = element.tag.rsplit("}", 1)[-1]
        if kind not in {"item", "entry"}:
            continue
        entry_id = _child_text(element, "guid") or _child_text(element, "id") or _child_text(element, "link") or ""
        published = (
            _child_text(element, "pubDate")
            or _child_text(element, "published")
            or _child_text(element, "updated")
            or ""
        )
        text = _xml_text(element)
        if text:
            entries.append({"id": entry_id, "published_at": published, "text": text})
    return entries


def extract_subscription_urls(text: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for match in _URL_RE.finditer(html.unescape(text)):
        value = match.group(0).rstrip(_TRAILING_PUNCTUATION)
        parsed = urlsplit(value)
        hostname = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not hostname:
            continue
        normalized_host = hostname.lower()
        if normalized_host == "t.me" or normalized_host.endswith(".t.me") or normalized_host.endswith("telegram.me"):
            continue
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if address is not None and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved):
            continue
        if value not in seen:
            seen.add(value)
            candidates.append(value)
    return candidates


def _fetch_rss(url: str, timeout_seconds: float) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": "node-subscription-builder/0.1"},
        timeout=(min(15.0, max(1.0, timeout_seconds)), max(1.0, timeout_seconds)),
        allow_redirects=False,
    )
    try:
        response.raise_for_status()
        if len(response.content) > 2 * 1024 * 1024:
            raise ValueError("RSS feed exceeds limit")
        return response.text
    finally:
        response.close()


def _load_registry(path: Path, now: datetime) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        document = {"version": 1, "items": []}
    items = document.get("items") if isinstance(document, dict) else []
    active: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        expiry = _parse_timestamp(str(item.get("expires_at", "")))
        if expiry and expiry > now and isinstance(item.get("url"), str):
            active.append(item)
    return {"version": 1, "items": active}


def save_registry(path: Path, registry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def refresh_dynamic_sources(
    registry_path: Path,
    config_path: Path,
    *,
    now: datetime | None = None,
    timeout_seconds: float = 20.0,
) -> tuple[list[str], dict[str, Any]]:
    """Retain unexpired candidates and discover fresh links from public RSS feeds."""
    now = now or datetime.now(UTC)
    config = load_telegram_config(config_path)
    registry = _load_registry(registry_path, now)
    by_url = {str(item["url"]): item for item in registry["items"]}
    for channel in config.channels:
        entries: list[dict[str, str]] = []
        for feed in channel.feeds:
            try:
                entries = parse_feed_entries(_fetch_rss(feed, timeout_seconds))
            except (OSError, requests.RequestException, ValueError):
                continue
            if entries:
                break
        accepted = 0
        for entry in entries:
            if accepted >= config.max_urls_per_channel:
                break
            published = _parse_timestamp(entry.get("published_at"))
            if not published or now - published > timedelta(hours=config.max_message_age_hours) or published > now + timedelta(minutes=10):
                continue
            message_id = entry.get("id") or hashlib.sha256(entry["text"].encode("utf-8")).hexdigest()[:16]
            for url in extract_subscription_urls(entry["text"]):
                if accepted >= config.max_urls_per_channel:
                    break
                existing = by_url.get(url)
                existing_published = _parse_timestamp(str(existing.get("published_at", ""))) if existing else None
                expires_at = published + timedelta(hours=config.ttl_hours)
                if existing is None or existing_published is None or published > existing_published:
                    by_url[url] = {
                        "id": hashlib.sha256(f"{channel.channel_id}|{message_id}|{url}".encode("utf-8")).hexdigest()[:20],
                        "channel": channel.channel_id,
                        "url": url,
                        "message_id": message_id[:128],
                        "published_at": published.isoformat(),
                        "first_seen_at": now.isoformat(),
                        "expires_at": expires_at.isoformat(),
                        "parse_failures": 0,
                    }
                accepted += 1
    items = sorted(by_url.values(), key=lambda item: str(item.get("published_at", "")), reverse=True)
    registry["items"] = items[: config.max_dynamic_urls]
    save_registry(registry_path, registry)
    return [str(item["url"]) for item in registry["items"]], registry


def record_dynamic_parse_results(registry_path: Path, parsed_by_url: dict[str, int]) -> None:
    now = datetime.now(UTC)
    registry = _load_registry(registry_path, now)
    retained: list[dict[str, Any]] = []
    for item in registry["items"]:
        url = str(item["url"])
        if url not in parsed_by_url:
            retained.append(item)
            continue
        parsed = parsed_by_url[url]
        item["last_checked_at"] = now.isoformat()
        item["last_node_count"] = parsed
        item["parse_failures"] = 0 if parsed > 0 else int(item.get("parse_failures", 0)) + 1
        item["last_parse_status"] = "accepted" if parsed > 0 else "rejected"
        if item["parse_failures"] < 2:
            retained.append(item)
    registry["items"] = retained
    save_registry(registry_path, registry)
