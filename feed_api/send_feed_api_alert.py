#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime as _dt
import os
import sys
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import feedparser
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_loader import (  # noqa: E402
    get_integration_channel_id,
    load_integrations_config,
)
from feed_common import (  # noqa: E402
    chapter_source_mode,
    feed_looks_capped_at_current_batch,
    host_level_feed_url,
    needs_novel_value,
)
from message_renderer import render_message, to_discord_api_payload  # noqa: E402
from novel_mappings import HOSTING_SITE_DATA  # noqa: E402

API_BASE = "https://discord.com/api/v10"
DEFAULT_FEED_PATHS = {
    "free": "free_chapters_feed.xml",
    "paid": "paid_chapters_feed.xml",
}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y", "on"}


def _utc_second(value: Any) -> _dt.datetime | None:
    if not isinstance(value, _dt.datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=_dt.timezone.utc)
    return value.astimezone(_dt.timezone.utc).replace(microsecond=0)


def _entry_pub_date(entry: Any) -> _dt.datetime | None:
    tt = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if tt:
        return _dt.datetime(*tt[:6], tzinfo=_dt.timezone.utc)

    raw = getattr(entry, "published", "") or getattr(entry, "updated", "") or ""
    if raw:
        try:
            return parsedate_to_datetime(raw)
        except Exception:
            return None

    return None


def _parse_pub_date(text: str) -> _dt.datetime | None:
    text = str(text or "").strip()
    if not text:
        return None

    try:
        return parsedate_to_datetime(text)
    except Exception:
        pass

    try:
        return _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _feed_entry_keys(entry: Any) -> set[str]:
    keys: set[str] = set()
    for attr in ("id", "guid", "link"):
        value = str(getattr(entry, attr, "") or "").strip()
        if value:
            keys.add(value)
    return keys


def _item_key(item: dict[str, Any]) -> str:
    return str(item.get("guid") or item.get("link") or "").strip()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _child_text(elem: ET.Element, name: str) -> str:
    for child in elem:
        if _local_name(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _read_generated_items(feed_path: Path) -> list[dict[str, Any]]:
    if not feed_path.exists():
        print(f"[feed_api alert] {feed_path} does not exist; skipping.")
        return []

    try:
        root = ET.parse(feed_path).getroot()
    except Exception as exc:
        print(f"[feed_api alert] Could not parse {feed_path}: {exc}")
        return []

    items: list[dict[str, Any]] = []
    for elem in root.iter():
        if _local_name(elem.tag) != "item":
            continue

        items.append({
            "title": _child_text(elem, "title"),
            "volume": _child_text(elem, "volume"),
            "chapter": _child_text(elem, "chapter"),
            "chaptername": _child_text(elem, "chaptername"),
            "link": _child_text(elem, "link"),
            "guid": _child_text(elem, "guid"),
            "pubDate": _parse_pub_date(_child_text(elem, "pubDate")),
            "host": _child_text(elem, "host"),
        })

    return items


def _chapter_label(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "Unknown novel").strip() or "Unknown novel"
    volume = str(item.get("volume") or "").strip()
    chapter = str(item.get("chapter") or "").strip()
    chaptername = str(item.get("chaptername") or "").strip()

    if volume and chapter:
        main = f"{volume}, {chapter}"
    else:
        main = volume or chapter

    if main and chaptername:
        detail = f"{main} — {chaptername}"
    else:
        detail = main or chaptername

    return f"{title} — {detail}" if detail else title


def _feed_label(chapter_type: str) -> str:
    return "public" if chapter_type == "free" else chapter_type


def _format_missing_lines(host: str, chapter_type: str, items: list[dict[str, Any]], *, max_items: int) -> str:
    feed_label = _feed_label(chapter_type)
    shown = items[:max_items]
    lines = [
        f"««« {_chapter_label(item)} not picked up by {host} {feed_label} feed"
        for item in shown
    ]
    extra = len(items) - len(shown)
    if extra > 0:
        lines.append(f"««« +{extra} more not picked up by {host} {feed_label} feed")
    return "\n".join(lines)


def _load_alert_config() -> dict[str, Any]:
    cfg = load_integrations_config()
    return _as_dict(cfg.get("feed_api_alerts", {}))


def _enabled(config: dict[str, Any]) -> bool:
    if _truthy(os.getenv("FEED_API_ALERTS_DISABLED")):
        return False

    override = os.getenv("FEED_API_ALERTS_ENABLED", "").strip()
    if override:
        return _truthy(override)

    return _truthy(config.get("enabled", False))


def _resolve_channel_id(config: dict[str, Any]) -> str:
    env_channel = (
        os.getenv("FEED_API_ALERT_CHANNEL_ID")
        or os.getenv("DISCORD_MOD_CHANNEL_ID")
        or ""
    ).strip()
    if env_channel:
        return env_channel

    direct = str(config.get("channel_id") or "").strip()
    if direct:
        return direct

    integration = str(
        os.getenv("FEED_API_ALERT_INTEGRATION")
        or config.get("integration")
        or "discord_webhook"
    ).strip() or "discord_webhook"
    channel_key = str(
        os.getenv("FEED_API_ALERT_CHANNEL_KEY")
        or config.get("channel_key")
        or "mod"
    ).strip() or "mod"

    return get_integration_channel_id(integration, channel_key)


def _send_discord_message(config: dict[str, Any], ctx: dict[str, Any]) -> bool:
    token = str(os.getenv("DISCORD_BOT_TOKEN") or "").strip()
    if not token:
        print("[feed_api alert] DISCORD_BOT_TOKEN not set; skipping Discord alert.")
        return False

    channel_id = _resolve_channel_id(config)
    if not channel_id:
        print("[feed_api alert] alert channel is not configured; skipping Discord alert.")
        return False

    payload = to_discord_api_payload(render_message("feed_api_alert", ctx))

    try:
        r = requests.post(
            f"{API_BASE}/channels/{int(channel_id)}/messages",
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
    except Exception as exc:
        print(f"[feed_api alert] Discord send failed: {exc}")
        return False

    if r.status_code >= 400:
        print(f"[feed_api alert] Discord send failed: HTTP {r.status_code}")
        print(r.text)
        return False

    return True


def _missing_items_for_host(
    *,
    host: str,
    chapter_type: str,
    generated_items: list[dict[str, Any]],
) -> tuple[str, _dt.datetime | None, list[dict[str, Any]]]:
    mode = chapter_source_mode(host, chapter_type)
    if mode != "feed_api":
        return "", None, []

    feed_url = host_level_feed_url(host, chapter_type)
    if not feed_url or needs_novel_value(feed_url):
        return "", None, []

    parsed_feed = feedparser.parse(feed_url)
    if not feed_looks_capped_at_current_batch(parsed_feed):
        return "", None, []

    entries = list(getattr(parsed_feed, "entries", []) or [])
    if not entries:
        return "", None, []

    batch_dt = _utc_second(_entry_pub_date(entries[-1]))
    feed_keys: set[str] = set()
    for entry in entries:
        feed_keys.update(_feed_entry_keys(entry))

    missing: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in generated_items:
        if str(item.get("host") or "").strip() != host:
            continue

        key = _item_key(item)
        if not key or key in feed_keys or key in seen:
            continue

        if batch_dt is not None and _utc_second(item.get("pubDate")) != batch_dt:
            continue

        seen.add(key)
        missing.append(item)

    reason = (
        f"{host} {chapter_type} feed shows {len(entries)} visible entries "
        "and the oldest visible row is still in the current batch"
    )
    return reason, batch_dt, missing


def main(argv: list[str]) -> int:
    chapter_type = (argv[1] if len(argv) > 1 else os.getenv("FEED_API_ALERT_TYPE", "free")).strip().casefold()
    if chapter_type not in DEFAULT_FEED_PATHS:
        print("Usage: python feed_api/send_feed_api_alert.py [free|paid]")
        return 2

    config = _load_alert_config()
    if not _enabled(config):
        print("[feed_api alert] disabled in config; skipping.")
        return 0

    feed_path = Path(
        os.getenv("FEED_API_ALERT_FEED_PATH")
        or config.get(f"{chapter_type}_feed_path")
        or DEFAULT_FEED_PATHS[chapter_type]
    )
    if not feed_path.is_absolute():
        feed_path = ROOT / feed_path

    generated_items = _read_generated_items(feed_path)
    if not generated_items:
        print("[feed_api alert] generated feed has no items; skipping.")
        return 0

    mention = str(os.getenv("FEED_API_ALERT_MENTION") or config.get("mention") or "").strip()
    mode_label = str(config.get("mode_label") or "api fallback").strip() or "api fallback"
    max_items = int(config.get("max_items") or 10)

    sent = 0
    for host in HOSTING_SITE_DATA:
        reason, _batch_dt, missing = _missing_items_for_host(
            host=host,
            chapter_type=chapter_type,
            generated_items=generated_items,
        )
        if not missing:
            continue

        print(f"[feed_api alert] {reason}; found {len(missing)} missing generated item(s).")
        missing_lines = _format_missing_lines(
            host,
            chapter_type,
            missing,
            max_items=max(1, max_items),
        )

        ctx = {
            "mention": mention,
            "host": host,
            "mode": mode_label,
            "chapter_type": chapter_type,
            "feed_label": _feed_label(chapter_type),
            "missing_lines": missing_lines,
            "missing_count": len(missing),
        }
        if _send_discord_message(config, ctx):
            sent += 1

    if sent:
        print(f"[feed_api alert] sent {sent} Discord alert message(s).")
    else:
        print("[feed_api alert] no alert sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
