# -*- coding: utf-8 -*-
"""
Post-merge-only NU appender for aggregated_comments_feed.xml

Usage (in CI after comments.py):
  python -m host_utils.host_nu_comments --merge aggregated_comments_feed.xml

What it does:
- Scans HOSTING_SITE_DATA[*].novels[*].novelupdates_feed_url
- Fetches NU items via feedparser
- Builds items with your exact mapping rules and appends to existing XML
- De-dups by GUID, sorts by pubDate desc, preserves your RSS shape
"""

from __future__ import annotations
import re
import html
import argparse
import hashlib
import datetime as dt
from typing import List, Dict, Any
import feedparser
import xml.dom.minidom
from xml.sax.saxutils import escape as _xesc, quoteattr as _xqa

from novel_mappings import HOSTING_SITE_DATA
try:
    from novel_mappings import get_nsfw_novels  # if defined
except Exception:
    def get_nsfw_novels() -> List[str]:
        return []

NU_HOST_NAME  = "Novel Updates"
NU_HOST_LOGO  = "https://www.novelupdates.com/appicon.png"

XMLDECL = '<?xml version="1.0" encoding="utf-8"?>'
RSS_OPEN = (
    '<rss xmlns:content="http://purl.org/rss/1.0/modules/content/" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:atom="http://www.w3.org/2005/Atom" '
    'xmlns:sy="http://purl.org/rss/1.0/modules/syndication/" '
    'xmlns:georss="http://www.georss.org/georss" '
    'xmlns:geo="http://www.w3.org/2003/01/geo/wgs84_pos#" '
    'version="2.0">'
)

def _guid_from(parts) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p).encode("utf-8", "ignore"))
        h.update(b"\x1f")
    return h.hexdigest()

def _to_rfc2822(t: dt.datetime) -> str:
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    else:
        t = t.astimezone(dt.timezone.utc)
    return t.strftime("%a, %d %b %Y %H:%M:%S +0000")

def _parse_pubdate(entry) -> dt.datetime:
    pp = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if pp:
        return dt.datetime(*pp[:6], tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)

def _strip_by_prefix(s: str) -> str:
    m = re.match(r'^\s*by:\s*(.+)$', (s or "").strip(), re.I)
    return m.group(1).strip() if m else (s or "").strip()

def _compact_cdata(xml_str: str) -> str:
    # Compact <description><![CDATA[ ... ]]></description>
    pat = re.compile(r'(<description><!\[CDATA\[)(.*?)(\]\]></description>)', re.DOTALL)
    def repl(m):
        start, body, end = m.groups()
        return f"{start}{re.sub(r'\\s+', ' ', body.strip())}{end}"
    return pat.sub(repl, xml_str)

# ---------- read & lightly-parse your existing aggregated XML ----------
def _parse_existing_aggregated(xml_text: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for block in re.findall(r"<item>(.*?)</item>", xml_text, flags=re.DOTALL|re.IGNORECASE):
        def _get(tag, default=""):
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.DOTALL|re.IGNORECASE)
            return m.group(1).strip() if m else default
        def _geta(tag, attr):
            m = re.search(rf"<{tag}\s+[^>]*{attr}=\"([^\"]+)\"[^>]*/?>", block, re.DOTALL|re.IGNORECASE)
            return m.group(1) if m else ""

        title      = _get("title")
        link       = _get("link")
        creator    = _get("dc:creator") or _get("creator")
        desc       = _get("description")
        host       = _get("host")
        host_logo  = _geta("hostLogo", "url")
        featured   = _geta("featuredImage", "url")
        category   = _get("category") or "SFW"
        pub_s      = _get("pubDate")
        try:
            pub_dt = dt.datetime.strptime(pub_s, "%a, %d %b %Y %H:%M:%S +0000").replace(tzinfo=dt.timezone.utc)
        except Exception:
            pub_dt = dt.datetime.now(dt.timezone.utc)
        g = re.search(r'<guid\s+isPermaLink="([^"]+)">(.*?)</guid>', block, re.DOTALL|re.IGNORECASE)
        is_perma = (g.group(1).lower() == "true") if g else False
        guid     = g.group(2).strip() if g else _guid_from([title, creator, link, desc[:80]])
        translator   = _get("translator")
        discord_role = _get("discord_role_id")
        chapter      = _get("chapter")  # keep if present

        # strip CDATA if any
        creator = re.sub(r"^\s*<!\[CDATA\[|\]\]>\s*$", "", creator)
        desc    = re.sub(r"^\s*<!\[CDATA\[|\]\]>\s*$", "", desc)

        items.append({
            "novel_title": title,
            "host": host,
            "translator": translator,
            "discord_role_id": discord_role,
            "featured_image": featured,
            "category": category,
            "host_logo": host_logo,
            "link": link,
            "author": creator,
            "description": desc,
            "pubDate": pub_dt,
            "guid": guid,
            "isPermaLink": is_perma,
            "chapter": chapter,
        })
    return items

# ---------- collect NU items from mappings ----------
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
                author = _strip_by_prefix(e.get("title", "") or e.get("author", "") or "")
                desc   = html.unescape(e.get("description", "") or "")
                pub_dt = _parse_pubdate(e)
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
                    "chapter": "",  # force empty
                })
    return out

# ---------- emit full aggregated feed (same shape, escaped safely) ----------
def _safe_cdata(s: str) -> str:
    # prevent ']]>' from breaking CDATA
    return (s or "").replace("]]>", "]]&gt;")

def _emit_aggregated(path: str, items: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(XMLDECL + "\n")
        f.write(RSS_OPEN + "\n")
        f.write("  <channel>\n")
        f.write("    <title>Aggregated Comments Feed</title>\n")
        f.write("    <link>https://github.com/Cannibal-Turtle</link>\n")
        f.write("    <description>Aggregated RSS feed for comments across hosting sites.</description>\n")
        f.write(f"    <lastBuildDate>{_to_rfc2822(dt.datetime.now(dt.timezone.utc))}</lastBuildDate>\n")

        for it in items:
            title_txt   = _xesc(it.get('novel_title', ''))
            link_txt    = _xesc(it.get('link', ''))
            trans_txt   = _xesc(it.get('translator', ''))
            host_txt    = _xesc(it.get('host', ''))
            cat_txt     = _xesc(it.get('category', 'SFW'))
            guid_txt    = _xesc(it.get('guid', ''))
            chapter_txt = _xesc(it.get('chapter', '') or '')

            creator_cdata = f"<![CDATA[ {_safe_cdata(it.get('author',''))} ]]>"
            desc_cdata    = f"<![CDATA[ {_safe_cdata(it.get('description',''))} ]]>"

            f.write("    <item>\n")
            f.write(f"      <title>{title_txt}</title>\n")
            f.write(f"      <chapter>{chapter_txt}</chapter>\n")
            f.write(f"      <link>{link_txt}</link>\n")
            f.write("      <dc:creator>\n")
            f.write(f"        {creator_cdata}\n")
            f.write("      </dc:creator>\n")
            f.write("      <description>\n")
            f.write(f"        {desc_cdata}\n")
            f.write("      </description>\n")
            f.write(f"      <translator>{trans_txt}</translator>\n")
            f.write("      <discord_role_id>\n")
            f.write(f"        <![CDATA[ {it.get('discord_role_id','')} ]]>\n")
            f.write("      </discord_role_id>\n")

            feat = it.get("featured_image")
            if feat:
                f.write(f"      <featuredImage url={_xqa(str(feat))}/>\n")

            f.write(f"      <host>{host_txt}</host>\n")
            host_logo = it.get("host_logo")
            if host_logo:
                f.write(f"      <hostLogo url={_xqa(str(host_logo))}/>\n")

            f.write(f"      <category>{cat_txt}</category>\n")
            f.write(f"      <pubDate>{_to_rfc2822(it['pubDate'])}</pubDate>\n")
            is_perm = str(bool(it.get("isPermaLink"))).lower()
            f.write(f"      <guid isPermaLink=\"{is_perm}\">{guid_txt}</guid>\n")
            f.write("    </item>\n")

        f.write("  </channel>\n")
        f.write("</rss>\n")

    # pretty-print + compact CDATA (unchanged)
    with open(path, "r", encoding="utf-8") as rf:
        xml_text = rf.read()
    xml_text = "\n".join(
        [line for line in xml.dom.minidom.parseString(xml_text).toprettyxml(indent="  ").splitlines() if line.strip()]
    )
    xml_text = _compact_cdata(xml_text)
    with open(path, "w", encoding="utf-8") as wf:
        wf.write(xml_text)

def merge_into_aggregated(aggregated_path: str) -> None:
    with open(aggregated_path, "r", encoding="utf-8") as f:
        existing = f.read()

    base_items = _parse_existing_aggregated(existing)
    nu_items   = _collect_nu_items_from_mappings()

    seen = {it["guid"] for it in base_items}
    merged = list(base_items)
    for it in nu_items:
        if it["guid"] not in seen:
            merged.append(it)
            seen.add(it["guid"])

    merged.sort(key=lambda x: x["pubDate"], reverse=True)
    _emit_aggregated(aggregated_path, merged)
    print(f"[nu-merge] appended {len(nu_items)} NU items → {aggregated_path} (total {len(merged)})")

# ---------- CLI ----------
def main() -> int:
    import argparse
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
