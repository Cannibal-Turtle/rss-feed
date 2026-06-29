# host_utils/mistmint_haven/__init__.py
from novel_mappings import HOSTING_SITE_DATA

from .common import (
    _use_api_feed,
    split_title_mistmint,
    extract_volume_mistmint,
    format_volume_from_url,
    chapter_num,
    pick_comment_html_default,
)
from .client import resolve_chapters_api_url
from .free_chapters import scrape_free_chapters_mistmint_async
from .paid_chapters import (
    scrape_paid_chapters_mistmint_async,
    split_paid_chapter_mistmint,
)
from .comments import (
    build_comment_link_mistmint,
    extract_chapter_mistmint,
    _mistmint_reply_flags_from_raw,
    load_comments_mistmint,
)

MISTMINT_UTILS = {
    # Free/public feed
    "split_title": split_title_mistmint,
    "extract_volume": extract_volume_mistmint,
    "scrape_free_chapters_async": scrape_free_chapters_mistmint_async if _use_api_feed() else None,
    "resolve_chapters_api_url": resolve_chapters_api_url,

    # Paid feed (synthetic)
    "split_paid_title": split_paid_chapter_mistmint,
    "format_volume_from_url": format_volume_from_url,
    "chapter_num": chapter_num,
    "scrape_paid_chapters_async": scrape_paid_chapters_mistmint_async,

    # Comments/etc.
    "build_comment_link": build_comment_link_mistmint,
    "extract_chapter": extract_chapter_mistmint,
    "reply_flags_from_raw": _mistmint_reply_flags_from_raw,
    "load_comments": load_comments_mistmint,
    "pick_comment_html": pick_comment_html_default,

    # passthroughs to novel_mappings
    "get_novel_details":
        lambda host, title: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(title, {}),
    "get_host_logo":
        lambda host: HOSTING_SITE_DATA.get(host, {}).get("host_logo", ""),
    "get_featured_image":
        lambda host, title: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(title, {}).get("featured_image", ""),
    "get_novel_short_code":
        lambda host, title: (HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(title, {}).get("short_code", "") or "").strip().upper(),
    "get_comments_api_url":
        lambda host: HOSTING_SITE_DATA.get(host, {}).get("comments_api_url", ""),
    "get_nsfw_novels":
        lambda: [],
}

__all__ = ["MISTMINT_UTILS"]
