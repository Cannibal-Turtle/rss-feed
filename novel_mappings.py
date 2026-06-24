"""
novel_mappings.py

Compatibility loader for novel mapping data.

The actual mapping data now lives in:

mappings/
├─ hosts/
│  └─ *.toml
├─ novels/
│  └─ *.toml
└─ output_feeds.toml

Dependent scripts can still import:

    from novel_mappings import HOSTING_SITE_DATA
"""

from __future__ import annotations

from importlib import resources
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


MAPPINGS_PACKAGE = "mappings"


def _read_toml_text(text: str) -> dict[str, Any]:
    return tomllib.loads(text)


def _read_toml_resource(*parts: str) -> dict[str, Any]:
    path = resources.files(MAPPINGS_PACKAGE).joinpath(*parts)
    return _read_toml_text(path.read_text(encoding="utf-8"))


def _iter_toml_resources(folder: str):
    base = resources.files(MAPPINGS_PACKAGE).joinpath(folder)

    for item in sorted(base.iterdir(), key=lambda p: p.name.casefold()):
        if item.name.endswith(".toml"):
            yield item


def _read_resource_toml(item) -> dict[str, Any]:
    return _read_toml_text(item.read_text(encoding="utf-8"))


def _load_output_feeds() -> dict[str, Any]:
    try:
        data = _read_toml_resource("output_feeds.toml")
    except FileNotFoundError:
        return {}

    return data if isinstance(data, dict) else {}


def _load_hosting_site_data() -> dict[str, dict[str, Any]]:
    hosts: dict[str, dict[str, Any]] = {}

    for item in _iter_toml_resources("hosts"):
        host_cfg = _read_resource_toml(item)
        host_name = str(
            host_cfg.pop("name", "") or host_cfg.pop("host", "") or ""
        ).strip()

        if not host_name:
            raise RuntimeError(f"Missing host name in {item.name}")

        host_cfg.setdefault("novels", {})
        hosts[host_name] = host_cfg

    output_feeds = _load_output_feeds()

    for item in _iter_toml_resources("novels"):
        novel = _read_resource_toml(item)

        host_name = str(novel.pop("host", "") or "").strip()
        title = str(novel.pop("title", "") or "").strip()

        if not host_name or not title:
            raise RuntimeError(f"Novel TOML must include host and title: {item.name}")

        if host_name not in hosts:
            raise RuntimeError(f"Unknown host {host_name!r} in {item.name}")

        # output_feeds.toml is repo-level/global, not host-specific.
        feeds = output_feeds

        if novel.get("has_free", False) and feeds.get("free_feed"):
            novel["free_feed"] = feeds["free_feed"]
        else:
            novel.pop("free_feed", None)

        if novel.get("has_paid", False) and feeds.get("paid_feed"):
            novel["paid_feed"] = feeds["paid_feed"]
        else:
            novel.pop("paid_feed", None)

        if novel.get("has_comments", True) and feeds.get("comments_feed"):
            novel["comments_feed"] = feeds["comments_feed"]
        else:
            novel.pop("comments_feed", None)

        novel.setdefault("is_nsfw", False)
        novel.setdefault("is_membership", False)

        hosts[host_name]["novels"][title] = novel

    return hosts


HOSTING_SITE_DATA = _load_hosting_site_data()


# ---------------- Utility Functions ----------------

def get_mapping_value(host, novel_title="", key="", default=""):
    """
    Generic novel → host fallback.
    Novel-level value wins. Host-level value is fallback.
    """
    host_data = HOSTING_SITE_DATA.get(host, {})
    novel = host_data.get("novels", {}).get(novel_title, {}) if novel_title else {}

    value = novel.get(key) or host_data.get(key) or default
    return value.strip() if isinstance(value, str) else value


def get_translator(host, novel_title=""):
    return get_mapping_value(host, novel_title, "translator", "")


def get_free_feed_url(host, novel_title=""):
    return get_mapping_value(host, novel_title, "free_feed_url", "")


def get_paid_feed_url(host, novel_title=""):
    return get_mapping_value(host, novel_title, "paid_feed_url", "")


def get_feed_url(host, novel_title=""):
    return get_mapping_value(host, novel_title, "feed_url", "")


def get_chapters_api_url(host, novel_title=""):
    return get_mapping_value(host, novel_title, "chapters_api_url", "")


def get_comments_api_url(host, novel_title=""):
    return get_mapping_value(host, novel_title, "comments_api_url", "")


def get_comments_feed_url(host, novel_title=""):
    return get_mapping_value(host, novel_title, "comments_feed_url", "")


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
    """Returns the list of NSFW novel titles."""
    return [
        title
        for host_data in HOSTING_SITE_DATA.values()
        for title, novel in host_data.get("novels", {}).items()
        if novel.get("is_nsfw", False)
    ]


def get_membership_novels():
    """Returns the list of membership novel titles."""
    return [
        title
        for host_data in HOSTING_SITE_DATA.values()
        for title, novel in host_data.get("novels", {}).items()
        if novel.get("is_membership", False)
    ]


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


def find_novel_by_short_code(short_code):
    """
    Backward-friendly alias.

    Returns (host, host_data, title, details).
    If not found, returns (None, None, None, None).
    """
    short_code = (short_code or "").strip().upper()

    for host, host_data in HOSTING_SITE_DATA.items():
        for title, details in host_data.get("novels", {}).items():
            if (details.get("short_code", "") or "").strip().upper() == short_code:
                return host, host_data, title, details

    return None, None, None, None


def novel_has_free_chapters(host, novel_title):
    """
    Returns True if this novel should be treated as having free/public chapters.
    """
    details = get_novel_details(host, novel_title)

    if "has_free" in details:
        return bool(details.get("has_free"))

    return bool(details.get("free_feed"))


def novel_has_paid_chapters(host, novel_title):
    """
    Returns True if this novel should be treated as having paid/member chapters.
    """
    details = get_novel_details(host, novel_title)

    if "has_paid" in details:
        return bool(details.get("has_paid"))

    return bool(details.get("paid_feed"))


def novel_has_comments_feed(host, novel_title):
    """
    Returns True if this novel should be included in comments feed logic.

    Defaults to True unless explicitly disabled with has_comments = false.
    """
    details = get_novel_details(host, novel_title)

    if "has_comments" in details:
        return bool(details.get("has_comments"))

    return bool(details.get("comments_feed"))


def short_code_has_free_chapters(short_code):
    """Short-code version of novel_has_free_chapters()."""
    host, title, details = get_novel_details_by_short_code(short_code)

    if not details:
        return False

    if "has_free" in details:
        return bool(details.get("has_free"))

    return bool(details.get("free_feed"))


def short_code_has_paid_chapters(short_code):
    """Short-code version of novel_has_paid_chapters()."""
    host, title, details = get_novel_details_by_short_code(short_code)

    if not details:
        return False

    if "has_paid" in details:
        return bool(details.get("has_paid"))

    return bool(details.get("paid_feed"))


def short_code_has_comments_feed(short_code):
    """Short-code version of novel_has_comments_feed()."""
    host, title, details = get_novel_details_by_short_code(short_code)

    if not details:
        return False

    if "has_comments" in details:
        return bool(details.get("has_comments"))

    return bool(details.get("comments_feed"))
