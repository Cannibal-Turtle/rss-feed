import re
import datetime
from urllib.parse import urlparse, unquote

import aiohttp
from bs4 import BeautifulSoup
import feedparser

from novel_mappings import HOSTING_SITE_DATA

APPROVED_COMMENTS_FEED = "https://script.google.com/macros/s/AKfycbxx6YrbuG1WVqc5uRmmQBw3Z8s8k29RS0sgK9ivhbaTUYTp-8t76mzLo0IlL1LlqinY/exec"

# ----------------------------------------------------------------------
# 1) ─── FREE-FEED SPLITTERS ───────────────────────────────────────────
# ----------------------------------------------------------------------
def split_title_dragonholic(full_title: str):
    """
    For the free/public feed.
    "Main Title - Chapter Name - (Optional)" → (main, chapter, extension)
    """
    parts = full_title.split(" - ")
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip(), ""
    if len(parts) >= 3:
        clean_parts = [p.strip() for p in parts[2:] if p.strip() and p.strip() != "-"]
        return parts[0].strip(), parts[1].strip(), " ".join(clean_parts)
    return full_title.strip(), "", ""

def split_title_mistmint(full_title: str):
    """
    Mistmint format examples:
    1) "Miss Priest... — Volume 1: Dream’s Beginning, Chapter 30 — Card Master"
    2) "My Ex-Wife Went Straight To The Crematorium [Rebirth] — Chapter 13 — The Ring"

    Returns (novel_title, chaptername, nameextend)
    so free_feed_generator.py can unpack it.
    """
    parts = [p.strip() for p in full_title.split(" — ")]

    # parts[0] : novel title
    # parts[1] : "Volume 1: X, Chapter NN"  OR "Chapter NN"
    # parts[2] : subtitle ("Card Master", "The Ring", etc.)
    novel_title = parts[0] if len(parts) > 0 else full_title.strip()
    middle      = parts[1] if len(parts) > 1 else ""
    chapter_sub = parts[2] if len(parts) > 2 else ""

    if ", Chapter " in middle:
        # "Volume 1: Dream’s Beginning, Chapter 30"
        before, after = middle.split(", Chapter ", 1)
        chaptername = f"Chapter {after.strip()}"
    else:
        # "Chapter 13"
        chaptername = middle.strip()

    # We don't return volume here because free_feed_generator will ask
    # utils["extract_volume"](title, link) for it per host.
    return novel_title, chaptername, chapter_sub

def extract_volume_dragonholic(full_title: str, link: str) -> str:
    """
    Dragonholic chapters usually don't include volume text in the feed title,
    so we fall back to the URL-based parser you already had.
    """
    return format_volume_from_url(link)


def extract_volume_mistmint(full_title: str, link: str) -> str:
    """
    Mistmint feed titles look like:
    "Miss Priest, ... — Volume 1: Dream’s Beginning, Chapter 30 — Card Master"
    or
    "My Ex-Wife ... — Chapter 13 — The Ring"

    We only want the part before ", Chapter NN" if it exists.
    Example:
      middle = "Volume 1: Dream’s Beginning, Chapter 30"
      => "Volume 1: Dream’s Beginning"
    If there's no volume (just "Chapter 13"), return "".
    """
    # Split on em dash blocks like we did in split_title_mistmint
    parts = [p.strip() for p in full_title.split(" — ")]

    if len(parts) < 2:
        # unexpected format, just give up
        return ""

    middle = parts[1]

    if ", Chapter " in middle:
        before, _after = middle.split(", Chapter ", 1)
        # before = "Volume 1: Dream’s Beginning"
        return before.strip()

    # Example of no volume: middle == "Chapter 13"
    return ""


# ----------------------------------------------------------------------
# 2) ─── PAID-FEED TITLE SPLITTERS ─────────────────────────────────────
# ----------------------------------------------------------------------
def split_paid_chapter_dragonholic(raw_title: str):
    cleaned = re.sub(r"<i[^>]*>.*?</i>", "", raw_title).strip()
    parts = cleaned.split(" - ", 1)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (cleaned, "")

def split_paid_chapter_mistmint(raw_title: str):
    """
    Stub for Mistmint paid titles.
    """
    return split_title_mistmint(raw_title)


# ----------------------------------------------------------------------
# 3) ─── GENERIC HELPERS ───────────────────────────────────────────────
# ----------------------------------------------------------------------
def clean_description(raw_desc: str) -> str:
    soup = BeautifulSoup(raw_desc, "html.parser")
    for div in soup.select("div.c-content-readmore"):
        div.decompose()
    return re.sub(r"\s+", " ", soup.decode_contents()).strip()

def extract_pubdate_from_soup(li) -> datetime.datetime:
    """
    Returns a proper UTC datetime for a chapter <li>.
    Handles:
    - "May 22, 2025"
    - "3 hours ago"
    - "1 day ago"
    """
    now = datetime.datetime.now(datetime.timezone.utc)

    span = li.select_one("span.chapter-release-date i")
    if not span:
        return now

    datestr = span.get_text(strip=True)

    # 1) Try absolute "Month DD, YYYY"
    try:
        return (
            datetime.datetime.strptime(datestr, "%B %d, %Y")
            .replace(tzinfo=datetime.timezone.utc)
        )
    except ValueError:
        # 2) Relative "N units ago"
        parts = datestr.lower().split()
        if parts and parts[0].isdigit():
            n, unit = int(parts[0]), parts[1]
            if "minute" in unit:
                return now - datetime.timedelta(minutes=n)
            if "hour" in unit:
                return now - datetime.timedelta(hours=n)
            if "day" in unit:
                return now - datetime.timedelta(days=n)
            if "week" in unit:
                return now - datetime.timedelta(weeks=n)
        # 3) fallback
        return now

def smart_title(parts: list[str]) -> str:
    small = {"a","an","the","and","but","or","nor","for","so","yet",
             "at","by","in","of","on","to","up","via"}
    out = []
    last = len(parts) - 1
    for i, w in enumerate(parts):
        wl = w.lower()
        if i == 0 or i == last or wl not in small:
            out.append(w.capitalize())
        else:
            out.append(wl)
    return " ".join(out)

def format_volume_from_url(url: str) -> str:
    """
    Currently: Dragonholic-style /novel/... parsing.
    TODO: extend for mistminthaven.com slugs like
    volume-1-dream-s-beginning-chapter-30 → "Volume 1: Dream's Beginning"
    """
    segs = [s for s in urlparse(url).path.split("/") if s]
    if len(segs) >= 4 and segs[0] == "novel":
        raw   = unquote(segs[2]).replace("_","-").strip("-")
        parts = raw.split("-")
        if not parts:
            return ""

        colon_keywords = {"volume","chapter","vol","chap","arc","world","plane","story","v"}
        lead = parts[0].lower()

        if lead in colon_keywords and len(parts) >= 2 and parts[1].isdigit():
            num  = parts[1]
            rest = parts[2:]
            if lead == "v":
                if rest:
                    return f"V{num}: {smart_title(rest)}"
                else:
                    return f"V{num}"
            label = lead.capitalize()
            if rest:
                return f"{label} {num}: {smart_title(rest)}"
            else:
                return f"{label} {num}"

        return smart_title(parts)

    return ""

async def fetch_page(session: aiohttp.ClientSession, url: str) -> str:
    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                print(f"⚠️  {url} returned HTTP {resp.status}")
                return ""
            return await resp.text()
    except Exception as e:
        print(f"⚠️  Network error fetching {url}: {e}")
        return ""

def slug(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^\w\s\u0080-\uFFFF-]", "", s)  # keep unicode
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s


# ----------------------------------------------------------------------
# 4) ─── QUICK “HAS PREMIUM UPDATE?” CHECK ─────────────────────────────
# ----------------------------------------------------------------------
async def novel_has_paid_update_async(session, novel_url: str) -> bool:
    """
    Dragonholic: check if there was a premium chapter in the last 7 days.
    """
    html = await fetch_page(session, novel_url)
    if not html:
        return False

    li = BeautifulSoup(html, "html.parser").find("li", class_="wp-manga-chapter")
    if not li or "premium" not in li.get("class", []) or "free-chap" in li.get("class", []):
        return False

    pub = extract_pubdate_from_soup(li)
    return pub >= datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)

async def novel_has_paid_update_mistmint_async(session, novel_url: str) -> bool:
    """
    Mistmint Haven: no premium tier (yet), so always False.
    """
    return False


# ----------------------------------------------------------------------
# 5) ─── PAID-CHAPTER SCRAPERS ─────────────────────────────────────────
# ----------------------------------------------------------------------
async def scrape_paid_chapters_async(session, novel_url: str, host: str):
    """
    Dragonholic version.

    1. If HOSTING_SITE_DATA[host]["paid_feed_url"] exists, parse it.
    2. Otherwise scrape the novel page and build recent paid chapters.
    """
    feed_url = HOSTING_SITE_DATA.get(host, {}).get("paid_feed_url")
    if feed_url:
        parsed = feedparser.parse(feed_url)
        paid = []
        for e in parsed.entries:
            chap, ext = split_paid_chapter_dragonholic(e.title)
            paid.append({
                "volume":      "",
                "chaptername": chap,
                "nameextend":  ext,
                "link":        e.link,
                "description": e.description,
                "pubDate":     datetime.datetime(*e.published_parsed[:6], tzinfo=datetime.timezone.utc),
                "guid":        e.id or chap,
                "coin":        "",
            })
        return paid, ""

    # Fallback: scrape live page
    html = await fetch_page(session, novel_url)
    if not html:
        return [], ""

    soup = BeautifulSoup(html, "html.parser")
    main_desc_div = soup.select_one("div.description-summary")
    main_desc = clean_description(main_desc_div.decode_contents()) if main_desc_div else ""

    paid = []
    now = datetime.datetime.now(datetime.timezone.utc)

    # (a) volume blocks
    vol_ul = soup.select_one("ul.main.version-chap.volumns")
    if vol_ul:
        for vol_parent in vol_ul.select("li.parent.has-child"):
            vol_label   = vol_parent.select_one("a.has-child").get_text(strip=True)
            vol_display = vol_label

            for chap_li in vol_parent.select("ul.sub-chap-list li.wp-manga-chapter"):
                if "free-chap" in chap_li.get("class", []):
                    continue
                pub = extract_pubdate_from_soup(chap_li)
                if pub < now - datetime.timedelta(days=7):
                    continue

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
                    link = f"{novel_url}{slug(vol_display)}/{slug(chap_name)}/"

                guid = next(
                    (c.split("data-chapter-")[1]
                     for c in chap_li.get("class", [])
                     if c.startswith("data-chapter-")),
                    slug(chap_name)
                )

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

    # (b) no-volume blocks
    no_vol_ul = soup.select_one("ul.main.version-chap.no-volumn")
    if no_vol_ul:
        for chap_li in no_vol_ul.select("li.wp-manga-chapter"):
            if "free-chap" in chap_li.get("class", []):
                continue

            pub = extract_pubdate_from_soup(chap_li)
            if pub < now - datetime.timedelta(days=7):
                continue

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

            guid = next(
                (c.split("data-chapter-")[1]
                 for c in chap_li.get("class", [])
                 if c.startswith("data-chapter-")),
                slug(chap_name)
            )

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

    return paid, main_desc


async def scrape_paid_chapters_mistmint_async(session, novel_url: str, host: str):
    """
    Mistmint Haven: no premium layer.
    Always return nothing so paid_feed_generator.py won't blow up.
    """
    return [], ""


# ----------------------------------------------------------------------
# 6) ─── CHAPTER-NUMBER TUPLE (for sorting) ────────────────────────────
# ----------------------------------------------------------------------
def chapter_num_dragonholic(chaptername: str):
    nums = re.findall(r"\d+(?:\.\d+)?", chaptername)
    return tuple(float(n) if "." in n else int(n) for n in nums) if nums else (0,)


# ----------------------------------------------------------------------
# 7) ─── COMMENT-HELPERS ───────────────────────────────────────────────
# ----------------------------------------------------------------------
def split_comment_title_dragonholic(comment_title):
    t = " ".join(comment_title.split())
    m = re.search(r"^Comment on\s+(.+?)\s+by\s+.+$", t, re.IGNORECASE)
    return m.group(1).strip() if m else ""

def extract_chapter_dragonholic(link: str) -> str:
    m = re.search(r"#comment-(\d+)", link)
    if m:
        cid = m.group(1)
        approved = feedparser.parse(APPROVED_COMMENTS_FEED)
        for entry in approved.entries:
            if hasattr(entry, "approve_url") and f"c={cid}" in entry.approve_url:
                return entry.chapter

    parsed   = urlparse(link)
    segments = [s for s in parsed.path.split("/") if s]
    if len(segments) <= 2:
        return "Homepage"
    last = unquote(segments[-1]).replace("-", " ")
    return last if not last.lower().startswith(("novel","comments")) else "Homepage"

def build_comment_link_dragonholic(novel_title: str, host: str, placeholder_link: str) -> str:
    m = re.search(r"#comment-(\d+)", placeholder_link)
    if not m:
        return placeholder_link

    cid = m.group(1)
    chapter_label = extract_chapter_dragonholic(placeholder_link)
    chapter_slug  = slug(chapter_label)

    novel_url = HOSTING_SITE_DATA[host]["novels"][novel_title]["novel_url"]
    if not novel_url.endswith("/"):
        novel_url += "/"

    return f"{novel_url}{chapter_slug}/#comment-{cid}"

def split_reply_chain_dragonholic(raw: str) -> tuple[str,str]:
    from html import unescape
    ws_collapsed = " ".join(raw.split())
    t = unescape(ws_collapsed)
    m = re.match(
        r'\s*In reply to\s*<a [^>]+>([^<]+)</a>\.\s*(.*)$',
        t,
        re.IGNORECASE
    )
    if m:
        name, body = m.group(1).strip(), m.group(2).strip()
        return f"In reply to {name}", body
    else:
        return "", raw.strip()


# ----------------------------------------------------------------------
# 8) ─── DISPATCH TABLES & ENTRY POINT ─────────────────────────────────
# ----------------------------------------------------------------------
DRAGONHOLIC_UTILS = {
    # Free-feed stuff
    "split_title": split_title_dragonholic,
    "extract_volume": extract_volume_dragonholic,  # <-- ADD THIS

    # Paid-feed stuff
    "split_paid_title": split_paid_chapter_dragonholic,
    "format_volume_from_url": format_volume_from_url,
    "chapter_num": chapter_num_dragonholic,
    "novel_has_paid_update_async": novel_has_paid_update_async,
    "scrape_paid_chapters_async": scrape_paid_chapters_async,

    # Shared helpers
    "clean_description": clean_description,
    "extract_pubdate": extract_pubdate_from_soup,
    "split_comment_title": split_comment_title_dragonholic,
    "extract_chapter": extract_chapter_dragonholic,
    "build_comment_link": build_comment_link_dragonholic,
    "split_reply_chain": split_reply_chain_dragonholic,

    # passthroughs for mapping
    "get_novel_details": lambda host, title: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(title, {}),
    "get_host_translator": lambda host: HOSTING_SITE_DATA.get(host, {}).get("translator", ""),
    "get_host_logo": lambda host: HOSTING_SITE_DATA.get(host, {}).get("host_logo", ""),
    "get_featured_image": lambda title, host: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(title, {}).get("featured_image", ""),
    "get_novel_discord_role": lambda title, host: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(title, {}).get("discord_role_id", ""),
    "get_comments_feed_url": lambda host: HOSTING_SITE_DATA.get(host, {}).get("comments_feed_url", ""),
    "get_nsfw_novels": lambda: [],
}

MISTMINT_UTILS = {
    # Free-feed stuff
    "split_title": split_title_mistmint,
    "extract_volume": extract_volume_mistmint,  # <-- ADD THIS

    # Paid-feed stuff (stubbed)
    "split_paid_title": split_paid_chapter_mistmint,
    "format_volume_from_url": format_volume_from_url,  # still harmless
    "chapter_num": chapter_num_dragonholic,
    "novel_has_paid_update_async": novel_has_paid_update_mistmint_async,
    "scrape_paid_chapters_async": scrape_paid_chapters_mistmint_async,

    # shared helpers / mirrors
    "clean_description": clean_description,
    "extract_pubdate": extract_pubdate_from_soup,
    "split_comment_title": split_comment_title_dragonholic,
    "extract_chapter": extract_chapter_dragonholic,
    "build_comment_link": build_comment_link_dragonholic,
    "split_reply_chain": split_reply_chain_dragonholic,

    # passthroughs for mapping
    "get_novel_details": lambda host, title: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(title, {}),
    "get_host_translator": lambda host: HOSTING_SITE_DATA.get(host, {}).get("translator", ""),
    "get_host_logo": lambda host: HOSTING_SITE_DATA.get(host, {}).get("host_logo", ""),
    "get_featured_image": lambda title, host: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(title, {}).get("featured_image", ""),
    "get_novel_discord_role": lambda title, host: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(title, {}).get("discord_role_id", ""),
    "get_comments_feed_url": lambda host: HOSTING_SITE_DATA.get(host, {}).get("comments_feed_url", ""),
    "get_nsfw_novels": lambda: [],
}

def get_host_utils(host: str):
    if host == "Dragonholic":
        return DRAGONHOLIC_UTILS
    if host == "Mistmint Haven":
        return MISTMINT_UTILS
    return {}
