"""
host_utils.py ― Dragonholic helpers (free + paid)

Only the Dragonholic section is implemented; other hosts can be added
later by creating a similar XYZ_UTILS dict and branching in
get_host_utils().
"""

import re
import datetime
from urllib.parse import urlparse, unquote

import aiohttp
from bs4 import BeautifulSoup
import feedparser

from novel_mappings import HOSTING_SITE_DATA


# ----------------------------------------------------------------------
# 1) ─── FREE‑FEED SPLITTER  (unchanged – do NOT modify) ───────────────
# ----------------------------------------------------------------------
def split_title_dragonholic(full_title: str):
    """
    For the free/public feed.
    "Main Title - Chapter Name - (Optional)"  → (main, chapter, extension)
    """
    parts = full_title.split(" - ")
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip(), ""
    if len(parts) >= 3:
        # Join the remaining parts, ignoring empty and literal hyphens
        clean_parts = [p.strip() for p in parts[2:] if p.strip() and p.strip() != "-"]
        return parts[0].strip(), parts[1].strip(), " ".join(clean_parts)
    return full_title.strip(), "", ""


# ----------------------------------------------------------------------
# 2) ─── PAID‑FEED TITLE SPLITTER  (removes <i> lock icon) ─────────────
# ----------------------------------------------------------------------
def split_paid_chapter_dragonholic(raw_title: str):
    cleaned = re.sub(r"<i[^>]*>.*?</i>", "", raw_title).strip()
    parts = cleaned.split(" - ", 1)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (cleaned, "")


# ----------------------------------------------------------------------
# 3) ─── GENERIC HELPERS ───────────────────────────────────────────────
# ----------------------------------------------------------------------
def clean_description(raw_desc: str) -> str:
    soup = BeautifulSoup(raw_desc, "html.parser")
    for div in soup.select("div.c-content-readmore"):
        div.decompose()
    return re.sub(r"\s+", " ", soup.decode_contents()).strip()


def extract_pubdate_from_soup(li) -> datetime.datetime:
    span = li.select_one("span.chapter-release-date i")
    if not span:
        return datetime.datetime.now(datetime.timezone.utc)

    datestr = span.get_text(strip=True)
    try:  # absolute date e.g.  April 19, 2025
        return datetime.datetime.strptime(datestr, "%B %d, %Y").replace(
            tzinfo=datetime.timezone.utc
        )
    except Exception:
        # relative (e.g. “3 hours ago”) – fall back to “now”
        return datetime.datetime.now(datetime.timezone.utc)

def format_volume_from_url(url: str, main_title: str) -> str:
    parsed = urlparse(url)
    segments = [seg for seg in parsed.path.split("/") if seg]
    try:
        slug = main_title.replace(" ", "-").lower()
        idx = segments.index(slug)
        post_slug = segments[idx + 1:]
        if len(post_slug) >= 2:
            raw_volume = unquote(post_slug[0]).strip("/")

            # Keep original for fallback
            original = raw_volume

            # Normalize separators
            raw = raw_volume.replace("_", "-").strip("-")
            parts = raw.split("-")
            if not parts:
                return original

            # Keywords that should trigger colon logic
            colon_keywords = {"volume", "chapter", "vol", "chap", "arc", "world", "plane", "story", "v"}

            lead = parts[0].lower()
            if lead in colon_keywords and len(parts) >= 2 and parts[1].isdigit():
                number = parts[1]
                rest = parts[2:]
                label = lead.capitalize() if lead != "v" else "V" + number
                if lead == "v":
                    # special V3 case (already handled above)
                    return f"{label}: {' '.join(p.capitalize() for p in rest)}" if rest else label
                else:
                    title = " ".join(p.capitalize() for p in rest)
                    return f"{label} {number}: {title}" if rest else f"{label} {number}"

            # If lead is a number (e.g. 3-the-dawn)
            if lead.isdigit() and len(parts) > 1:
                title = " ".join(p.capitalize() for p in parts[1:])
                return f"{lead}: {title}"

            # Otherwise just title-case everything, preserve special characters
            return " ".join(p.capitalize() if p.isascii() else p for p in parts)
    except Exception:
        pass
    return ""

async def fetch_page(session: aiohttp.ClientSession, url: str) -> str:
    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                print(f"⚠️  {url} returned HTTP {resp.status}")
                return ""
            return await resp.text()
    except Exception as e:
        print(f"⚠️  Network error fetching {url}: {e}")
        return ""

def slug(text: str) -> str:
    s = text.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    return s

# ----------------------------------------------------------------------
# 4) ─── QUICK “HAS PREMIUM UPDATE?” CHECK ─────────────────────────────
# ----------------------------------------------------------------------
async def novel_has_paid_update_async(session, novel_url: str) -> bool:
    html = await fetch_page(session, novel_url)
    if not html:
        return False

    li = BeautifulSoup(html, "html.parser").find("li", class_="wp-manga-chapter")
    if not li or "premium" not in li.get("class", []) or "free-chap" in li.get("class", []):
        return False

    pub = extract_pubdate_from_soup(li)
    return pub >= datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)


# ----------------------------------------------------------------------
# 5) ─── VOLUME‑AWARE PAID‑CHAPTER SCRAPER  ────────────────────────────
# ----------------------------------------------------------------------
async def scrape_paid_chapters_async(session, novel_url: str, host: str):
    """
    • If HOSTING_SITE_DATA supplies paid_feed_url – parse that.
    • Else scrape the web page and recognise both
      ul.main.version-chap.volumns  *and*  ul.main.version-chap.no-volumn.
    """
    feed_url = HOSTING_SITE_DATA.get(host, {}).get("paid_feed_url")
    if feed_url:                       # -------- use the external feed
        parsed = feedparser.parse(feed_url)
        paid = []                
        for e in parsed.entries:
            chap, ext = split_paid_chapter_dragonholic(e.title)
            vol_label = ""
            paid.append({
                "volume":      vol_label,
                "chaptername": chap,
                "nameextend":  ext,
                "link":        e.link,
                "description": e.description,
                "pubDate":     datetime.datetime(*e.published_parsed[:6], tzinfo=datetime.timezone.utc),
                "guid":        e.id or chap,
                "coin":        "",
            })
        return paid, ""                 

# -------------------------------------------------- scrape website
    html = await fetch_page(session, novel_url)
    if not html:
        return [], ""

    soup = BeautifulSoup(html, "html.parser")
    main_desc_div = soup.select_one("div.description-summary")
    main_desc = clean_description(main_desc_div.decode_contents()) if main_desc_div else ""

    paid = []
    now = datetime.datetime.now(datetime.timezone.utc)

    # —— (a) volume blocks (Dragonholic‑public style) -----------------------
    vol_ul = soup.select_one("ul.main.version-chap.volumns")
    if vol_ul:
        for vol_parent in vol_ul.select("li.parent.has-child"):
            vol_label   = vol_parent.select_one("a.has-child").get_text(strip=True)
            vol_display = vol_label

            for chap_li in vol_parent.select("ul.sub-chap-list li.wp-manga-chapter"):
                if "free-chap" in chap_li.get("class", []): continue
                pub = extract_pubdate_from_soup(chap_li)
                if pub < now - datetime.timedelta(days=7): continue

                a = chap_li.find("a")
                raw_html = a.decode_contents()

                # 1) chaptername = everything before the first HTML tag
                m1 = re.match(r'\s*([^<]+)', raw_html)
                chap_name = m1.group(1).strip() if m1 else raw_html.strip()

                # 2) nameextend = whatever follows the first “</i> – ”
                m2 = re.search(r'</i>\s*[-–]\s*(.+)', raw_html)
                nameext = m2.group(1).strip() if m2 else ""

                href = a.get("href", "").strip()
                if href and href != "#":
                    link = href
                else:
                    # slug both the volume **label** and the chapter **text**
                    link = f"{novel_url}{slug(vol_display)}/{slug(chap_name)}/"

                guid = next((c.split("data-chapter-")[1]
                             for c in chap_li.get("class", [])
                             if c.startswith("data-chapter-")),
                            slug(chap_name))
                coin = chap_li.select_one("span.coin")
                coin = coin.get_text(strip=True) if coin else ""

                paid.append({
                    "volume":      vol_display,
                    "chaptername": chap_name,
                    "nameextend":  nameext,
                    "link":        link,
                    "description": main_desc,
                    "pubDate":     pub,
                    "guid":        guid,
                    "coin":        coin
                })

    # —— (b) no‑volume (same pattern) --------------------------------------
    no_vol_ul = soup.select_one("ul.main.version-chap.no-volumn")
    if no_vol_ul:
        for chap_li in no_vol_ul.select("li.wp-manga-chapter"):
            if "free-chap" in chap_li.get("class", []): continue
            pub = extract_pubdate_from_soup(chap_li)
            if pub < now - datetime.timedelta(days=7): continue

            a = chap_li.find("a")
            raw_html = a.decode_contents()

            m1 = re.match(r'\s*([^<]+)', raw_html)
            chap_name = m1.group(1).strip() if m1 else raw_html.strip()
            m2 = re.search(r'</i>\s*[-–]\s*(.+)', raw_html)
            nameext = m2.group(1).strip() if m2 else ""

            href = a.get("href", "").strip()
            if href and href != "#":
                link = href
            else:
                link = f"{novel_url}{slug(chap_name)}/"

            guid = next((c.split("data-chapter-")[1]
                         for c in chap_li.get("class", [])
                         if c.startswith("data-chapter-")),
                        slug(chap_name))
            coin = chap_li.select_one("span.coin")
            coin = coin.get_text(strip=True) if coin else ""

            paid.append({
                "volume":      "",
                "chaptername": chap_name,
                "nameextend":  nameext,
                "link":        link,
                "description": main_desc,
                "pubDate":     pub,
                "guid":        guid,
                "coin":        coin
            })
    return paid,   main_desc


# ----------------------------------------------------------------------
# 6) ─── CHAPTER‑NUMBER TUPLE (for sorting) ────────────────────────────
# ----------------------------------------------------------------------
def chapter_num_dragonholic(chaptername: str):
    nums = re.findall(r"\d+(?:\.\d+)?", chaptername)
    return tuple(float(n) if "." in n else int(n) for n in nums) if nums else (0,)


# ----------------------------------------------------------------------
# 7) ─── COMMENT‑HELPERS (unchanged) ───────────────────────────────────
# ----------------------------------------------------------------------
def split_comment_title_dragonholic(comment_title):
    m = re.search(r"Comment on\s*(.+)\s+by\s+(\S+)\s*$", comment_title, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def extract_chapter_dragonholic(link: str):
    parsed = urlparse(link)
    segs = [s for s in parsed.path.split("/") if s]
    if len(segs) <= 2:
        return "Homepage"
    nice = unquote(segs[-1]).replace("-", " ")
    return " ".join(word.capitalize() for word in nice.split())


# ----------------------------------------------------------------------
# 8) ─── DISPATCH TABLE & ENTRY POINT ──────────────────────────────────
# ----------------------------------------------------------------------
DRAGONHOLIC_UTILS = {
    # Free‑feed stuff
    "split_title": split_title_dragonholic,
    # Paid‑feed stuff
    "split_paid_title": split_paid_chapter_dragonholic,
    "chapter_num": chapter_num_dragonholic,
    "novel_has_paid_update_async": novel_has_paid_update_async,
    "scrape_paid_chapters_async": scrape_paid_chapters_async,
    # Shared helpers
    "clean_description": clean_description,
    "extract_pubdate": extract_pubdate_from_soup,
    "split_comment_title": split_comment_title_dragonholic,
    "extract_chapter": extract_chapter_dragonholic,
    # simple lambdas to re‑expose mapping data
    "get_novel_details": lambda host, title: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(title, {}),
    "get_host_translator": lambda host: HOSTING_SITE_DATA.get(host, {}).get("translator", ""),
    "get_host_logo": lambda host: HOSTING_SITE_DATA.get(host, {}).get("host_logo", ""),
    "get_featured_image": lambda title, host: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(title, {}).get("featured_image", ""),
    "get_novel_discord_role": lambda title, host: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(title, {}).get("discord_role_id", ""),
    "get_comments_feed_url": lambda host: HOSTING_SITE_DATA.get(host, {}).get("comments_feed_url", ""),
    "get_nsfw_novels": lambda: [],  # customise if you have NSFW titles
}


# This is what paid_feed_generator.py calls.
def get_host_utils(host: str):
    if host == "Dragonholic":
        return DRAGONHOLIC_UTILS
    # add other hosts here
    return {}
