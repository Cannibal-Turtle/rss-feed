import re
import datetime
from urllib.parse import urlparse, unquote
from html import unescape
import aiohttp
import feedparser
from bs4 import BeautifulSoup

from novel_mappings import HOSTING_SITE_DATA

# =============================================================================
# GLOBAL CONSTANTS
# =============================================================================

# Dragonholic paid pubdate override (UTC)
DH_PUBDATE_OVERRIDE = {"hour": 12, "minute": 0, "second": 0}  # set to None to disable

APPROVED_COMMENTS_FEED = (
    "https://script.google.com/macros/s/"
    "AKfycbxx6YrbuG1WVqc5uRmmQBw3Z8s8k29RS0sgK9ivhbaTUYTp-8t76mzLo0IlL1LlqinY/exec"
)

# --- shared HTTP defaults (Dragonholic) ---
UA_STR = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
DEFAULT_HEADERS = {"User-Agent": UA_STR}
AIOHTTP_TIMEOUT = aiohttp.ClientTimeout(total=20)  # if using aiohttp

# =============================================================================
# DRAGONHOLIC PAID UPDATE CHECK / SCRAPE
# =============================================================================

def tune_paid_pubdate(source: str, dt: datetime.datetime) -> datetime.datetime:
    # Apply override only to HTML-scraped (state) items
    if DH_PUBDATE_OVERRIDE and source == "html":
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        dt = dt.astimezone(datetime.timezone.utc)
        return dt.replace(
            hour=DH_PUBDATE_OVERRIDE.get("hour", dt.hour),
            minute=DH_PUBDATE_OVERRIDE.get("minute", dt.minute),
            second=DH_PUBDATE_OVERRIDE.get("second", dt.second),
            microsecond=0,
        )
    # still normalize tz to UTC for safety if you like (optional):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt
    
async def fetch_page(session: aiohttp.ClientSession, url: str) -> str:
    try:
        async with session.get(url, headers=DEFAULT_HEADERS, timeout=AIOHTTP_TIMEOUT) as resp:
            if resp.status != 200:
                print(f"⚠️  {url} returned HTTP {resp.status}")
                return ""
            return await resp.text()
    except Exception as e:
        print(f"⚠️  Network error fetching {url}: {e}")
        return ""

def clean_description(raw_desc: str) -> str:
    soup = BeautifulSoup(raw_desc, "html.parser")
    for div in soup.select("div.c-content-readmore"):
        div.decompose()
    text_html = soup.decode_contents()
    return re.sub(r"\s+", " ", text_html).strip()


def extract_pubdate_from_soup(li) -> datetime.datetime:
    now = datetime.datetime.now(datetime.timezone.utc)
    span = li.select_one("span.chapter-release-date i")
    if not span:
        return now

    datestr = span.get_text(strip=True)

    # absolute form: "May 22, 2025"
    try:
        dt_naive = datetime.datetime.strptime(datestr, "%B %d, %Y")
        return dt_naive.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        pass

    # relative "3 hours ago", "1 day ago"
    parts = datestr.lower().split()
    if parts and parts[0].isdigit():
        n = int(parts[0])
        unit = parts[1]
        if "minute" in unit:
            return now - datetime.timedelta(minutes=n)
        if "hour" in unit:
            return now - datetime.timedelta(hours=n)
        if "day" in unit:
            return now - datetime.timedelta(days=n)
        if "week" in unit:
            return now - datetime.timedelta(weeks=n)

    return now


async def novel_has_paid_update_async(session, novel_url: str) -> bool:
    """
    Dragonholic: True if there's a premium (not free) chapter in last 7 days.
    """
    html = await fetch_page(session, novel_url)
    if not html:
        return False

    soup = BeautifulSoup(html, "html.parser")
    li = soup.find("li", class_="wp-manga-chapter")
    if not li:
        return False

    classes = li.get("class", [])
    if "premium" not in classes or "free-chap" in classes:
        return False

    pub = extract_pubdate_from_soup(li)
    seven_days_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
    return pub >= seven_days_ago


def slug(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^\w\s\u0080-\uFFFF-]", "", s)  # keep unicode
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")


async def scrape_paid_chapters_async(session, novel_url: str, host: str):
    """
    Dragonholic premium chapters.
    Try host_data['paid_feed_url'] if it exists,
    else scrape the live HTML.
    """
    host_data = HOSTING_SITE_DATA.get(host, {})
    feed_url = host_data.get("paid_feed_url")

    # Branch A: direct paid RSS if you ever define it in mapping
    if feed_url:
        parsed = feedparser.parse(feed_url)
        paid = []
        for e in parsed.entries:
            chap, ext = split_paid_chapter_dragonholic(e.title)
            pub_dt = datetime.datetime(*e.published_parsed[:6], tzinfo=datetime.timezone.utc)
            paid.append({
                "source":      "rss", 
                "volume":      "",
                "chaptername": chap,
                "nameextend":  ext,
                "link":        e.link,
                "description": e.description,
                "pubDate":     pub_dt,
                "guid":        e.id or chap,
                "coin":        "",
            })
        return paid, ""

    # Branch B: scrape site HTML
    html = await fetch_page(session, novel_url)
    if not html:
        return [], ""

    soup = BeautifulSoup(html, "html.parser")

    # summary for <description>
    main_desc_div = soup.select_one("div.description-summary")
    main_desc = clean_description(main_desc_div.decode_contents()) if main_desc_div else ""

    paid_items = []
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now_utc - datetime.timedelta(days=7)

    def handle_chapter_li(li, vol_label: str):
        classes = li.get("class", [])

        # skip if it's free or not premium
        if "free-chap" in classes:
            return None
        if "premium" not in classes:
            return None

        pub_dt = extract_pubdate_from_soup(li)
        if pub_dt < cutoff:
            return None

        a = li.find("a")
        if not a:
            return None

        raw_html = a.decode_contents()

        # the first text before any tags is usually "Chapter X"
        m1 = re.match(r"\s*([^<]+)", raw_html)
        chap_name = m1.group(1).strip() if m1 else raw_html.strip()

        # anything after </i> - ... is the subtitle
        m2 = re.search(r"</i>\s*[-–]\s*(.+)", raw_html)
        nameext = m2.group(1).strip() if m2 else ""

        href = a.get("href", "").strip()
        if href and href != "#":
            link = coerce_to_new_if_dh(href)
        else:
            if vol_label:
                link = f"{novel_url}{slug(vol_label)}/{slug(chap_name)}/"
            else:
                link = f"{novel_url}{slug(chap_name)}/"

        guid = None
        for c in classes:
            if c.startswith("data-chapter-"):
                guid = c.split("data-chapter-")[1]
                break
        if not guid:
            guid = slug(chap_name)

        coin_el = li.select_one("span.coin")
        coin_val = coin_el.get_text(strip=True) if coin_el else ""

        tuned_pub = tune_paid_pubdate("html", pub_dt)

        return {
            "source": "html", 
            "volume":      vol_label,
            "chaptername": chap_name,
            "nameextend":  nameext,
            "link":        link,
            "description": main_desc,
            "pubDate":     tuned_pub,
            "guid":        guid,
            "coin":        coin_val
        }

    # with-volume structure
    vol_ul = soup.select_one("ul.main.version-chap.volumns")
    if vol_ul:
        for vol_parent in vol_ul.select("li.parent.has-child"):
            vol_label_el = vol_parent.select_one("a.has-child")
            vol_label = vol_label_el.get_text(strip=True) if vol_label_el else ""
            for chap_li in vol_parent.select("ul.sub-chap-list li.wp-manga-chapter"):
                item = handle_chapter_li(chap_li, vol_label)
                if item:
                    paid_items.append(item)

    # flat list structure
    no_vol_ul = soup.select_one("ul.main.version-chap.no-volumn")
    if no_vol_ul:
        for chap_li in no_vol_ul.select("li.wp-manga-chapter"):
            item = handle_chapter_li(chap_li, vol_label="")
            if item:
                paid_items.append(item)

    return paid_items, main_desc


# =============================================================================
# FREE FEED PARSING HELPERS
# =============================================================================

def split_title_dragonholic(full_title: str):
    parts = full_title.split(" - ")
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip(), ""
    if len(parts) >= 3:
        clean_parts = [
            p.strip()
            for p in parts[2:]
            if p.strip() and p.strip() != "-"
        ]
        return parts[0].strip(), parts[1].strip(), " ".join(clean_parts)
    return full_title.strip(), "", ""


def extract_volume_dragonholic(full_title: str, link: str) -> str:
    return format_volume_from_url(link)


# =============================================================================
# DRAGONHOLIC PAID TITLE PARSER
# =============================================================================

def split_paid_chapter_dragonholic(raw_title: str):
    cleaned = re.sub(r"<i[^>]*>.*?</i>", "", raw_title, flags=re.DOTALL).strip()
    parts = cleaned.split(" - ", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return cleaned, ""

def split_comment_title_dragonholic(comment_title: str) -> str:
    collapsed = " ".join(comment_title.split())
    m = re.search(r"^Comment on\s+(.+?)\s+by\s+.+$", collapsed, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def extract_chapter_dragonholic(link: str) -> str:
    # If this is a direct comment link, try to resolve its chapter from the approved feed.
    m = re.search(r"#comment-(\d+)", link)
    if m:
        cid = m.group(1)
        approved = feedparser.parse(APPROVED_COMMENTS_FEED)
        for entry in approved.entries:
            # Your Apps Script feed puts an approve_url and a custom <chapter> field
            if hasattr(entry, "approve_url") and f"c={cid}" in entry.approve_url:
                if hasattr(entry, "chapter") and entry.chapter:
                    return entry.chapter

    # Fallback: parse the URL path
    path = urlparse(link).path.rstrip("/")
    segments = [s for s in path.split("/") if s]
    if len(segments) <= 2:
        return "Homepage"

    tail_slug = segments[-1]           # e.g. "chapter-12-some-title" or "homepage"
    tail = tail_slug.lower()

    # Explicit home-y tails
    if tail in {"homepage", "comments"}:
        return "Homepage"

    # Match "chapter-extra-N" or "chapter-N(.M)" anywhere in the tail
    m = re.search(r'(?:^|-)chapter-(?:(extra)-)?(\d+(?:\.\d+)?)\b', tail, re.I)
    if m:
        is_extra = bool(m.group(1))
        num = m.group(2)
        return f"Chapter {'Extra ' if is_extra else ''}{num}"

    # Match plain "extra-N" (in case site omits 'chapter-')
    m = re.search(r'(?:^|-)extra-(\d+)\b', tail, re.I)
    if m:
        return f"Chapter Extra {m.group(1)}"

    # Last-resort: humanize the last segment
    last = unquote(tail_slug).replace("-", " ").strip()
    if last.lower().startswith(("novel", "comments")):
        return "Homepage"
    return last or "Homepage"


def build_comment_link_dragonholic(novel_title: str, host: str, placeholder_link: str) -> str:
    m = re.search(r"#comment-(\d+)", placeholder_link)
    if not m:
        return coerce_to_new_if_dh(placeholder_link)  # <- simple bridge

    cid = m.group(1)
    chapter_label = extract_chapter_dragonholic(placeholder_link)
    chapter_slug = slug(chapter_label)

    base_url = HOSTING_SITE_DATA[host]["novels"][novel_title]["novel_url"]
    if not base_url.endswith("/"):
        base_url += "/"

    return coerce_to_new_if_dh(f"{base_url}{chapter_slug}/#comment-{cid}")

def split_reply_chain_dragonholic(raw: str) -> tuple[str, str]:
    from html import unescape
    import re
    s = unescape(raw or "")
    s = re.sub(r"\s+", " ", s).strip()
    s_head = re.sub(r'^(?:\s*<[^>]+>\s*)+', '', s)

    # 1) HTML-tagged name (<a>…</a> or any tag), optional whitespace + punctuation
    m = re.match(r'(?is)^\s*in\s+reply\s+to\s*<[^>]*>([^<]+)</[^>]*>\s*[.,:;!?]?\s*(.*)$', s_head)
    if m:
        name, body = m.group(1).strip(), m.group(2).strip()
        body = re.sub(r'\s+([.,!?;:])', r'\1', body)
        return f"In reply to {name}", body

    # 2) Plain-text variant (feeds that already stripped the anchor)
    m = re.match(r'(?is)^\s*in\s+reply\s+to\s+([^.:\n<]+?)\s*[.,:;!?]?\s*(.+)?$', s_head)
    if m:
        name, body = m.group(1).strip(), m.group(2).strip()
        body = re.sub(r'\s+([.,!?;:])', r'\1', body)
        return f"In reply to {name}", body

    return "", (raw or "").strip()

def pick_comment_html_dragonholic(entry) -> str:
    # Dragonholic puts the reply header in description
    return unescape(entry.get("description", "") or "")


# =============================================================================
# OTHER SHARED HELPERS
# =============================================================================

def chapter_num(chaptername: str):
    s = (chaptername or '').lower()

    # Extras → very large rank so they come after normal chapters
    m = re.search(r'chapter\s+extra\s+(\d+)', s)
    if not m:
        m = re.search(r'\bextra\s+(\d+)', s)
    if m:
        return (10**9, int(m.group(1)))  # extras at the end

    # Normal numeric (supports decimals like 12.5)
    nums = re.findall(r"\d+(?:\.\d+)?", chaptername)
    if not nums:
        return (0,)
    out = []
    for n in nums:
        out.append(float(n) if "." in n else int(n))
    return tuple(out)


def smart_title(parts):
    small = {
        "a","an","the","and","but","or","nor","for","so","yet",
        "at","by","in","of","on","to","up","via"
    }
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
    Mainly Dragonholic-style URLs:
    /novel/<slug>/<volume-1-the-beginning>/<chapter-1-some-name>/
    """
    segs = [s for s in urlparse(url).path.split("/") if s]
    if len(segs) >= 4 and segs[0] == "novel":
        raw = unquote(segs[2]).replace("_", "-").strip("-")
        parts = raw.split("-")
        if not parts:
            return ""

        colon_keywords = {
            "volume", "chapter", "vol", "chap", "arc", "world", "plane", "story", "v"
        }
        lead = parts[0].lower()

        if lead in colon_keywords and len(parts) >= 2 and parts[1].isdigit():
            num = parts[1]
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

# ===== Dragonholic URL Bridge (Lumina theme) ================================

from urllib.parse import urlparse, urlunparse

_OLD_HOST = "dragonholic.com"
_NEW_HOST = "dragonholictranslations.com"

def _with_host(parsed, host):
    return parsed._replace(netloc=host)

def _swap_segment(path, old_seg, new_seg):
    # Expect paths beginning with /novel/<slug>/... or /series/<slug>/...
    parts = [p for p in path.split("/") if p != ""]
    if not parts:
        return path
    if parts[0] == old_seg:
        parts[0] = new_seg
    return "/" + "/".join(parts) + ("/" if path.endswith("/") else "")

def normalize_trailing_slash(url: str) -> str:
    # keep a trailing slash for series/chapter URLs (your code expects that)
    p = urlparse(url)
    path = p.path
    if not path.endswith("/"):
        path = path + "/"
    return urlunparse(p._replace(path=path))

def dh_old_to_new(url: str) -> str:
    """
    Translate any old Dragonholic URL to the new domain & path structure.
    - domain:  dragonholic.com  -> dragonholictranslations.com
    - segment: /novel/...       -> /series/...
    Leaves other URLs untouched. Keeps tail slug (e.g., extra-8) intact.
    """
    if not url:
        return url
    p = urlparse(url)
    if p.netloc != _OLD_HOST:
        return url  # not an old DH URL; leave as-is

    # Swap host
    p2 = _with_host(p, _NEW_HOST)
    # Swap leading path segment /novel -> /series
    new_path = _swap_segment(p2.path, "novel", "series")
    # Normalize trailing slash
    return normalize_trailing_slash(urlunparse(p2._replace(path=new_path)))

def dh_new_to_old(url: str) -> str:
    """
    Reverse mapping if you need it (optional).
    - domain:  dragonholictranslations.com -> dragonholic.com
    - segment: /series/...                 -> /novel/...
    """
    if not url:
        return url
    p = urlparse(url)
    if p.netloc != _NEW_HOST:
        return url
    p2 = _with_host(p, _OLD_HOST)
    old_path = _swap_segment(p2.path, "series", "novel")
    return normalize_trailing_slash(urlunparse(p2._replace(path=old_path)))

def is_dh_old(url: str) -> bool:
    try:
        return urlparse(url).netloc == _OLD_HOST
    except Exception:
        return False

def is_dh_new(url: str) -> bool:
    try:
        return urlparse(url).netloc == _NEW_HOST
    except Exception:
        return False

def coerce_to_new_if_dh(url: str) -> str:
    """
    Convenience: if URL is from either DH domain, return the 'new' equivalent.
    Otherwise return it unchanged.
    """
    if is_dh_old(url):
        return dh_old_to_new(url)
    if is_dh_new(url):
        # still normalize /novel -> /series if someone pasted a weird path
        p = urlparse(url)
        new_path = _swap_segment(p.path, "novel", "series")
        return normalize_trailing_slash(urlunparse(p._replace(path=new_path)))
    return url

# --- Transparent link bridge for Dragonholic feeds (Lumina) ---

if not getattr(feedparser, "_dh_link_bridge_installed", False):
    _orig_parse = feedparser.parse

    def _parse_and_bridge(url, *args, **kwargs):
        feed = _orig_parse(url, *args, **kwargs)
        try:
            # Only touch Dragonholic feeds
            if isinstance(url, str) and ("dragonholic.com" in url or "dragonholictranslations.com" in url):
                for e in getattr(feed, "entries", []):
                    link = getattr(e, "link", "")
                    if link:
                        e.link = coerce_to_new_if_dh(link)
        except Exception:
            # Never break caller on patch issues
            pass
        return feed

    feedparser.parse = _parse_and_bridge
    feedparser._dh_link_bridge_installed = True
    
# =============================================================================
# DISPATCH TABLE
# =============================================================================

DRAGONHOLIC_UTILS = {
    # Free/public feed
    "split_title": split_title_dragonholic,
    "extract_volume": extract_volume_dragonholic,

    # Paid feed
    "split_paid_title": split_paid_chapter_dragonholic,
    "format_volume_from_url": format_volume_from_url,
    "chapter_num": chapter_num,
    "novel_has_paid_update_async": novel_has_paid_update_async,
    "scrape_paid_chapters_async": scrape_paid_chapters_async,
    "tune_paid_pubdate": tune_paid_pubdate,

    # Comments / misc
    "clean_description": clean_description,
    "extract_pubdate": extract_pubdate_from_soup,
    "split_comment_title": split_comment_title_dragonholic,
    "extract_chapter": extract_chapter_dragonholic,
    "build_comment_link": build_comment_link_dragonholic,
    "split_reply_chain": split_reply_chain_dragonholic,
    "pick_comment_html": pick_comment_html_dragonholic,

    # passthroughs to novel_mappings
    "get_novel_details":
        lambda host, title: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(title, {}),
    "get_host_translator":
        lambda host: HOSTING_SITE_DATA.get(host, {}).get("translator", ""),
    "get_host_logo":
        lambda host: HOSTING_SITE_DATA.get(host, {}).get("host_logo", ""),
    "get_featured_image":
        lambda title, host: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(title, {}).get("featured_image", ""),
    "get_novel_discord_role":
        lambda title, host: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(title, {}).get("discord_role_id", ""),
    "get_comments_feed_url":
        lambda host: HOSTING_SITE_DATA.get(host, {}).get("comments_feed_url", ""),
    "get_nsfw_novels":
        lambda: [],
}



