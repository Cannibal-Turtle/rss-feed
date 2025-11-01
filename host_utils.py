import re
import os
import json
import datetime
from datetime import timezone
from urllib.parse import urlparse, unquote
import requests

import aiohttp
import feedparser
from bs4 import BeautifulSoup

import hashlib

from novel_mappings import HOSTING_SITE_DATA


# =============================================================================
# GLOBAL CONSTANTS
# =============================================================================

APPROVED_COMMENTS_FEED = (
    "https://script.google.com/macros/s/"
    "AKfycbxx6YrbuG1WVqc5uRmmQBw3Z8s8k29RS0sgK9ivhbaTUYTp-8t76mzLo0IlL1LlqinY/exec"
)

MISTMINT_STATE_PATH = "mistmint_state.json"

# All arcs for [Quick Transmigration] The Delicate Little Beauty Keeps Getting Caught
# Used to figure out volume/arc info for any global chapter number.
TDLBKGC_ARCS = [
    {"arc_num": 1,  "title": "Tycoon Boss Gong × Pure Little Male Servant Shou",            "start": 1,   "end": 42},
    {"arc_num": 2,  "title": "Sea Serpent Chief Gong × Cute Little Merman Shou",            "start": 43,  "end": 79},
    {"arc_num": 3,  "title": "Brutal Evil Dragon Gong × Crossdressing Princess Shou",       "start": 80,  "end": 109},
    {"arc_num": 4,  "title": "Reborn Villain Gong × Powerless Noble Young Master Shou",     "start": 110, "end": 148},
    {"arc_num": 5,  "title": "Demon Lord Gong × Spiritual Medicine Shou",                   "start": 149, "end": 186},
    {"arc_num": 6,  "title": "Ruthless Daoist Exorcist Gong × Timid Fierce Ghost Shou",     "start": 187, "end": 224},
    {"arc_num": 7,  "title": "Broken Giant Wolf Gong × Soft Sweet White Rabbit Shou",       "start": 225, "end": 260},
    {"arc_num": 8,  "title": "Dominant Military Officer Gong × Fallen Young Master Shou",   "start": 261, "end": 295},
    {"arc_num": 9,  "title": "Bloodthirsty Zombie Gong × Sweet Researcher Shou",            "start": 296, "end": 331},
    {"arc_num": 10, "title": "Lowly Slave Gong × Imperial Prince Shou",                     "start": 332, "end": 369},
    {"arc_num": 11, "title": "War-Scarred Demon King Gong × Low-Rank Succubus Shou",        "start": 370, "end": 407},
    {"arc_num": 12, "title": "Street Bully Gong × Campus Male God Shou",                    "start": 408, "end": 444},
    {"arc_num": 13, "title": "Evil Magician Gong × Aloof Elf Shou",                         "start": 445, "end": 479},
    {"arc_num": 14, "title": "Mute Merman Gong × Cannon Fodder Caretaker Shou",             "start": 480, "end": 517},
    {"arc_num": 15, "title": "Game Boss Gong × Simple-Minded Player Shou",                  "start": 518, "end": 556},
    {"arc_num": 16, "title": "Gentle Film Emperor Gong × Little Nobody Assistant Shou",     "start": 557, "end": 594},
    {"arc_num": 17, "title": "Supreme AI Gong × Physically Weak Cyborg Shou",               "start": 595, "end": 628},
    {"arc_num": 18, "title": "Cold CEO Gong × Honest Married Wife Shou",                    "start": 629, "end": 666},
    {"arc_num": 19, "title": "Top Musician Gong × Autistic Little Pitiful Shou",            "start": 667, "end": 700},
    {"arc_num": 20, "title": "Tentacled Alien Gong × Passerby Doctor Shou",                 "start": 701, "end": 734},
]


# --- Mistmint comment helpers -----------------------------------------------

def _guid_from(parts):
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p).encode("utf-8", "ignore"))
        h.update(b"\x1f")
    return h.hexdigest()

def _extract_data_array_segment(raw: str) -> str | None:
    # Pull out the substring between "data":[ and its matching closing ]
    m = re.search(r'"data"\s*:\s*\[', raw)
    if not m:
        return None
    i = m.end()
    depth = 1
    in_string = False
    while i < len(raw):
        ch = raw[i]
        if in_string:
            if ch == '\\':
                i += 2
                continue
            if ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == '[':
                depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    return raw[m.end():i]  # between '[' and the matching ']'
        i += 1
    return None

def _mistmint_reply_flags_from_raw(raw_text: str) -> list[bool]:
    """
    Return a list of booleans with length == (#items - 1).
    flags[k] == True  => item k+1 is a reply to item k (boundary is '},{')
    flags[k] == False => top-level (boundary has whitespace: '}, {', '},\\n{', etc)

    If the JSON is fully minified and *every* boundary looks like a reply, the
    heuristic is not credible, so we disable it by returning [].
    """
    seg = _extract_data_array_segment(raw_text)
    if seg is None:
        return []
    flags = []
    for m in re.finditer(r'}(?P<ws1>\s*),(?P<ws2>\s*){', seg):
        ws = (m.group('ws1') or '') + (m.group('ws2') or '')
        flags.append(ws == '')  # no whitespace ⇒ reply-chaining
    # Disable adjacency if minification makes everything look like a reply.
    return [] if flags and all(flags) else flags

def _parse_iso_utc(s: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


def _mistmint_parse_chapter_label(ch: str):
    """
    'Chapter 1: 1.1' -> ('Chapter 1', 1)
    'Chapter 50'     -> ('Chapter 50', 50)
    '' or None       -> ('Homepage', None)
    """
    if not ch:
        return ("Homepage", None)
    m = re.match(r'^\s*Chapter\s+(\d+)', ch, re.IGNORECASE)
    if not m:
        # Unknown format, just show what we got
        return (ch.strip(), None)
    n = int(m.group(1))
    return (f"Chapter {n}", n)

def build_comment_link_mistmint(novel_title: str, host: str, chapter_label_or_empty: str) -> str:
    details = HOSTING_SITE_DATA[host]["novels"][novel_title]
    base = details["novel_url"].rstrip("/")
    label = (chapter_label_or_empty or "").strip()
    if not label:
        return base  # homepage

    m = re.search(r'chapter\s+(\d+)', label, re.IGNORECASE)
    if not m:
        return base
    ch = int(m.group(1))
    arc = _get_arc_for_ch(ch)
    if not arc:
        return base
    arc_slug = _slug_arc(arc["arc_num"], arc["title"])
    return f"{base}/{arc_slug}-chapter-{ch}"

def extract_chapter_mistmint(chapter_or_url: str) -> str:
    """
    If given a chapter label, return normalized ('Chapter N' or 'Homepage').
    If given a URL, try to pull Chapter N from ...-chapter-N; else 'Homepage'.
    """
    if not chapter_or_url:
        return "Homepage"
    if not chapter_or_url.startswith("http"):
        return _mistmint_parse_chapter_label(chapter_or_url)[0]

    # URL case: .../<arc-slug>-chapter-123
    m = re.search(r'-chapter-(\d+)(?:/|$)', chapter_or_url)
    if m:
        return f"Chapter {int(m.group(1))}"
    return "Homepage"


# --- Mistmint comments loader (JSON recent-comments endpoint) ---------------
def load_comments_mistmint(comments_feed_url: str):
    """
    Returns list[dict] with keys:
      novel_title, chapter, author, description, reply_to, posted_at
    """
    import os, json, requests

    out = []
    token  = os.getenv("MISTMINT_TOKEN", "").strip()     # raw JWT (no prefix)
    cookie = os.getenv("MISTMINT_COOKIE", "").strip()    # e.g. "mistmint_token=<JWT>"

    base_headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://mistminthaven.com",
        "Referer": "https://mistminthaven.com/",
    }

    def unauth(payload_text: str, payload_json: dict | None) -> bool:
        try:
            if isinstance(payload_json, dict) and str(payload_json.get("code", "")).startswith("401"):
                return True
        except Exception:
            pass
        t = (payload_text or "").lower()
        return ("you must be logged in" in t) or ('"code":401' in t)

    # return (resp, raw_text, parsed_json)
    def get_with(headers: dict, label: str):
        r = requests.get(comments_feed_url, headers=headers, timeout=20)
        ctype = r.headers.get("content-type", "?")
        raw = r.text
        print(f"[mistmint] try={label} status={r.status_code} ctype={ctype} bytes={len(r.content)}")
        pj = None
        try:
            pj = r.json()
        except Exception:
            pass
        return r, raw, pj

    payload = None
    raw_used = ""

    # Try #1: Bearer
    if token:
        h1 = dict(base_headers)
        h1["Authorization"] = f"Bearer {token}"
        r, raw, pj = get_with(h1, "bearer")
        if not unauth(raw, pj):
            payload, raw_used = (pj if pj is not None else {}), raw
        else:
            # Try #2: Cookie built from token (Nuxt/Auth setups)
            h2 = dict(base_headers)
            h2["Cookie"] = f"auth._token.local=Bearer%20{token}; auth.strategy=local"
            r, raw, pj = get_with(h2, "cookie-from-token")
            if not unauth(raw, pj):
                payload, raw_used = (pj if pj is not None else {}), raw

    # Try #3: Real session cookie if provided
    if payload is None and cookie:
        h3 = dict(base_headers)
        h3["Cookie"] = cookie
        r, raw, pj = get_with(h3, "cookie-secret")
        if not unauth(raw, pj):
            payload, raw_used = (pj if pj is not None else {}), raw

    if payload is None:
        print("[mistmint] unauthorized; set MISTMINT_TOKEN or MISTMINT_COOKIE")
        return out

    # ---- flexible list extraction (top-level or nested)
    def pick_list(obj):
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            for k in ("data", "items", "results", "comments", "entries"):
                v = obj.get(k)
                if isinstance(v, list):
                    return v
            v = obj.get("data")
            if isinstance(v, dict):
                for k in ("comments", "items", "results", "data", "entries"):
                    w = v.get(k)
                    if isinstance(w, list):
                        return w
        return []

    items = pick_list(payload)
    if not items:
        preview = str(payload)
        preview = preview[:200] + ("…" if len(preview) > 200 else "")
        print(f"[mistmint] no items; top-level keys={list(payload)[:6]} sample={preview!r}")
        return out

    # Common pick helper
    def pick(d, *cands, default=""):
        for k in cands:
            v = d.get(k)
            if v not in (None, ""):
                return v
        return default

    # Keys we’ll look for
    id_keys      = ("id", "_id", "commentId", "comment_id")
    parent_keys  = ("parentId", "parent_id", "inReplyTo", "in_reply_to", "replyToId", "reply_to_id")
    user_keys    = ("user", "author", "username", "name", "displayName")
    reply_user_keys = ("replyToUser", "reply_user", "replyToName", "reply_name", "parentUser", "parent_user", "toUser", "to_user")

    # 1) Build id->author map
    id_to_user = {}
    for obj in items:
        cid = pick(obj, *id_keys)
        if cid:
            id_to_user[str(cid)] = pick(obj, *user_keys)

    # 2) Heuristic adjacency flags (safe)
    flags = _mistmint_reply_flags_from_raw(raw_used or "")

    # Helper: parse timestamps
    def _parse_when(d):
        s = pick(d, "postedAt", "createdAt", "created_at", "date", "timestamp")
        try:
            return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    for i, obj in enumerate(items):
        novel_title = pick(obj, "novel", "novelTitle", "title")
        chapter     = pick(obj, "chapter", "chapterLabel", "chapterTitle")
        author      = pick(obj, *user_keys)
        body_raw    = pick(obj, "content", "body", "text", "message").strip()
        posted_at   = pick(obj, "postedAt", "createdAt", "created_at", "date", "timestamp")

        # 1) explicit reply hints
        reply_to = pick(obj, *reply_user_keys)

        # 2) parentId -> author
        if not reply_to:
            pid = pick(obj, *parent_keys)
            if pid and str(pid) in id_to_user:
                reply_to = id_to_user[str(pid)]

        # 3) adjacency fallback (only if credible)
        if not reply_to and flags and i > 0 and i-1 < len(flags) and flags[i-1]:
            prev = items[i-1]
            prev_author = pick(prev, *user_keys)
            same_novel  = (novel_title or "").strip() == pick(prev, "novel", "novelTitle", "title").strip()
            t_cur  = _parse_when(obj)
            t_prev = _parse_when(prev)
            close_in_time = (t_cur and t_prev and abs((t_cur - t_prev).total_seconds()) <= 120)
            if prev_author and author and prev_author != author and same_novel and close_in_time:
                reply_to = prev_author

        # 4) never show self-replies
        if reply_to and reply_to == author:
            reply_to = ""

        body = f"In reply to {reply_to}. {body_raw}" if reply_to else body_raw

        out.append({
            "novel_title": (novel_title or "").strip(),
            "chapter": chapter or "",
            "author": author or "",
            "description": body,
            "reply_to": reply_to,
            "posted_at": posted_at or "",
        })

    print(f"[mistmint] loaded {len(out)} raw comment(s)")
    if out:
        print(f"[mistmint] sample keys: {sorted(list(items[0].keys()))[:12]}")
    return out

    # detect reply adjacency off the original raw (still works)
    flags = _mistmint_reply_flags_from_raw(raw)

    def pick(d, *candidates, default=""):
        for k in candidates:
            v = d.get(k)
            if v not in (None, ""):
                return v
        return default

    for i, obj in enumerate(items):
        reply_to = items[i-1].get("user", "") if i > 0 and i-1 < len(flags) and flags[i-1] else ""

        novel_title = pick(obj, "novel", "novelTitle", "title")
        chapter     = pick(obj, "chapter", "chapterLabel", "chapterTitle")
        author      = pick(obj, "user", "author", "username", "name", "displayName")
        body_raw    = pick(obj, "content", "body", "text", "message").strip()
        posted_at   = pick(obj, "postedAt", "createdAt", "created_at", "date", "timestamp")

        body = f"In reply to {reply_to}. {body_raw}" if reply_to else body_raw

        out.append({
            "novel_title": (novel_title or "").strip(),
            "chapter": chapter or "",
            "author": author or "",
            "description": body,
            "reply_to": reply_to,
            "posted_at": posted_at or "",
        })

    print(f"[mistmint] loaded {len(out)} raw comment(s)")
    # peek first item keys to help future debugging
    if out:
        print(f"[mistmint] sample fields -> novel_title='{out[0]['novel_title']}', chapter='{out[0]['chapter']}', author='{out[0]['author']}'")

    return out


# =============================================================================
# MISTMINT STATE HELPERS (multi-novel, keyed by short_code)
# =============================================================================

def _load_mistmint_state():
    """
    mistmint_state.json looks like:
    {
      "tdlbkgc": {
        "last_posted_chapter": 0,
        "latest_available_chapter": 1
      },
      "another_short": {
        "last_posted_chapter": 12,
        "latest_available_chapter": 40
      }
    }
    """
    try:
        with open(MISTMINT_STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        state = {}

    # normalize any partial entries
    for scode, entry in state.items():
        entry.setdefault("last_posted_chapter", 0)
        entry.setdefault("latest_available_chapter", entry["last_posted_chapter"])
    return state


def _save_mistmint_state(state):
    with open(MISTMINT_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _get_arc_for_ch(ch_num: int):
    """
    Given a global chapter number (e.g. 50),
    return the arc dict containing it.
    """
    for arc in TDLBKGC_ARCS:
        if arc["start"] <= ch_num <= arc["end"]:
            return arc
    return None


def _slug_arc(arc_num: int, arc_title: str) -> str:
    """
    "Arc 1 Tycoon Boss Gong × Pure Little Male Servant Shou"
    -> "arc-1-tycoon-boss-gong-pure-little-male-servant-shou"
    """
    base = f"arc {arc_num} {arc_title}"
    s = base.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")


# =============================================================================
# MISTMINT PAID FEED (synthetic)
# =============================================================================

async def scrape_paid_chapters_mistmint_async(session, novel_url: str, host: str):
    """
    Generate synthetic "paid chapters" for ALL Mistmint novels in mapping.

    For each Mistmint novel:
    - Look up its short_code in novel_mappings.
    - Check mistmint_state.json[short_code].
      * last_posted_chapter
      * latest_available_chapter
    - For any new chapters in (last_posted+1 ... latest_available):
        build an RSS-style item:
          volume       -> "Arc X: <arc_title>"
          chaptername  -> "Chapter 50"
          nameextend   -> "1.7"  (arcNum.localIndexInArc)
          link         -> predictable URL based on arc slug + global chapter num
          guid         -> "<short_code>-<global_chapter_num>"

    After generating, bump last_posted_chapter = latest_available_chapter
    and save back to mistmint_state.json.

    Returns (all_items, "") where all_items is a list[dict] for feed builder.
    """
    all_items = []
    state = _load_mistmint_state()
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    mistmint_block = HOSTING_SITE_DATA.get(host, {}).get("novels", {})

    for novel_title, details in mistmint_block.items():
        short_code = details.get("short_code")
        if not short_code:
            # if a Mistmint novel in mapping doesn't define short_code,
            # we can't track it. skip silently.
            continue

        # get (or init) per-novel state
        novel_state = state.get(short_code, {
            "last_posted_chapter": 0,
            "latest_available_chapter": 0
        })
        last_posted = int(novel_state.get("last_posted_chapter", 0))
        latest_avail = int(novel_state.get("latest_available_chapter", 0))

        if latest_avail <= last_posted:
            # nothing new to export for this novel
            continue

        novel_slug = details["novel_url"].rstrip("/").split("/")[-1]
        desc_html  = details.get("custom_description", "")
        override   = details.get("pub_date_override", None)

        # build each missing chapter
        for ch in range(last_posted + 1, latest_avail + 1):
            arc = _get_arc_for_ch(ch)
            if not arc:
                # if you ever go beyond arc 20 and forget to extend TDLBKGC_ARCS,
                # we'll just skip unknown ranges instead of crashing.
                continue

            arc_num   = arc["arc_num"]
            arc_title = arc["title"]
            arc_local_index = ch - arc["start"] + 1  # chapter index inside that arc

            volume      = f"Arc {arc_num}: {arc_title}"
            chaptername = f"Chapter {ch}"
            nameextend  = f"{arc_num}.{arc_local_index}"

            arc_slug = _slug_arc(arc_num, arc_title)
            link = (
                "https://www.mistminthaven.com/novels/"
                f"{novel_slug}/{arc_slug}-chapter-{ch}"
            )

            pub_dt = now_utc
            if override:
                pub_dt = pub_dt.replace(**override)

            guid_val = f"{short_code}-{ch}"
    
            # pull the per-novel fixed price (default "5" just in case)
            coin_amt = str(details.get("coin_price", "5"))
    
            all_items.append({
                "volume":      volume,
                "chaptername": chaptername,
                "nameextend":  nameextend,
                "link":        link,
                "description": desc_html,
                "pubDate":     pub_dt,
                "guid":        guid_val,
                "coin":        coin_amt,
                "novel_title": novel_title
            })
            
        # advance pointer for THIS novel
        novel_state["last_posted_chapter"] = latest_avail
        state[short_code] = novel_state

    # persist updated state for next run
    _save_mistmint_state(state)

    return all_items, ""


async def novel_has_paid_update_mistmint_async(session, novel_url: str) -> bool:
    """
    Return True if *any* Mistmint novel in mapping has new premium chapters
    we haven't exported yet.
    """
    state = _load_mistmint_state()
    mistmint_block = HOSTING_SITE_DATA.get("Mistmint Haven", {}).get("novels", {})

    for _title, details in mistmint_block.items():
        short_code = details.get("short_code")
        if not short_code:
            continue
        novel_state = state.get(short_code, {
            "last_posted_chapter": 0,
            "latest_available_chapter": 0
        })
        if int(novel_state.get("latest_available_chapter", 0)) > int(novel_state.get("last_posted_chapter", 0)):
            return True
    return False


def split_paid_chapter_mistmint(raw_title: str):
    """
    Kept for API compatibility with Dragonholic, but Mistmint premium
    chapters are synthetic, so there's nothing real to parse.
    """
    return ("", "")


# =============================================================================
# DRAGONHOLIC PAID UPDATE CHECK / SCRAPE
# =============================================================================

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
            link = href
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

        return {
            "volume":      vol_label,
            "chaptername": chap_name,
            "nameextend":  nameext,
            "link":        link,
            "description": main_desc,
            "pubDate":     pub_dt,
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


def split_title_mistmint(full_title: str):
    """
    "Miss Priest ... — Volume 1: Dream’s Beginning, Chapter 30 — Card Master"
    "My Ex-Wife ... — Chapter 13 — The Ring"

    Returns (novel_title, 'Chapter NN', subtitle).
    """
    parts = [p.strip() for p in full_title.split(" — ")]

    novel_title = parts[0] if len(parts) > 0 else full_title.strip()
    middle      = parts[1] if len(parts) > 1 else ""
    subtitle    = parts[2] if len(parts) > 2 else ""

    if ", Chapter " in middle:
        # "Volume 1: Dream’s Beginning, Chapter 30"
        _before, after = middle.split(", Chapter ", 1)
        chaptername = f"Chapter {after.strip()}"
    else:
        # "Chapter 13"
        chaptername = middle.strip()

    return novel_title, chaptername, subtitle


def extract_volume_dragonholic(full_title: str, link: str) -> str:
    return format_volume_from_url(link)


def extract_volume_mistmint(full_title: str, link: str) -> str:
    """
    From "Volume 1: Dream’s Beginning, Chapter 30"
    we return "Volume 1: Dream’s Beginning".
    If it's just "Chapter NN", return "".
    """
    parts = [p.strip() for p in full_title.split(" — ")]
    if len(parts) < 2:
        return ""

    middle = parts[1]
    if ", Chapter " in middle:
        before, _after = middle.split(", Chapter ", 1)
        return before.strip()

    return ""


# =============================================================================
# DRAGONHOLIC PAID TITLE PARSER
# =============================================================================

def split_paid_chapter_dragonholic(raw_title: str):
    cleaned = re.sub(r"<i[^>]*>.*?</i>", "", raw_title, flags=re.DOTALL).strip()
    parts = cleaned.split(" - ", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return cleaned, ""


# =============================================================================
# OTHER SHARED HELPERS
# =============================================================================

def chapter_num(chaptername: str):
    """
    Turn "Chapter 640" / "Chapter 12.5" / "1.1"
    into a tuple of numbers so sorting is numeric.
    """
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


def split_comment_title_dragonholic(comment_title: str) -> str:
    collapsed = " ".join(comment_title.split())
    m = re.search(r"^Comment on\s+(.+?)\s+by\s+.+$", collapsed, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def extract_chapter_dragonholic(link: str) -> str:
    m = re.search(r"#comment-(\d+)", link)
    if m:
        cid = m.group(1)
        approved = feedparser.parse(APPROVED_COMMENTS_FEED)
        for entry in approved.entries:
            if hasattr(entry, "approve_url") and f"c={cid}" in entry.approve_url:
                return entry.chapter

    parsed = urlparse(link)
    segments = [s for s in parsed.path.split("/") if s]
    if len(segments) <= 2:
        return "Homepage"

    last = unquote(segments[-1]).replace("-", " ")
    lower = last.lower()
    if lower.startswith("novel") or lower.startswith("comments"):
        return "Homepage"
    return last


def build_comment_link_dragonholic(novel_title: str, host: str, placeholder_link: str) -> str:
    m = re.search(r"#comment-(\d+)", placeholder_link)
    if not m:
        return placeholder_link

    cid = m.group(1)
    chapter_label = extract_chapter_dragonholic(placeholder_link)
    chapter_slug = slug(chapter_label)

    base_url = HOSTING_SITE_DATA[host]["novels"][novel_title]["novel_url"]
    if not base_url.endswith("/"):
        base_url += "/"

    return f"{base_url}{chapter_slug}/#comment-{cid}"


def split_reply_chain_dragonholic(raw: str) -> tuple:
    from html import unescape
    ws_collapsed = " ".join(raw.split())
    t = unescape(ws_collapsed)

    m = re.match(
        r'\s*In reply to\s*<a [^>]+>([^<]+)</a>\.\s*(.*)$',
        t,
        re.IGNORECASE
    )
    if m:
        name = m.group(1).strip()
        body = m.group(2).strip()
        return f"In reply to {name}", body

    return "", raw.strip()


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

    # Comments / misc
    "clean_description": clean_description,
    "extract_pubdate": extract_pubdate_from_soup,
    "split_comment_title": split_comment_title_dragonholic,
    "extract_chapter": extract_chapter_dragonholic,
    "build_comment_link": build_comment_link_dragonholic,
    "split_reply_chain": split_reply_chain_dragonholic,

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

MISTMINT_UTILS = {
    # Free/public feed
    "split_title": split_title_mistmint,
    "extract_volume": extract_volume_mistmint,

    # Paid feed (synthetic)
    "split_paid_title": split_paid_chapter_mistmint,
    "format_volume_from_url": format_volume_from_url,
    "chapter_num": chapter_num,
    "novel_has_paid_update_async": novel_has_paid_update_mistmint_async,
    "scrape_paid_chapters_async": scrape_paid_chapters_mistmint_async,

    # Comments/etc. (reuse Dragonholic logic for now)
    "build_comment_link": build_comment_link_mistmint,
    "extract_chapter":    extract_chapter_mistmint,
    "reply_flags_from_raw": _mistmint_reply_flags_from_raw,
    "load_comments": load_comments_mistmint,

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


def get_host_utils(host: str):
    if host == "Dragonholic":
        return DRAGONHOLIC_UTILS
    if host == "Mistmint Haven":
        return MISTMINT_UTILS
    return {}
