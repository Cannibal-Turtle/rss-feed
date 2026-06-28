"""Shared helpers for free/paid chapter feed generators.

This module is intentionally limited to generator-level rules:
- source-mode/scope detection from mappings
- completion-state gating for novel-scoped fetches
- shared NSFW marker detection
- shared item sorting

It does not write RSS XML and does not build free/paid RSS items, so the XML
shape stays owned by free_feed_generator.py and paid_feed_generator.py.
"""

from __future__ import annotations

import datetime
import json
import os
import re

import feedparser
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from novel_mappings import HOSTING_SITE_DATA
from config_loader import get_integration_raw_url, get_runtime_fetch_config

NSFW_PAREN_RE = re.compile(r"\([^)]*\b(?:nsfw|r-?18|18\+|h{1,3})\b[^)]*\)", re.I)

FEED_URL_KEYS = {
    "free": "free_feed_url",
    "paid": "paid_feed_url",
}

SOURCE_MODE_KEYS = {
    "free": "free_chapters_source",
    "paid": "paid_chapters_source",
}


def has_nsfw_marker(*texts: str) -> bool:
    for text in texts:
        if text and NSFW_PAREN_RE.search(str(text)):
            return True
    return False


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False

    text = str(value).strip().casefold()
    return text in {"1", "true", "yes", "y", "on"}


def normalize_title_key(title: str) -> str:
    return re.sub(r"\s+", " ", str(title or "")).strip().casefold()


def entry_matches_chapter_type(utils: dict[str, Any], entry: Any, chapter_type: str) -> bool:
    """Return whether one source entry belongs in this generated feed.

    Default is True to preserve old behavior. Hosts with mixed free/paid RSS
    feeds can expose one of these hooks in their utils dict:
      - entry_matches_chapter_type(entry, "free"/"paid")
      - is_free_entry(entry) / is_paid_entry(entry)
      - entry_is_free(entry) / entry_is_paid(entry)
    """

    chapter_type = str(chapter_type or "").strip().casefold()
    utils = utils or {}

    checker = utils.get("entry_matches_chapter_type")
    if callable(checker):
        try:
            return bool(checker(entry, chapter_type))
        except TypeError:
            return bool(checker(entry))
        except Exception as exc:
            print(f"Warning: entry_matches_chapter_type failed for {chapter_type}: {exc}")
            return True

    for name in (f"is_{chapter_type}_entry", f"entry_is_{chapter_type}"):
        checker = utils.get(name)
        if callable(checker):
            try:
                return bool(checker(entry))
            except Exception as exc:
                print(f"Warning: {name} failed: {exc}")
                return True

    return True


# ---------------- Fetch/Concurrency Helpers ----------------

def _safe_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _first_runtime_int(fetch_cfg: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        if key in fetch_cfg and str(fetch_cfg.get(key, "")).strip() != "":
            value = _safe_int(fetch_cfg.get(key))
            if value is not None:
                return value
    return None


def chapter_fetch_concurrency(
    chapter_type: str = "",
    default: int = 6,
    *,
    max_value: int | None = None,
) -> int:
    """Return the concurrency limit for novel-scoped chapter fetches.

    Priority:
      1. FREE_FETCH_CONCURRENCY / PAID_FETCH_CONCURRENCY env
      2. CHAPTER_FETCH_CONCURRENCY env
      3. config/runtime.json free_fetch_concurrency / paid_fetch_concurrency
      4. config/runtime.json chapter_fetch_concurrency
      5. default
    """

    chapter_type_upper = str(chapter_type or "").strip().upper()
    chapter_type_lower = str(chapter_type or "").strip().casefold()

    env_keys: list[str] = []
    if chapter_type_upper:
        env_keys.append(f"{chapter_type_upper}_FETCH_CONCURRENCY")
    env_keys.append("CHAPTER_FETCH_CONCURRENCY")

    value: int | None = None
    for key in env_keys:
        raw = str(os.getenv(key, "") or "").strip()
        if raw:
            value = _safe_int(raw)
            if value is not None:
                break

    fetch_cfg = get_runtime_fetch_config()

    if value is None:
        config_keys: list[str] = []
        if chapter_type_lower:
            config_keys.append(f"{chapter_type_lower}_fetch_concurrency")
        config_keys.append("chapter_fetch_concurrency")
        value = _first_runtime_int(fetch_cfg, tuple(config_keys))

    if value is None:
        value = default

    value = max(1, int(value))

    config_max = _first_runtime_int(
        fetch_cfg,
        tuple(
            key
            for key in (
                f"max_{chapter_type_lower}_fetch_concurrency" if chapter_type_lower else "",
                "max_chapter_fetch_concurrency",
            )
            if key
        ),
    )

    limits = [candidate for candidate in (max_value, config_max) if candidate is not None]
    if limits:
        value = min(value, max(1, min(int(candidate) for candidate in limits)))

    return value


async def fetch_parsed_feed_async(session: Any, feed_url: str, *, semaphore: Any, label: str = "Feed"):
    """Fetch one RSS/Atom feed with aiohttp and return a feedparser result."""

    async with semaphore:
        try:
            async with session.get(feed_url, timeout=30) as resp:
                if resp.status >= 400:
                    print(f"{label} fetch failed: {feed_url} → HTTP {resp.status}")
                    return feedparser.parse("")
                text = await resp.text()
        except Exception as exc:
            print(f"{label} fetch failed: {feed_url} → {exc}")
            return feedparser.parse("")

    return feedparser.parse(text)


# ---------------- Source Scope Helpers ----------------

def host_data_for(host: str) -> dict[str, Any]:
    return HOSTING_SITE_DATA.get(host, {}) or {}


def novels_for_host(host: str) -> dict[str, dict[str, Any]]:
    return host_data_for(host).get("novels", {}) or {}


def chapter_source_mode(host: str, chapter_type: str) -> str:
    """Return host source mode for this chapter type: "feed" or "api".

    If the host TOML does not say explicitly:
    - free defaults to feed, unless there is no free_feed_url but there is a chapters_api_url
    - paid defaults to feed when paid_feed_url exists, otherwise api
    """

    chapter_type = str(chapter_type or "").strip().casefold()
    host_data = host_data_for(host)

    key = SOURCE_MODE_KEYS.get(chapter_type, "")
    raw = str(host_data.get(key, "") or "").strip().casefold()
    if raw in {"feed", "api"}:
        return raw

    if chapter_type == "free":
        return "api" if host_data.get("chapters_api_url") and not host_data.get("free_feed_url") else "feed"

    if chapter_type == "paid":
        return "feed" if host_data.get("paid_feed_url") else "api"

    return "feed"


def host_level_feed_url(host: str, chapter_type: str) -> str:
    """Return only the host-level feed URL, without novel fallback."""

    key = FEED_URL_KEYS.get(str(chapter_type or "").strip().casefold(), "")
    if not key:
        return ""
    return str(host_data_for(host).get(key, "") or "").strip()


def slug_from_url(url: str) -> str:
    value = str(url or "").strip().rstrip("/")
    if not value:
        return ""
    return value.split("/")[-1]


def fill_novel_template(template: str, novel_title: str, details: dict[str, Any]) -> str:
    value = str(template or "")

    novel_url = str(details.get("novel_url") or "").strip()
    slug = str(details.get("slug") or slug_from_url(novel_url) or "").strip()
    novel_id = str(details.get("novel_id") or details.get("id") or "").strip()
    short_code = str(details.get("short_code") or "").strip()

    replacements = {
        "{slug}": slug,
        "{novel_slug}": slug,
        "{novel_url_slug}": slug,
        "{novel_id}": novel_id,
        "{id}": novel_id,
        "{novel_url}": novel_url,
        "{title}": novel_title,
        "{short_code}": short_code,
    }

    for key, replacement in replacements.items():
        value = value.replace(key, replacement)

    return value.strip()


def resolved_novel_feed_url(host: str, novel_title: str, details: dict[str, Any], chapter_type: str) -> str:
    raw = novel_level_feed_url(details, chapter_type) or host_level_feed_url(host, chapter_type)
    return fill_novel_template(raw, novel_title, details)


def novel_level_feed_url(details: dict[str, Any], chapter_type: str) -> str:
    """Return only the novel-level feed URL, without host fallback."""

    key = FEED_URL_KEYS.get(str(chapter_type or "").strip().casefold(), "")
    if not key:
        return ""
    return str((details or {}).get(key, "") or "").strip()


def chapters_api_template(host: str, details: dict[str, Any] | None = None) -> str:
    details = details or {}
    return str(details.get("chapters_api_url") or host_data_for(host).get("chapters_api_url") or "").strip()


NOVEL_URL_MARKERS = (
    "{slug}",
    "{novel_slug}",
    "{novel_url_slug}",
    "{novel_id}",
    "{id}",
    "{novel_url}",
    "{title}",
    "{short_code}",
)


def needs_novel_value(template: str) -> bool:
    lowered = str(template or "").casefold()
    return any(marker in lowered for marker in NOVEL_URL_MARKERS)

def api_source_scope(host: str, details: dict[str, Any] | None = None) -> str:
    """Return "novel" or "host" for a chapters API template.

    A host-level template can still be novel-scoped if it needs a novel slug/id/url.
    Example: chapters_api_url = ".../slug/{slug}/chapters" is novel-scoped.
    """

    template = chapters_api_template(host, details)
    if not template:
        return ""

    if needs_novel_value(template):
        return "novel"

    # If the API URL is defined directly on one novel, treat it as novel-scoped.
    if details and details.get("chapters_api_url"):
        return "novel"

    return "host"


def source_scope_for(host: str, novel_title: str, details: dict[str, Any], chapter_type: str) -> str:
    """Return one of host_feed, novel_feed, host_api, novel_api, or "".

    This reads the mapping shape instead of using novel→host fallback getters,
    so the generator can tell where a source lives.
    """

    mode = chapter_source_mode(host, chapter_type)

    if mode == "feed":
        novel_feed = novel_level_feed_url(details, chapter_type)
        if novel_feed:
            return "novel_feed"

        host_feed = host_level_feed_url(host, chapter_type)
        if host_feed:
            return "novel_feed" if needs_novel_value(host_feed) else "host_feed"

        return ""

    if mode == "api":
        scope = api_source_scope(host, details)
        if scope == "novel":
            return "novel_api"
        if scope == "host":
            return "host_api"
        return ""

    return ""


# ---------------- Completion State Gate ----------------

def completion_state_url() -> str:
    env_url = str(os.getenv("COMPLETION_STATE_URL") or "").strip()

    if env_url:
        return env_url

    integration = os.getenv("DISCORD_INTEGRATION", "discord_webhook").strip() or "discord_webhook"
    return get_integration_raw_url(integration, "state", "state.json")


def completion_state_path() -> str:
    return str(
        os.getenv("COMPLETION_STATE_PATH")
        or os.getenv("DISCORD_WEBHOOK_STATE_PATH")
        or ""
    ).strip()


def _load_json_path(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        print(f"Warning: completion state path does not exist: {path}")
        return {}

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Warning: could not read completion state path {path}: {e}")
        return {}

    if not isinstance(data, dict):
        print(f"Warning: completion state is not a JSON object: {path}")
        return {}

    return data


def _load_json_url(url: str) -> dict[str, Any]:
    if not url:
        return {}

    try:
        req = Request(url, headers={"User-Agent": "rss-feed-generator/1.0"})
        with urlopen(req, timeout=20) as resp:
            status = getattr(resp, "status", 200)
            if status != 200:
                print(f"Warning: completion state returned HTTP {status}: {url}")
                return {}
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Warning: could not fetch completion state {url}: {e}")
        return {}

    if not isinstance(data, dict):
        print(f"Warning: completion state is not a JSON object: {url}")
        return {}

    return data


def load_completion_state() -> dict[str, Any]:
    """Load canonical discord-webhook/state.json.

    Path env wins for local testing; otherwise use integrations.json URL.
    Missing/unreadable state returns {}, which means "do not skip anything".
    """

    path = completion_state_path()
    if path:
        return _load_json_path(path)

    return _load_json_url(completion_state_url())


def completion_key_for(chapter_type: str, novel_details: dict[str, Any]) -> str:
    chapter_type = str(chapter_type or "").strip().casefold()

    if chapter_type == "paid":
        return "paid_completion"

    if chapter_type == "free":
        return "free_completion" if (novel_details or {}).get("paid_feed") else "only_free_completion"

    return ""


def completion_announced(
    novel_title: str,
    chapter_type: str,
    novel_details: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
) -> bool:
    state = state if isinstance(state, dict) else {}
    key = completion_key_for(chapter_type, novel_details)
    if not key:
        return False

    wanted = normalize_title_key(novel_title)
    for title, record in state.items():
        if normalize_title_key(title) != wanted:
            continue
        return isinstance(record, dict) and bool(record.get(key))

    return False


def should_skip_completed(
    novel_title: str,
    chapter_type: str,
    novel_details: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
    force: bool = False,
) -> bool:
    if force:
        return False
    return completion_announced(novel_title, chapter_type, novel_details, state=state)


# ---------------- Shared Feed Sorting ----------------

def _normalized_pubdate(item):
    dt = getattr(item, "pubDate", None)

    if not isinstance(dt, datetime.datetime):
        return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)

    return dt.astimezone(datetime.timezone.utc).replace(microsecond=0)


def _novel_alpha_sort_key(item):
    return (
        getattr(item, "host", "").casefold(),
        getattr(item, "title", "").casefold(),
    )


def _chapter_sort_key(item):
    from host_utils import get_host_utils

    return get_host_utils(getattr(item, "host", "")).get(
        "chapter_num", lambda s: (0,)
    )(getattr(item, "chapter", ""))


def sort_feed_items(items):
    """
    Sort newest pubDate first.

    Tie-breakers:
      1. host/title alphabetical
      2. chapter number newest first within the same novel/date
    """
    # weakest tie-breaker first
    items.sort(key=_chapter_sort_key, reverse=True)

    # then alphabetical novel tie-breaker
    items.sort(key=_novel_alpha_sort_key)

    # strongest sort last
    items.sort(key=_normalized_pubdate, reverse=True)
