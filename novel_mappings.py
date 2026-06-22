"""
novel_mappings.py

Compatibility loader/front door for JSON-backed novel mapping data.

Dependent scripts can keep using:

    from novel_mappings import HOSTING_SITE_DATA

Actual mapping data lives in:

    mappings/hosts/*.json
    mappings/novels/*.json
    mappings/output_feeds.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
MAPPINGS_DIR = ROOT / "mappings"
HOSTS_DIR = MAPPINGS_DIR / "hosts"
NOVELS_DIR = MAPPINGS_DIR / "novels"
OUTPUT_FEEDS_FILE = MAPPINGS_DIR / "output_feeds.json"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_json_files(folder: Path):
    if not folder.exists():
        return

    for path in sorted(folder.glob("*.json"), key=lambda p: p.name.casefold()):
        yield path


def _load_output_feeds() -> dict:
    if not OUTPUT_FEEDS_FILE.exists():
        return {}

    data = _read_json(OUTPUT_FEEDS_FILE)
    return data if isinstance(data, dict) else {}


def _load_hosting_site_data() -> dict:
    hosts: dict[str, dict] = {}

    for path in _iter_json_files(HOSTS_DIR):
        host_cfg = _read_json(path)
        host_name = str(host_cfg.pop("name", "") or host_cfg.pop("host", "")).strip()

        if not host_name:
            raise RuntimeError(f"Missing host name in {path}")

        host_cfg.setdefault("novels", {})
        hosts[host_name] = host_cfg

    output_feeds = _load_output_feeds()

    for path in _iter_json_files(NOVELS_DIR):
        novel = _read_json(path)
        host_name = str(novel.pop("host", "") or "").strip()
        title = str(novel.pop("title", "") or "").strip()

        if not host_name or not title:
            raise RuntimeError(f"Novel JSON must include host and title: {path}")

        if host_name not in hosts:
            raise RuntimeError(f"Unknown host {host_name!r} in {path}")

        feeds = output_feeds.get(host_name, {})

        if novel.get("has_free", False) and feeds.get("free_feed"):
            novel["free_feed"] = feeds["free_feed"]
        else:
            novel.pop("free_feed", None)

        if novel.get("has_paid", False) and feeds.get("paid_feed"):
            novel["paid_feed"] = feeds["paid_feed"]
        else:
            novel.pop("paid_feed", None)

        # Default true for compatibility with your current all-novels comments feed.
        # Add "has_comments": false later only if a novel should opt out.
        if novel.get("has_comments", True) and feeds.get("comments_feed"):
            novel["comments_feed"] = feeds["comments_feed"]
        else:
            novel.pop("comments_feed", None)

        novel.setdefault("has_free", False)
        novel.setdefault("has_paid", False)
        novel.setdefault("is_nsfw", False)
        novel.setdefault("is_membership", False)

        hosts[host_name]["novels"][title] = novel

    return hosts


HOSTING_SITE_DATA = _load_hosting_site_data()


# ---------------- Utility Functions ----------------

def get_host_translator(host):
    """Returns the translator name for the given hosting site."""
    return HOSTING_SITE_DATA.get(host, {}).get("translator", "")


def get_host_logo(host):
    """Returns the hosting site's logo URL for the given host."""
    return HOSTING_SITE_DATA.get(host, {}).get("host_logo", "")


def get_novel_details(host, novel_title):
    """Returns the details of a novel from the specified hosting site."""
    return HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(novel_title, {})


def get_novel_short_code(novel_title, host):
    """
    Returns the stable short code for the given novel.
    This is used by RSS feeds so downstream Discord repos can map
    short_code -> server-specific role IDs.
    """
    details = get_novel_details(host, novel_title)
    return (details.get("short_code", "") or "").strip().upper()


def get_novel_url(novel_title, host):
    """Returns the URL for the given novel on the specified hosting site."""
    details = get_novel_details(host, novel_title)
    return details.get("novel_url", "")


def get_featured_image(novel_title, host):
    """Returns the featured image URL for the given novel on the specified hosting site."""
    details = get_novel_details(host, novel_title)
    return details.get("featured_image", "")


def get_coin_emoji(host):
    """Emoji string used in <coin> for paid feed."""
    return HOSTING_SITE_DATA.get(host, {}).get("coin_emoji", "")


def get_novelupdates_url(novel: dict) -> str:
    """
    Returns the clean NovelUpdates series URL from novel["novelupdates_url"].
    """
    url = str(novel.get("novelupdates_url") or "").strip()
    return url.rstrip("/") if url else ""


def get_novelupdates_feed_url(novel: dict) -> str:
    """
    Returns the NovelUpdates RSS feed URL from novel["novelupdates_url"].
    """
    url = get_novelupdates_url(novel)
    return f"{url}/feed/" if url else ""


def get_nsfw_novels():
    """Returns the list of NSFW novel titles based on novel JSON flags."""
    return [
        title
        for host_data in HOSTING_SITE_DATA.values()
        for title, novel in host_data.get("novels", {}).items()
        if novel.get("is_nsfw", False)
    ]


def get_membership_novels():
    """Returns the list of membership novel titles based on novel JSON flags."""
    return [
        title
        for host_data in HOSTING_SITE_DATA.values()
        for title, novel in host_data.get("novels", {}).items()
        if novel.get("is_membership", False)
    ]


def find_novel_by_short_code(short_code: str):
    """
    Returns (host, host_data, title, novel) for a short code.
    Returns (None, None, None, None) if no match is found.
    """
    target = (short_code or "").strip().upper()

    for host, host_data in HOSTING_SITE_DATA.items():
        for title, novel in host_data.get("novels", {}).items():
            code = (novel.get("short_code", "") or "").strip().upper()
            if code == target:
                return host, host_data, title, novel

    return None, None, None, None

def novel_has_free_chapters(host, novel_title):
    """
    Returns True if this novel should be treated as having free/public chapters.
    Prefer this helper over checking has_free directly in downstream repos.
    """
    details = get_novel_details(host, novel_title)

    if "has_free" in details:
        return bool(details.get("has_free"))

    # Backward compatibility for older mappings
    return bool(details.get("free_feed"))


def novel_has_paid_chapters(host, novel_title):
    """
    Returns True if this novel should be treated as having paid/member chapters.
    Prefer this helper over checking has_paid directly in downstream repos.
    """
    details = get_novel_details(host, novel_title)

    if "has_paid" in details:
        return bool(details.get("has_paid"))

    # Backward compatibility for older mappings
    return bool(details.get("paid_feed"))


def novel_has_comments_feed(host, novel_title):
    """
    Returns True if this novel should be included in comments feed logic.
    Defaults to True unless explicitly disabled with has_comments: false.
    """
    details = get_novel_details(host, novel_title)

    if "has_comments" in details:
        return bool(details.get("has_comments"))

    return bool(details.get("comments_feed"))

def get_novel_details_by_short_code(short_code):
    """
    Returns (host, title, details) for a short_code.
    If not found, returns ("", "", {}).
    """
    short_code = (short_code or "").strip().upper()

    for host, host_data in HOSTING_SITE_DATA.items():
        for title, details in host_data.get("novels", {}).items():
            if (details.get("short_code", "") or "").strip().upper() == short_code:
                return host, title, details

    return "", "", {}


def short_code_has_free_chapters(short_code):
    host, title, details = get_novel_details_by_short_code(short_code)

    if not details:
        return False

    if "has_free" in details:
        return bool(details.get("has_free"))

    return bool(details.get("free_feed"))


def short_code_has_paid_chapters(short_code):
    host, title, details = get_novel_details_by_short_code(short_code)

    if not details:
        return False

    if "has_paid" in details:
        return bool(details.get("has_paid"))

    return bool(details.get("paid_feed"))
