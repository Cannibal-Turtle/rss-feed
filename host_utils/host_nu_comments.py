# -*- coding: utf-8 -*-
"""
Post-merge Novel Updates appender for aggregated_comments_feed.xml

Usage (CI step after comments.py):
  python -m host_utils.host_nu_comments --merge aggregated_comments_feed.xml

Behavior:
- Read existing aggregated XML as raw text
- Extract existing <item>...</item> blocks verbatim
- Fetch NU comment items from mappings (novelupdates_feed_url)
- Build NU items as raw <item> blocks (role mention normalized)
- De-duplicate by GUID
- Sort ALL blocks by <pubDate> DESC
- Write header + sorted blocks + footer (existing blocks unchanged byte-for-byte)
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import re
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List

import feedparser
from xml.sax.saxutils import escape as _xesc, quoteattr as _xqa

from novel_mappings import HOSTING_SITE_DATA
try:
    from novel_mappings import get_nsfw_novels  # optional
except Exception:
    def get_nsfw_novels() -> List[str]:
        return []

# ---------------------------- constants --------------------------------

NU_HOST_NAME  = "Novel Updates"
NU_HOST_LOGO  = "https://www.novelupdates.com/appicon.png"

# XML 1.0 legal char filter: tab, LF, CR, U+0020–U+D7FF, U+E000–U+FFFD, U+10000–U+10FFFF
_XML10_BAD = re.compile(r"[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]")

_ITEM_RE = re.compile(r"(<item>.*?</item>)", re.DOTALL | re.IGNORECASE)
_PUB_RE  = re.compile(r"<pubDate>(.*?)</pubDate>", re.IGNORECASE | re.DOTALL)
_GUID_RE = re.compile(r"<guid[^>]*>(.*?)</guid>", re.IGNORECASE | re.DOTALL)

# accepts 123 or <@&123>
_ROLE_RE = re.compile(r"^\s*(?:<@&)?(\d+)>?\s*$", re.ASCII)

# ---------------------------- helpers ----------------------------------

def _xml10(s: str) -> str:
    return _XML10_BAD.sub("", s or "")

def _guid_from(parts) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p).encode("utf-8", "ignore"))
        h.update(b"\x1f")
    return h.hexdigest()

def _parse_pubdate_rfc2822(s: str) -> dt.datetime:
    try:
        d = parsedate_to_datetime(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        else:
            d = d.astimezone(dt.timezone.utc)
        return d
    except Exception:
        return dt.datetime.now(dt.timezone.utc)

def _to_rfc2822(t: dt.datetime) -> str:
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    else:
        t = t.astimezone(dt.timezone.utc)
    return t.strftime("%a, %d %b %Y %H:%M:%S +0000")

def _cdata(s: str) -> str:
    """Safe CDATA wrapper that splits any ']]>'."""
    s = s or ""
    s = s.replace("]]>", "]]]]><![CDATA[>")
    return "<![CDATA[" + s + "]]>"

def _strip_by_prefix(s: str) -> str:
    """NU often has 'By: username' in title; strip if present."""
    m = re.match(r"^\s*by:\s*(.+)$", (s or "").strip(), re.I)
    return m.group(1).strip() if m else (s or "").strip()

def _role_mention(val: str) -> str:
    """
    Accept '12345' or '<@&12345>' (with or without whitespace / CDATA).
    Return '<@&12345>' or ''.
    """
    if not val:
        return ""
    # unescape & strip CDATA if fed from XML
    v = html.unescape(val).strip()
    v = re.sub(r"^\s*<!\[CDATA\[|\]\]>\s*$", "", v).strip()
    m = _ROLE_RE.match(v)
    return f"<@&{m.group(1)}>" if m else ""

def _parse_existing_aggregated(xml_text: str) -> List[str]:
    """Return list of raw <item>...</item> blocks verbatim."""
    return _ITEM_RE.findall(xml_text)

def _split_header_items_footer(xml_text: str):
    """Return (header, [item blocks], footer) without altering bytes."""
    items = _parse_existing_aggregated(xml_text)
    if not items:
        # Try to split around </channel> so footer carries closing tags
        m = re.search(r"(.*?<channel>)(.*)(</channel>.*)", xml_text, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1), [], m.group(3)
        return xml_text, [], ""  # extreme fallback
    first = xml_text.find(items[0])
    last  = xml_text.rfind(items[-1]) + len(items[-1])
    header = xml_text[:first]
    footer = xml_text[last:]
    return header, items, footer

def _block_pubdate(block: str) -> dt.datetime:
    m = _PUB_RE.search(block)
    return _parse_pubdate_rfc2822(m.group(1).strip()) if m else dt.datetime.now(dt.timezone.utc)

def _block_guid(block: str) -> str:
    m = _GUID_RE.search(block)
    return (m.group(1).strip() if m else "") or ""

# -------------------- NU collection and item building -------------------

def _collect_nu_items_from_mappings() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for host, cfg in (HOSTING_SITE_DATA or {}).items():
        novels = (cfg.get("novels") or {})
        translator = cfg.get("translator", "")
        for novel_title, nd in novels.items():
            nu_url = (nd.get("novelupdates_feed_url") or "").strip()
            if not nu_url:
                continue
            parsed = feedparser.parse(nu_url)
            for e in getattr(parsed, "entries", []) or []:
                author = _strip_by_prefix(
                    e.get("title", "") or e.get("author", "") or ""
                )
                desc   = html.unescape(e.get("description", "") or "")
                # prefer published_parsed/updated_parsed; fallback now
                pp = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
                pub_dt = (dt.datetime(*pp[:6], tzinfo=dt.timezone.utc)
                          if pp else dt.datetime.now(dt.timezone.utc))
                guid_v = getattr(e, "id", "") or e.get("guid") or e.get("link") or _guid_from(
                    [novel_title, author, e.get("link", ""), desc[:80]]
                )
                is_perm = bool(getattr(e, "guidislink", False))
                link_v  = e.get("link", "") or ""
                category_value = "NSFW" if novel_title in get_nsfw_novels() else "SFW"

                out.append({
                    "novel_title": novel_title,
                    "host": NU_HOST_NAME,
                    "translator": translator,
                    "discord_role_id": (nd.get("discord_role_id") or ""),
                    "featured_image": (nd.get("featured_image") or ""),
                    "category": category_value,
                    "host_logo": NU_HOST_LOGO,
                    "link": link_v,
                    "author": author,
                    "description": desc,
                    "pubDate": pub_dt,
                    "guid": guid_v,
                    "isPermaLink": is_perm,
                    "chapter": "",  # NU doesn't provide per-chapter label
                })
    return out

def _build_nu_item_block(it: Dict[str, Any]) -> str:
    """Build a single NU <item> block with normalized role mention."""
    title       = _xml10(it.get("novel_title", ""))
    link        = _xml10(it.get("link", ""))
    translator  = _xml10(it.get("translator", ""))
    host        = _xml10(it.get("host", NU_HOST_NAME))
    category    = _xml10(it.get("category", "SFW"))
    guid        = _xml10(it.get("guid", ""))
    is_perm     = "true" if it.get("isPermaLink") else "false"
    pub         = _to_rfc2822(it["pubDate"])
    chapter     = _xml10(it.get("chapter", "") or "")
    featured    = it.get("featured_image") or ""
    host_logo   = it.get("host_logo") or ""
    author      = _xml10(it.get("author", ""))
    desc        = _xml10(it.get("description", ""))

    # role mention normalized to '<@&digits>' or ''
    role_raw   = it.get("discord_role_id", "")
    role_fixed = _role_mention(role_raw)

    lines = []
    lines.append("    <item>")
    lines.append(f"      <title>{_xesc(title)}</title>")
    lines.append(f"      <chapter>{_xesc(chapter)}</chapter>")
    lines.append(f"      <link>{_xesc(link)}</link>")
    lines.append("      <dc:creator>")
    lines.append(f"        {_cdata(author)}")
    lines.append("      </dc:creator>")
    lines.append("      <description>")
    lines.append(f"        {_cdata(desc)}")
    lines.append("      </description>")
    lines.append(f"      <translator>{_xesc(translator)}</translator>")
    lines.append("      <discord_role_id>")
    lines.append(f"        {_cdata(role_fixed)}")
    lines.append("      </discord_role_id>")
    if featured:
        lines.append(f"      <featuredImage url={_xqa(_xml10(str(featured)))}/>")
    lines.append(f"      <host>{_xesc(host)}</host>")
    if host_logo:
        lines.append(f"      <hostLogo url={_xqa(_xml10(str(host_logo)))}/>")
    lines.append(f"      <category>{_xesc(category)}</category>")
    lines.append(f"      <pubDate>{pub}</pubDate>")
    lines.append(f"      <guid isPermaLink=\"{is_perm}\">{_xesc(guid)}</guid>")
    lines.append("    </item>")

    # ensure trailing newline for nice concatenation
    return "\n".join(lines) + "\n"

# ------------------------------- merge ---------------------------------

def merge_into_aggregated(aggregated_path: str) -> None:
    # 1) read existing XML
    with open(aggregated_path, "r", encoding="utf-8") as f:
        original = f.read()

    header, existing_blocks, footer = _split_header_items_footer(original)

    # 2) pull NU items
    nu_items = _collect_nu_items_from_mappings()
    if not nu_items:
        print("[nu-merge] no NU items; skipping rewrite")
        return

    # 3) collect existing GUIDs for de-dup
    existing_guids = set()
    for blk in existing_blocks:
        mg = _GUID_RE.search(blk)
        if mg:
            existing_guids.add(mg.group(1).strip())

    # 4) create NU blocks to append (only new GUIDs)
    nu_blocks: List[str] = []
    nu_blocks_with_dates: List[tuple[str, dt.datetime]] = []
    for it in nu_items:
        if it["guid"] in existing_guids:
            continue
        blk = _build_nu_item_block(it)
        nu_blocks.append(blk)
        nu_blocks_with_dates.append((blk, it["pubDate"]))

    if not nu_blocks:
        print("[nu-merge] no new NU items; skipping rewrite")
        return

    # 5) prepare sortable list: existing (use their own pubDate inside block) + new NU ones
    sortable: List[tuple[str, dt.datetime]] = [(blk, _block_pubdate(blk)) for blk in existing_blocks]
    sortable.extend(nu_blocks_with_dates)

    # 6) sort by pubDate DESC, concatenate blocks as-is
    sortable.sort(key=lambda t: t[1], reverse=True)
    new_body = "".join(blk if blk.endswith("\n") else blk + "\n" for blk, _ in sortable)

    # 7) write back header + body + footer (header/footer unchanged)
    with open(aggregated_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write(new_body)
        f.write(footer)

    print(f"[nu-merge] appended {len(nu_blocks)} NU items and re-ordered by pubDate (existing items left byte-for-byte)")

# -------------------------------- CLI ----------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--merge", metavar="AGG_XML", help="Path to aggregated_comments_feed.xml")
    args = ap.parse_args()
    if not args.merge:
        ap.print_help()
        return 2
    merge_into_aggregated(args.merge)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
