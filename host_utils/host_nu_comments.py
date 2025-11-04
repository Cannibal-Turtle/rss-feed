# -*- coding: utf-8 -*-
"""
host_utils/host_nu_comments.py

Helpers to collect NovelUpdates *comment* items for novels that define
'novelupdates_feed_url' in HOSTING_SITE_DATA[<host>].novels[*].

These are intentionally shaped to match comments.py's loader expectations
so you can simply `items.extend(collect_nu_items_for_host("Dragonholic"))`
inside your existing host loader without changing comments.py.

Returned dict keys per item:
  - novel_title     (str)  : from mappings' novel key
  - chapter         (str)  : ""   (force empty chapter as requested)
  - author          (str)  : parsed from NU item title "By: name" (case-insensitive)
  - description     (str)  : NU description (HTML already unescaped)
  - posted_at       (str)  : ISO8601 UTC (Z) time string
  - reply_to        (str)  : ""   (NU has no reply chains)
  - guid            (str)  : NU id/guid/link or fallback SHA1
  - link            (str)  : NU item link (left as-is)

Optional helpers:
  - is_nu_link(url)                 -> bool
  - extract_chapter_for_nu(url)     -> "" (so your host's extract_chapter can short-circuit)
  - passthrough_comment_link_for_nu(novel_title, host, link) -> link unchanged for NU
"""

from __future__ import annotations
import re
import html
import hashlib
import datetime as dt
from typing import List, Dict, Any

import feedparser
from novel_mappings import HOSTING_SITE_DATA

# ──────────────────────────────────────────────────────────────────────────────
def _guid_from(parts) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p).encode("utf-8", "ignore"))
        h.update(b"\x1f")
    return h.hexdigest()

def _strip_by_prefix(s: str) -> str:
    """Strip leading 'By: ' (any case) from creator/title field."""
    m = re.match(r'^\s*by:\s*(.+)$', (s or "").strip(), re.I)
    return m.group(1).strip() if m else (s or "").strip()

def _parse_pubdate(entry) -> dt.datetime:
    pp = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if pp:
        return dt.datetime(*pp[:6], tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)

def _to_iso_utc_z(t: dt.datetime) -> str:
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    else:
        t = t.astimezone(dt.timezone.utc)
    return t.isoformat().replace("+00:00", "Z")

# ───────────────── helpers you can call from your host modules ───────────────
def collect_nu_items_for_host(host_name: str) -> List[Dict[str, Any]]:
    """
    Look up HOSTING_SITE_DATA[host_name].novels[*].novelupdates_feed_url
    and return normalized comment items for comments.py's loader path.
    """
    out: List[Dict[str, Any]] = []
    host_cfg = (HOSTING_SITE_DATA.get(host_name) or {})
    novels = (host_cfg.get("novels") or {})

    for novel_title, nd in novels.items():
        nu_url = (nd.get("novelupdates_feed_url") or "").strip()
        if not nu_url:
            continue

        parsed = feedparser.parse(nu_url)
        for e in getattr(parsed, "entries", []) or []:
            author = _strip_by_prefix(e.get("title", "") or e.get("author", "") or "")
            desc = html.unescape(e.get("description", "") or "")
            pub_dt = _parse_pubdate(e)

            guid_val = getattr(e, "id", "") or e.get("guid") or e.get("link") or _guid_from(
                [novel_title, author, e.get("link", ""), desc[:80]]
            )
            link_val = e.get("link", "") or ""

            out.append({
                "novel_title": novel_title,
                "chapter": "",                         # force empty <chapter>
                "author": author,                      # parsed username
                "description": desc,                   # NU description
                "posted_at": _to_iso_utc_z(pub_dt),    # ISO UTC Z
                "reply_to": "",                        # NU has no reply chains
                "guid": guid_val,                      # from feed or fallback
                "link": link_val,                      # NU link as-is
            })
    return out

def is_nu_link(url: str) -> bool:
    return isinstance(url, str) and "novelupdates.com" in url.lower()

def extract_chapter_for_nu(url: str) -> str:
    """
    Return empty string for NU so comments.py emits <chapter></chapter>
    via your host's extract_chapter short-circuit.
    Use from your host's extract_chapter like:

        if is_nu_link(link): return extract_chapter_for_nu(link)
    """
    return ""

def passthrough_comment_link_for_nu(novel_title: str, host: str, link: str) -> str:
    """
    Return NU links unchanged so your host-specific build_comment_link()
    can early-return for NU:

        if is_nu_link(link): return passthrough_comment_link_for_nu(nt, host, link)
    """
    return link
