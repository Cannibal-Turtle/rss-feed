import re
import os
import json
import datetime
import traceback
import time
from urllib.parse import urlparse, unquote
import requests
from html import unescape
import aiohttp
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Optional, Tuple
from collections import Counter
from contextlib import contextmanager
import hashlib
import unicodedata

from novel_mappings import HOSTING_SITE_DATA

# === GitHub Actions diagnostics helpers ======================================

COIN_MANUAL_DEFAULT = os.getenv("MISTMINT_MANUAL_COIN", "5").strip()

DIAG = {"counts": Counter(), "errors": [], "events": []}

def _gha(level: str, title: str, msg: str = ""):
    # levels: error, warning, notice
    print(f"::{level} title={title}::{msg}")

def diag_ok(kind: str, **ctx):
    DIAG["counts"][f"ok:{kind}"] += 1
    if ctx:
        DIAG["events"].append({"ok": kind, **ctx})

def diag_fail(kind: str, **ctx):
    DIAG["counts"][f"fail:{kind}"] += 1
    DIAG["errors"].append({"fail": kind, **ctx})
    # escalate level by kind
    level = "warning"
    if kind.startswith(("api-5xx","api-auth","api-timeout","api-exception")):
        level = "error"
    _gha(level, kind, json.dumps(ctx, ensure_ascii=False)[:900])

@contextmanager
def diag_step(name: str, **ctx):
    print(f"::group::{name}")
    t0 = time.time()
    try:
        yield
        diag_ok(f"step:{name}", **ctx)
    except Exception as e:
        diag_fail(f"step:{name}", error=str(e), tb=traceback.format_exc(limit=8), **ctx)
        raise
    finally:
        dt = int((time.time() - t0) * 1000)
        print(f"{name} took {dt} ms")
        print("::endgroup::")

def diag_snapshot(name: str, obj):
    try:
        os.makedirs("snapshots", exist_ok=True)
        with open(f"snapshots/{name}.json","w",encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        _gha("notice","snapshot",f"wrote snapshots/{name}.json")
    except Exception as e:
        _gha("warning","snapshot-failed",str(e))

def diag_summary(save_json: bool = True):
    print("::group::diagnostic-summary")
    for k,v in DIAG["counts"].most_common():
        print(f"{k}: {v}")
    if DIAG["errors"]:
        _gha("error","first-error", json.dumps(DIAG["errors"][0], ensure_ascii=False)[:900])
    print("::endgroup::")
    if save_json:
        try:
            os.makedirs("snapshots", exist_ok=True)
            with open("snapshots/diag.json","w",encoding="utf-8") as f:
                json.dump(DIAG, f, ensure_ascii=False, indent=2)
            _gha("notice","diag-summary","wrote snapshots/diag.json")
        except Exception as e:
            _gha("warning","diag-save-failed",str(e))
# ==============================================================================

# =============================================================================
# GLOBAL CONSTANTS
# =============================================================================

MISTMINT_STATE_PATH = os.getenv("MISTMINT_STATE_PATH", "mistmint_state.json")
UA_STR = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
DEFAULT_HEADERS = {"User-Agent": UA_STR}
_MISTMINT_HOME_CACHE: dict[str, dict] = {}
AIOHTTP_TIMEOUT = aiohttp.ClientTimeout(total=20)

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

# ─── Mode & state helpers required by async paid functions ───────────────────

def _manual_mode_on() -> bool:
    # When set to "1" we force STATE mode (no live API scraping)
    return (os.getenv("MISTMINT_FORCE_STATE", "0") or "0").strip() == "1"

def _mistmint_mode() -> str:
    # If manual override is on or we have no cookie, use STATE; else API.
    return "STATE" if _manual_mode_on() or not _resolve_mistmint_cookie() else "API"

def _log_mistmint_mode(phase: str, novel_url: str = ""):
    try:
        _gha("notice", "mistmint-mode", json.dumps({
            "phase": phase,
            "mode": _mistmint_mode(),
            "has_cookie": bool(_resolve_mistmint_cookie()),
            "novel_url": (novel_url or "")[:200]
        })[:300])
    except Exception:
        # keep it non-fatal
        print(f"[mistmint] mode={_mistmint_mode()} phase={phase} url={novel_url}")

def _load_mistmint_state() -> dict:
    try:
        with open(MISTMINT_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _mistmint_slug_from_url(novel_url: str) -> str:
    return (novel_url or "").rstrip("/").split("/")[-1]

def _mistmint_find_details_by_url(host: str, novel_url: str):
    block = HOSTING_SITE_DATA.get(host, {}).get("novels", {}) or {}
    want = (novel_url or "").rstrip("/")
    for title, det in block.items():
        if (det.get("novel_url") or "").rstrip("/") == want:
            return title, det
    return "", {}

# =============================================================================
# API-based Mistmint paid scraper + detector (fallback to state)
# =============================================================================

BASE_APP = "https://www.mistminthaven.com"
BASE_API = "https://api.mistminthaven.com/api"
ALL_COMMENTS_URL = f"{BASE_API}/comments/trans/all-comments"

UUID_RE = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
CHAPTERID_RE = re.compile(
    rf'(?:"|\\")chapterId(?:"|\\")\s*:\s*(?:"|\\")({UUID_RE})(?:"|\\")',
    re.I
)

def _extract_chapter_id_from_html(html: str, chapter_slug: str) -> Optional[str]:
    """
    Fallback: scan inline JSON for the specific chapter slug, then pull its id (UUID).
    Works whether the JSON is escaped or not.
    """
    if not html or not chapter_slug:
        return None

    # unescaped JSON path
    pat1 = re.compile(
        rf'"slug"\s*:\s*"{re.escape(chapter_slug)}"(?s).*?"id"\s*:\s*"({UUID_RE})"',
        re.I | re.S
    )
    m = pat1.search(html)
    if m:
        return m.group(1)

    # escaped-quote JSON path
    pat2 = re.compile(
        rf'slug\\\"\s*:\s*\\\"{re.escape(chapter_slug)}\\\"(?s).*?id\\\"\s*:\s*\\\"({UUID_RE})\\\"',
        re.I | re.S
    )
    m = pat2.search(html)
    if m:
        return m.group(1)

    return None

def _get_arc_for_ch(ch: int) -> Optional[dict]:
    for arc in TDLBKGC_ARCS:
        if arc["start"] <= ch <= arc["end"]:
            return arc
    return None

async def _scrape_paid_chapters_mistmint_from_state(session, novel_url: str, host: str):
    all_items = []
    state = _load_mistmint_state()
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    mistmint_block = HOSTING_SITE_DATA.get(host, {}).get("novels", {}) or {}

    for novel_title, details in mistmint_block.items():
        short_code = (details.get("short_code") or "").strip()
        if not short_code:
            continue

        novel_state = state.get(short_code, {
            "last_posted_chapter": 0,
            "latest_available_chapter": 0
        })
        last_posted = int(novel_state.get("last_posted_chapter", 0))
        latest_avail = int(novel_state.get("latest_available_chapter", 0))
        if latest_avail <= last_posted:
            continue

        novel_slug = details["novel_url"].rstrip("/").split("/")[-1]
        desc_html  = details.get("custom_description", "")

        # Deterministic timestamps: +1s per item
        for idx, ch in enumerate(range(last_posted + 1, latest_avail + 1), start=0):
            arc = _get_arc_for_ch(ch)
            if not arc:
                continue

            arc_num   = arc["arc_num"]
            arc_title = arc["title"]
            arc_local_index = ch - arc["start"] + 1

            volume      = f"Arc {arc_num}: {arc_title}"
            chaptername = f"Chapter {ch}"
            nameextend  = f"{arc_num}.{arc_local_index}"

            arc_slug = _slug_arc(arc_num, arc_title)
            link = f"{BASE_APP}/novels/{novel_slug}/{arc_slug}-chapter-{ch}"

            # STATE policy: always short_code-N
            guid_val = f"{short_code}-{ch}"

            pub_dt = now_utc + datetime.timedelta(seconds=idx)
            coin_amt = COIN_MANUAL_DEFAULT

            all_items.append({
                "volume":      volume,
                "chaptername": chaptername,
                "nameextend":  nameextend,
                "link":        link,
                "description": desc_html,
                "pubDate":     pub_dt,
                "guid":        guid_val,
                "coin":        coin_amt,
                "novel_title": novel_title,
                "source":      "manual",
            })

        # advance state
        novel_state["last_posted_chapter"] = latest_avail
        state[short_code] = novel_state

    _save_mistmint_state(state)
    return all_items, ""

def _canon_name(s: str) -> str:
    # "Cannibal Turtle" == "cannibalturtle" == "CANNIBAL_TURTLE"
    return re.sub(r'[\W_]+', '', (s or '').casefold())

def _iso_dt(s: str):
    try:
        d = datetime.datetime.fromisoformat((s or '').replace('Z', '+00:00'))
        return d.astimezone(datetime.timezone.utc).replace(microsecond=0)
    except Exception:
        return None

def _now_utc():
    return datetime.datetime.now(datetime.timezone.utc)
        
def _norm(s: str) -> str:
    # stronger normalization for Mistmint text bodies
    s = unescape(s or "")
    s = s.replace("\u200b", "").replace("\ufeff", "")
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", " ", s.strip())
    
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
    
def match_comment_on_homepage_by_id(novel_id: str, author: str, body_raw: str, posted_at: str):
    """
    Return (matching_comment_obj, parent_user_name) from the novel homepage thread.
    Behaves like the chapter-thread matcher: canonicalized name, tolerant timestamp,
    and (if provided) normalized body equality as a tie-breaker.
    """
    if not novel_id:
        return None, ""

    # fetch/cached payload
    if novel_id in _MISTMINT_HOME_CACHE:
        payload = _MISTMINT_HOME_CACHE[novel_id]
        diag_ok("homepage-cache-hit", novel_id=novel_id)
    else:
        url = f"https://api.mistminthaven.com/api/comments/novel/{novel_id}?skipPage=0&limit=50"
        payload = _http_get_json(url) or {}
        _MISTMINT_HOME_CACHE[novel_id] = payload
        diag_ok("homepage-fetch", novel_id=novel_id)

    want_name = _canon_name(author)
    want_dt   = _iso_dt(posted_at)
    want_body = _norm(body_raw)

    def _time_close(theirs: str, target: datetime.datetime | None) -> bool:
        if target is None:
            # if we don't have a usable target, fall back to string equality
            return (theirs or "").strip() == (posted_at or "").strip()
        dt = _iso_dt(theirs)
        return (dt is not None) and (abs((dt - target).total_seconds()) <= 300)

    def _hit(user_obj, created_at: str, content: str) -> bool:
        u = _canon_name(_user_str(user_obj))
        if u != want_name:
            return False
        if not _time_close(created_at, want_dt):
            return False
        # If we have a body, require equality after normalization to disambiguate.
        return (not want_body) or (_norm(content or "") == want_body)

    for top in (payload.get("data") or []):
        if _hit(top.get("user"), top.get("createdAt") or "", top.get("content") or ""):
            diag_ok("homepage-match-top", novel_id=novel_id, comment_id=top.get("id"))
            return top, ""
        for rep in (top.get("replies") or []):
            if _hit(rep.get("user"), rep.get("createdAt") or "", rep.get("content") or ""):
                parent_user = _user_str(top.get("user"))
                diag_ok("homepage-match-reply", novel_id=novel_id, comment_id=rep.get("id"), parent=parent_user)
                return rep, parent_user

    diag_fail("homepage-match-miss",
              novel_id=novel_id,
              author=author,
              want_ts=(posted_at or ""),
              note="try relaxed time+body match but none found")
    return None, ""

def resolve_chapter_id(novel_slug: str, chapter_slug: str) -> str:
    url = f"https://www.mistminthaven.com/novels/{novel_slug}/{chapter_slug}"
    try:
        with diag_step("slug-resolve", url=url):
            r = requests.get(url, headers=DEFAULT_HEADERS, timeout=20)
            r.raise_for_status()
            html = r.text

            # Try unescaped pattern first
            m = re.search(r'"chapterId":"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"', html, re.I)
            if not m:
                # Fallback for escaped quotes in inline JSON
                m = re.search(r'chapterId\\":\\"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\\"', html, re.I)

            if not m:
                diag_fail("slug-resolve-miss", reason="chapterId not found in page")
                raise ValueError("chapterId not found in page")

            chapter_id = m.group(1)
            diag_ok("slug-resolve-hit", chapter_id=chapter_id)
            return chapter_id
    except Exception as e:
        diag_fail("slug-resolve-error", error=str(e))
        raise


class MistmintClient:
    def __init__(self, translator_cookie: Optional[str] = None, timeout: int = 20):
        if translator_cookie is None:
            translator_cookie = _resolve_mistmint_cookie()
        self.s = requests.Session()
        self.s.headers.update(DEFAULT_HEADERS)
        self.timeout = timeout
        self.cookie = translator_cookie
        self._chapter_id_cache: Dict[Tuple[str, str], Optional[str]] = {}

    def _get(self, url: str, use_cookie: bool = False) -> requests.Response:
        headers = {}
        if use_cookie and self.cookie:
            headers["Cookie"] = self.cookie
        try:
            r = self.s.get(url, headers=headers, timeout=self.timeout, allow_redirects=True)
        except requests.Timeout:
            diag_fail("api-timeout", url=url, use_cookie=use_cookie)
            raise
        except Exception as e:
            diag_fail("api-exception", url=url, use_cookie=use_cookie, error=str(e))
            raise
    
        if r.status_code >= 500:
            diag_fail("api-5xx", url=url, code=r.status_code)
        elif r.status_code in (401, 403):
            diag_fail("api-auth", url=url, code=r.status_code, use_cookie=use_cookie)
        elif not r.ok:
            diag_fail("api-http", url=url, code=r.status_code)
        else:
            diag_ok("api-get", url=url, code=r.status_code, use_cookie=use_cookie)
        return r

    def fetch_all_comments(self) -> Dict[str, Any]:
        r = self._get(ALL_COMMENTS_URL, use_cookie=bool(self.cookie))
        r.raise_for_status()
        return r.json()

    @staticmethod
    def build_url(novel_slug: str, chapter_slug: str) -> str:
        if chapter_slug:
            return f"{BASE_APP}/novels/{novel_slug}/{chapter_slug}"
        return f"{BASE_APP}/novels/{novel_slug}"

    def get_chapter_id(self, novel_slug: str, chapter_slug: str) -> Tuple[Optional[str], bool]:
        """
        Returns (chapter_id, gated)
        gated=True if we couldn't extract chapterId anonymously (and also failed with cookie if provided)
        """
        if not chapter_slug:
            return None, False
    
        key = (novel_slug, chapter_slug)
        if key in self._chapter_id_cache:
            cid = self._chapter_id_cache[key]
            return cid, cid is None  # if None, treat as gated/unknown
    
        url = self.build_url(novel_slug, chapter_slug)
    
        # 1) try anonymous HTML (legacy "chapterId" in page)
        try:
            if 'diag_step' in globals():
                with diag_step("chapterId-anon", novel=novel_slug, chapter=chapter_slug):
                    r = self._get(url, use_cookie=False)
                    html = r.text or ""
                    m = CHAPTERID_RE.search(html)
                    if m:
                        cid = m.group(1)
                        self._chapter_id_cache[key] = cid
                        diag_ok("chapterId-anon-hit", chapter_id=cid)
                        return cid, False
                    diag_fail("chapterId-anon-miss")
            else:
                r = self._get(url, use_cookie=False)
                html = r.text or ""
                m = CHAPTERID_RE.search(html)
                if m:
                    cid = m.group(1)
                    self._chapter_id_cache[key] = cid
                    return cid, False
        except Exception:
            pass
    
        # 2) cookie HTML + smarter HTML JSON fallback + API fallback
        if self.cookie:
            if 'diag_step' in globals():
                with diag_step("chapterId-cookie", novel=novel_slug, chapter=chapter_slug):
                    r2 = self._get(url, use_cookie=True)
                    html2 = r2.text or ""
                    # 2a) old regex again
                    m2 = CHAPTERID_RE.search(html2)
                    if m2:
                        cid = m2.group(1)
                        self._chapter_id_cache[key] = cid
                        diag_ok("chapterId-cookie-hit", chapter_id=cid)
                        return cid, False
                    # 2b) new: parse Nuxt/JSON blobs
                    cid = _extract_chapter_id_from_html(html2 or "", chapter_slug)
                    if cid:
                        self._chapter_id_cache[key] = cid
                        diag_ok("chapterId-cookie-fallback-html-hit", chapter_id=cid)
                        return cid, False
            else:
                r2 = self._get(url, use_cookie=True)
                html2 = r2.text or ""
                m2 = CHAPTERID_RE.search(html2)
                if m2:
                    cid = m2.group(1)
                    self._chapter_id_cache[key] = cid
                    return cid, False
                cid = _extract_chapter_id_from_html(html2 or "", chapter_slug)
                if cid:
                    self._chapter_id_cache[key] = cid
                    return cid, False
    
        # gated or not found
        diag_fail("chapterId-not-found", novel=novel_slug, chapter=chapter_slug)
        self._chapter_id_cache[key] = None
        return None, True

    def fetch_chapter_comments(self, chapter_id: str, skip_page: int = 0, limit: int = 100) -> Dict[str, Any]:
        u = f"{BASE_API}/comments/chapter/{chapter_id}?skipPage={skip_page}&limit={limit}"
        with diag_step("thread-fetch", chapter_id=chapter_id, page=skip_page, limit=limit):
            r = self._get(u, use_cookie=bool(self.cookie))
            try:
                data = r.json()
                diag_ok("thread-json", chapter_id=chapter_id, count=len(data.get("data", [])))
                return data
            except Exception as e:
                diag_fail("thread-json-parse", chapter_id=chapter_id, error=str(e))
                raise
            
def _user_str(v: Any) -> str:
    """
    Normalize a 'user' field that might be a dict or a plain string.
    Picks displayName → username → name → (stringifies).
    """
    if isinstance(v, dict):
        return (v.get("displayName")
                or v.get("username")
                or v.get("name")
                or "").strip()
    return str(v or "").strip()
    
def _resolve_mistmint_cookie() -> str:
    # 1) direct env
    direct = os.getenv("MISTMINT_COOKIE", "").strip()
    if direct:
        return direct
    # 2) mapping indirection: token_secret stores the *env var name*
    env_name = HOSTING_SITE_DATA.get("Mistmint Haven", {}).get("token_secret", "").strip()
    if env_name:
        return os.getenv(env_name, "").strip()
    return ""

# ─── Mode helpers (paste after _resolve_mistmint_cookie) ──────────────────────

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

def extract_chapter_mistmint(value: str) -> str:
    """
    Fallback used only when we’re given a URL/URI instead of a human chapter label.
    If it's a label already, just normalize and return it.
    """
    v = (value or "").strip()
    if not v:
        return "Homepage"

    # Already a human label? Just normalize and stop.
    if not (v.lower().startswith("mm://") or v.lower().startswith("http://") or v.lower().startswith("https://")):
        return normalize_mistmint_chapter_label(v)

    # mm://novel/<novel_slug>/chapter/<chapter_slug>
    m = _MM_SCHEME.match(v)
    if m:
        chapter_slug = m.group(2).lower()
    else:
        # Try real https://www.mistminthaven.com/novels/<novel>/<chapter>
        p = urlparse(v)
        segs = [s for s in p.path.split("/") if s]
        chapter_slug = segs[-1].lower() if len(segs) >= 3 and segs[0] == "novels" else ""

    if not chapter_slug or chapter_slug in {"homepage", "comments"}:
        return "Homepage"

    # Only parse the slug (not the display label)
    m = re.search(r'(?:^|-)chapter-(?:(extra)-)?(\d+(?:\.\d+)?)\b', chapter_slug, re.I)
    if m:
        return f"Chapter {'Extra ' if m.group(1) else ''}{m.group(2)}"

    m = re.search(r'(?:^|-)extra-(\d+)\b', chapter_slug, re.I)
    if m:
        return f"Chapter Extra {m.group(1)}"

    return "Homepage"

def _find_chapter_slug_live(client: MistmintClient, novel_slug: str, ch_str: str) -> str | None:
    url = f"{BASE_APP}/novels/{novel_slug}"
    # use cookie if you have one; some listings are gated
    r = client._get(url, use_cookie=bool(client.cookie))
    if not (r and r.text):
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        p = urlparse(href)
        parts = [s for s in p.path.split("/") if s]
        if len(parts) >= 3 and parts[0] == "novels" and parts[1] == novel_slug:
            tail = parts[-1].lower()
            # allow "chapter-4" OR "…-chapter-4"
            if re.fullmatch(rf'(?:.*-)?chapter-{re.escape(str(ch_str))}', tail, flags=re.I):
                return parts[-1]  # exact tail slug
    return None

def match_comment_in_thread(thread_json: Dict[str, Any], username: str, created_at_iso: str) -> Optional[Dict[str, Any]]:
    want_name = _canon_name(username)
    want_dt = _iso_dt(created_at_iso)

    def _time_close(a: str, b: Optional[datetime.datetime]) -> bool:
        if want_dt is None:
            # if we don't have a usable target, allow string equality as a last resort
            return (a or "") == (created_at_iso or "")
        bd = _iso_dt(a)
        return (bd is not None) and (abs((bd - want_dt).total_seconds()) <= 1)

    for c in thread_json.get("data", []) or []:
        u = _canon_name(_user_str(c.get("user")))
        if u == want_name and _time_close(c.get("createdAt") or "", want_dt):
            diag_ok("comment-match", user=username, at=created_at_iso, where="top")
            return c
        for rc in (c.get("replies") or []):
            ru = _canon_name(_user_str(rc.get("user")))
            if ru == want_name and _time_close(rc.get("createdAt") or "", want_dt):
                diag_ok("comment-match", user=username, at=created_at_iso, where="reply")
                return rc
    diag_fail("comment-match-miss", user=username, at=created_at_iso, tops=len(thread_json.get("data", []) or []))
    return None

def enrich_all_comments(client: MistmintClient, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    thread_cache: Dict[str, Dict[str, Any]] = {}

    for rec in records:
        novel_slug    = rec.get("novelSlug")   or ""
        chapter_slug  = rec.get("chapterSlug") or ""
        chapter_label = rec.get("chapter") or rec.get("chapterLabel") or ""
        username      = _user_str(rec.get("user") or rec.get("username") or rec.get("displayName"))
        created_at    = rec.get("createdAt")   or ""

        novel_id = rec.get("novelId") or rec.get("novel_id") or ""
        body_raw = (rec.get("content") or rec.get("body") or rec.get("text") or rec.get("message") or "").strip()
        
        item = dict(rec)
        item["url"] = client.build_url(novel_slug, chapter_slug)
        item["chapterId"] = None
        item["gated"] = False
        item["is_reply"] = None
        item["parentId"] = None
        item["commentId"] = None

        # Resolve chapterId if we have/derive a slug
        cid, gated = (None, False)
        if chapter_slug:
            cid, gated = client.get_chapter_id(novel_slug, chapter_slug)
        else:
            _, ch_num = _mistmint_parse_chapter_label(chapter_label)
            if ch_num is not None and novel_slug:
                alt = _find_chapter_slug_live(client, novel_slug, ch_num)
                if alt:
                    chapter_slug = alt
                    item["url"] = client.build_url(novel_slug, alt)
                    cid, gated = client.get_chapter_id(novel_slug, alt)

        item["chapterId"] = cid
        item["gated"] = gated

        # If a chapter thread exists, try to match the comment and mark reply info
        if cid:
            if cid not in thread_cache:
                time.sleep(0.2)
                thread_cache[cid] = client.fetch_chapter_comments(cid, skip_page=0, limit=100)
            thread = thread_cache[cid]
            hit = match_comment_in_thread(thread, username=username, created_at_iso=created_at)
            if hit:
                item["commentId"] = hit.get("id") or hit.get("_id")
                item["is_reply"]  = bool(hit.get("parentId") or hit.get("replyToId"))
                item["parentId"]  = hit.get("parentId") or hit.get("replyToId")
        # If it's a homepage comment (no chapter slug), try to match on the homepage thread to get the UUID
        if not item.get("commentId") and not chapter_slug and novel_id:
            hit, parent_user = match_comment_on_homepage_by_id(
                novel_id=novel_id,
                author=username,
                body_raw=body_raw,
                posted_at=created_at
            )
            if hit:
                item["commentId"] = hit.get("id") or hit.get("_id")
                item["is_reply"]  = bool(hit.get("parentId") or hit.get("replyToId"))
                item["parentId"]  = hit.get("parentId") or hit.get("replyToId")
                if item["is_reply"] and parent_user:
                    item["replyToUser"] = parent_user
            
        out.append(item)
    return out
    
def cli_main():
    try:
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--print", choices=["raw","enriched","both"], default="both")
        args = parser.parse_args()

        rows = load_comments_mistmint(ALL_COMMENTS_URL)
        if args.print in ("raw","both"):
            for r in rows:
                tag = "reply" if r["reply_to"] else "top"
                print(f"[{r['posted_at']}] {r['author']} → {r['novel_title']} [{tag}]")
                print(f"   {r['description']}")
                print(f"   chapter={r['chapter']}\n")

        if args.print in ("enriched","both"):
            client = MistmintClient()
            blob = client.fetch_all_comments()
            enriched = enrich_all_comments(client, blob.get("data", []))
            for e in enriched:
                tag = "reply" if e["is_reply"] else ("top" if e["is_reply"] is False else "unknown")
                novel_name = e.get("novel") or e.get("novelTitle") or "?"
                print(f"[{e.get('createdAt','?')}] {e.get('user','?')} → {novel_name} [{tag}]")
                print(f"   {e.get('content','')}")
                print(f"   {e.get('url','')}")
                if e.get("chapterId"):
                    print(f"   chapterId={e.get('chapterId')}  commentId={e.get('commentId')} parentId={e.get('parentId')}")
                if e.get("gated"):
                    print("   gated: true (needed cookie or skip)")
                print()
    except Exception as e:
        diag_fail("fatal", error=str(e), exc_type=type(e).__name__)
        raise
    finally:
        diag_summary(save_json=True)

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

def _mistmint_headers():
    token  = os.getenv("MISTMINT_TOKEN", "").strip()
    cookie = _resolve_mistmint_cookie()
    h = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://www.mistminthaven.com",
        "Referer": "https://www.mistminthaven.com/",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    if cookie:
        h["Cookie"] = cookie
    return h

def _http_get_json(url: str, headers: dict | None = None):
    try:
        r = requests.get(url, headers=headers or _mistmint_headers(), timeout=20)
        if not r.ok:
            print(f"[mistmint] GET {url} → HTTP {r.status_code}")
            return None
        return r.json()
    except Exception as e:
        print(f"[mistmint] GET {url} failed: {e}")
        return None

# let self-replies show up if desired
ALLOW_SELF_REPLIES = True

def resolve_reply_to_on_chapter_by_id(client: MistmintClient, chapter_id: str,
                                      author: str, body_raw: str, posted_at: str) -> str:
    if not chapter_id:
        return ""
    want_author = _canon_name(author)
    want_body = _norm(body_raw)
    want_dt = _iso_dt(posted_at)

    def _name(u):
        return (u or {}).get("displayName") or (u or {}).get("username") or ""

    def _is_same(obj) -> bool:
        rep_user = _canon_name(_name(obj.get("user")))
        rep_body = _norm(obj.get("content") or "")
        if rep_user != want_author or rep_body != want_body:
            return False
        if want_dt is None:
            return True
        rep_dt = _iso_dt(obj.get("createdAt"))
        return (rep_dt is None) or abs((rep_dt - want_dt).total_seconds()) <= 300

    with diag_step("reply-resolve-chapter", chapter_id=chapter_id, author=author):
        # try first three pages just in case the comment is older
        for page in range(0, 3):
            payload = client.fetch_chapter_comments(chapter_id, skip_page=page, limit=100)
            for top in (payload.get("data") or []):
                parent_user = _name(top.get("user"))
                if _is_same(top):
                    diag_ok("reply-resolve-top", chapter_id=chapter_id, page=page)
                    return ""
                for rep in (top.get("replies") or []):
                    if _is_same(rep):
                        who = parent_user or _name(rep.get("toUser"))
                        diag_ok("reply-resolve-hit", chapter_id=chapter_id, parent=who, page=page)
                        return (who or "").strip()

        diag_fail("reply-resolve-miss", chapter_id=chapter_id, author=author)
        return ""
        
                                             
def resolve_reply_to_on_homepage_by_id(novel_id: str, author: str, body_raw: str, posted_at: str) -> str:
    if not novel_id:
        return ""

    if novel_id in _MISTMINT_HOME_CACHE:
        payload = _MISTMINT_HOME_CACHE[novel_id]
        diag_ok("homepage-cache-hit", novel_id=novel_id)
    else:
        url = f"https://api.mistminthaven.com/api/comments/novel/{novel_id}?skipPage=0&limit=50"
        payload = _http_get_json(url) or {}
        _MISTMINT_HOME_CACHE[novel_id] = payload
        diag_ok("homepage-fetch", novel_id=novel_id)

    want_author = _canon_name(author)
    want_body = _norm(body_raw)
    want_dt = _iso_dt(posted_at)

    for top in (payload.get("data") or []):
        parent_user = _user_str(top.get("user"))
        for rep in (top.get("replies") or []):
            rep_user = _canon_name(_user_str(rep.get("user")))
            rep_body = _norm(rep.get("content", ""))
            rep_dt = _iso_dt(rep.get("createdAt", ""))

            if rep_user == want_author and rep_body == want_body:
                if want_dt is None or rep_dt is None or abs((rep_dt - want_dt).total_seconds()) <= 300:
                    diag_ok("reply-resolve-homepage-hit", novel_id=novel_id, parent=parent_user)
                    return parent_user

    diag_fail("reply-resolve-homepage-miss", novel_id=novel_id, author=author)
    return ""
    
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

EXTRA_ALIASES = r'(?:extra|side\s*story|sidestory|ss|special|bonus|omake)'

# keep this helper exactly as-is (it handles "Extra", decimals, etc.)
def _mistmint_parse_chapter_label(s: str):
    s = (s or '').strip()
    if not s:
        return ('Homepage', None)

    EXTRA_ALIASES = r'(?:extra|side\s*story|sidestory|ss|special|bonus|omake)'

    m = re.match(rf'^\s*Chapter\s+{EXTRA_ALIASES}\s+(\d+)\s*$', s, re.I)
    if m: return (f'Chapter Extra {int(m.group(1))}', None)

    m = re.match(rf'^\s*{EXTRA_ALIASES}\s+(\d+)\s*$', s, re.I)
    if m: return (f'Chapter Extra {int(m.group(1))}', None)

    m = re.match(r'^\s*Chapter\s+(\d+(?:\.\d+)?)', s, re.I)
    if m:
        num = m.group(1)
        return (f'Chapter {num}', float(num) if '.' in num else int(num))

    return (s, None)

_MM_SCHEME = re.compile(r'^mm://novel/([^/]+)/chapter/([^/]+)$', re.I)

def build_comment_link_mistmint(novel_title: str, host: str, chapter_label_or_empty: str) -> str:
    label = (chapter_label_or_empty or "").strip()
    # homepage
    if not label or label.lower() == "homepage":
        details = HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(novel_title, {})
        return (details.get("novel_url") or "").rstrip("/")

    # exact slugs passed as mm://… → canonicalize to https
    m = _MM_SCHEME.match(label)
    if m:
        novel_slug, chapter_slug = m.groups()
        return MistmintClient.build_url(novel_slug, chapter_slug)

    # if a fully qualified https URL slipped through, just return it
    if label.lower().startswith(("http://", "https://")):
        return label

    # Otherwise do not guess from human text; fall back to novel homepage.
    details = HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(novel_title, {})
    return (details.get("novel_url") or "").rstrip("/")

def normalize_mistmint_chapter_label(label: str) -> str:
    # Empty → Homepage. Otherwise keep exactly what the API says.
    return (label or "").strip() or "Homepage"

# --- Mistmint comments loader (JSON recent-comments endpoint) ---------------

def load_comments_mistmint(comments_feed_url: str):
    """
    Returns list[dict] with keys:
      novel_title, chapter, author, description, reply_to, posted_at
    """
    out = []
    token  = os.getenv("MISTMINT_TOKEN", "").strip()
    cookie = os.getenv("MISTMINT_COOKIE", "").strip()

    base_headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://www.mistminthaven.com",
        "Referer": "https://www.mistminthaven.com/",
    }

    def unauth(payload_text: str, payload_json: dict | None) -> bool:
        try:
            if isinstance(payload_json, dict) and str(payload_json.get("code", "")).startswith("401"):
                return True
        except Exception:
            pass
        t = (payload_text or "").lower()
        return ("you must be logged in" in t) or ('"code":401' in t)

    def get_with(headers: dict, label: str):
        r = requests.get(comments_feed_url, headers=headers, timeout=20)
        # tiny snapshot about the HTTP attempt
        diag_snapshot(f"comments-fetch-{label}", {
            "status": r.status_code,
            "ctype": r.headers.get("content-type", "?"),
            "bytes": len(r.content)
        })
        raw = r.text
        pj = None
        try:
            pj = r.json()
        except Exception:
            pass
        return r, raw, pj

    payload = None
    raw_used = ""

    # ── FETCH PHASE ────────────────────────────────────────────────────────────
    with diag_step("comments-fetch", url=comments_feed_url, has_token=bool(token), has_cookie=bool(cookie)):
        if token:
            h1 = dict(base_headers)
            h1["Authorization"] = f"Bearer {token}"
            r, raw, pj = get_with(h1, "bearer")
            if not unauth(raw, pj):
                payload, raw_used = (pj if pj is not None else {}), raw
                diag_ok("comments-fetch-ok", mode="bearer")
            else:
                h2 = dict(base_headers)
                h2["Cookie"] = f"auth._token.local=Bearer%20{token}; auth.strategy=local"
                r, raw, pj = get_with(h2, "cookie-from-token")
                if not unauth(raw, pj):
                    payload, raw_used = (pj if pj is not None else {}), raw
                    diag_ok("comments-fetch-ok", mode="cookie-from-token")
                else:
                    diag_fail("comments-fetch-unauthorized", mode="bearer+cookie-from-token")

        if payload is None and cookie:
            h3 = dict(base_headers)
            h3["Cookie"] = cookie
            r, raw, pj = get_with(h3, "cookie-secret")
            if not unauth(raw, pj):
                payload, raw_used = (pj if pj is not None else {}), raw
                diag_ok("comments-fetch-ok", mode="cookie-secret")
            else:
                diag_fail("comments-fetch-unauthorized", mode="cookie-secret")

        if payload is None:
            diag_fail("comments-unauthorized")
            print("[mistmint] unauthorized; set MISTMINT_TOKEN or MISTMINT_COOKIE")
            return out

        # keep this snapshot light; don’t dump the whole JSON
        top_keys = list(payload)[:8] if isinstance(payload, dict) else []
        diag_snapshot("comments-raw", {"type": type(payload).__name__, "top_keys": top_keys})

    # ── ITEM EXTRACTION ───────────────────────────────────────────────────────
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
    diag_snapshot("comments-items", {"count": len(items)})

    if not items:
        preview = str(payload)
        preview = preview[:200] + ("…" if len(preview) > 200 else "")
        print(f"[mistmint] no items; top-level keys={list(payload)[:6]} sample={preview!r}")
        return out

    def pick(d, *cands, default=""):
        for k in cands:
            v = d.get(k)
            if v not in (None, ""):
                return v
        return default

    id_keys         = ("id", "_id", "commentId", "comment_id")
    parent_keys     = ("parentId", "parent_id", "inReplyTo", "in_reply_to", "replyToId", "reply_to_id")
    user_keys       = ("user", "author", "username", "name", "displayName")
    reply_user_keys = ("replyToUser", "reply_user", "replyToName", "reply_name", "parentUser", "parent_user", "toUser", "to_user")

    # Build id_to_user safely
    id_to_user = {}
    for obj in items:
        cid = pick(obj, *id_keys)
        if cid:
            id_to_user[str(cid)] = _user_str(obj.get("user") or pick(obj, *user_keys))

    flags = _mistmint_reply_flags_from_raw(raw_used or "")

    # ── ENRICHMENT PHASE ──────────────────────────────────────────────────────

    # Pre-inject mapping so enrich_all_comments can resolve homepage commentId
    mistmint_map = HOSTING_SITE_DATA.get("Mistmint Haven", {}).get("novels", {})
    for obj in items:
        title = (obj.get("novel") or obj.get("novelTitle") or obj.get("title") or "").strip()
        if not title:
            continue
        meta = mistmint_map.get(title, {})
    
        # novelId
        if not (obj.get("novelId") or obj.get("novel_id")):
            nid = meta.get("novel_id", "")
            if nid:
                obj["novelId"] = nid
    
        # novelSlug
        if not (obj.get("novelSlug") or obj.get("novel_slug")):
            base = (meta.get("novel_url") or "").rstrip("/")
            if base:
                obj["novelSlug"] = base.split("/")[-1]

    with diag_step("comments-enrich"):
        client = MistmintClient(translator_cookie=_resolve_mistmint_cookie())
        enriched = enrich_all_comments(client, items)
        diag_snapshot("comments-enriched", {"count": len(enriched)})

    def _parse_when(d):
        s = pick(d, "postedAt", "createdAt", "created_at", "date", "timestamp")
        try:
            return datetime.datetime.fromisoformat((s or "").replace("Z", "+00:00"))
        except Exception:
            return None

    for i, obj in enumerate(enriched):
        novel_title  = pick(obj, "novel", "novelTitle", "title").strip()
        author       = _user_str(obj.get("user") or pick(obj, *user_keys))
        body_raw     = (pick(obj, "content", "body", "text", "message") or "").strip()
        posted_at    = pick(obj, "postedAt", "createdAt", "created_at", "date", "timestamp")

        novel_id     = pick(obj, "novelId", "novel_id")
        novel_slug   = pick(obj, "novelSlug", "novel_slug")
        chapter_slug = pick(obj, "chapterSlug", "chapter_slug")
        chapter_lbl  = pick(obj, "chapter", "chapterLabel", "chapterTitle")

        # Fill from mappings if missing
        if not (novel_slug and novel_id):
            meta = HOSTING_SITE_DATA.get("Mistmint Haven", {}).get("novels", {}).get(novel_title, {})
            if not novel_slug:
                base = (meta.get("novel_url") or "").rstrip("/")
                if base:
                    novel_slug = base.split("/")[-1]
            if not novel_id:
                novel_id = meta.get("novel_id", "")

        # Try to discover chapter slug if we only have a human label
        if not chapter_slug and chapter_lbl and novel_slug:
            _disp, ch_num = _mistmint_parse_chapter_label(chapter_lbl)
            if ch_num is not None:
                alt = _find_chapter_slug_live(client, novel_slug, ch_num)
                if alt:
                    obj["chapterSlug"] = alt
                    chapter_slug = alt
                    diag_ok("chapter-slug-discovered", novel=novel_title, novel_slug=novel_slug, chapter_label=chapter_lbl, chapter_slug=alt)
                else:
                    diag_fail("chapter-slug-not-found", novel=novel_title, novel_slug=novel_slug, chapter_label=chapter_lbl)

        # Canonical chapter field for the feed
        if chapter_slug:
            chapter = f"mm://novel/{novel_slug}/chapter/{chapter_slug}"
        else:
            chapter = normalize_mistmint_chapter_label(chapter_lbl)

        # --- Resolve reply target (multiple fallbacks; each inner function logs) ---
        reply_to = pick(obj, *reply_user_keys)
        if not reply_to:
            pid = pick(obj, *parent_keys)
            if pid and str(pid) in id_to_user:
                reply_to = id_to_user[str(pid)]

        if not reply_to:
            chap_id_enriched = obj.get("chapterId")
            if chap_id_enriched:
                who = resolve_reply_to_on_chapter_by_id(
                    client=client,
                    chapter_id=chap_id_enriched,
                    author=author,
                    body_raw=body_raw,
                    posted_at=posted_at,
                )
                if who and (ALLOW_SELF_REPLIES or who.strip().casefold() != author.casefold()):
                    reply_to = who

        # after: try homepage resolution whenever it's a homepage comment
        is_homepage = not chapter_slug and (chapter_lbl or "") in ("", "Homepage")
        if not reply_to and is_homepage and novel_id:
            who = resolve_reply_to_on_homepage_by_id(
                novel_id=novel_id,
                author=author,
                body_raw=body_raw,
                posted_at=posted_at
            )
            if who and (ALLOW_SELF_REPLIES or who.strip().casefold() != author.casefold()):
                reply_to = who

        # adjacency heuristic last
        if not reply_to and flags and i > 0 and i-1 < len(flags) and flags[i-1]:
            prev = enriched[i-1]
            prev_author = _user_str(prev.get("user") or pick(prev, *user_keys))
            same_novel = novel_title == (pick(prev, "novel", "novelTitle", "title").strip())
            t_cur = _parse_when(obj)
            t_prev = _parse_when(prev)
            close_in_time = (t_cur and t_prev and abs((t_cur - t_prev).total_seconds()) <= 120)
            if prev_author and author and prev_author != author and same_novel and close_in_time:
                reply_to = prev_author
                diag_ok("reply-adjacency-heuristic", child=author, parent=prev_author, novel=novel_title)

        body = body_raw

        # --- Derive canonical IDs robustly (homepage-friendly) ---
        def _pick(d, *keys):
            for k in keys:
                v = d.get(k)
                if v not in (None, ""):
                    return v
            return None
        
        cid = _pick(obj, "commentId", "comment_id", "id", "_id")
        cid = str(cid).strip() if cid else ""
        
        pid = _pick(obj, "parentId", "replyToId", "inReplyTo", "in_reply_to")
        pid = str(pid).strip() if pid else None

        out.append({
            "novel_title": novel_title,
            "chapter": chapter,
            "author": author,
            "description": body,
            "reply_to": reply_to,                 # <- this is what becomes <reply_chain> later
            "posted_at": posted_at or "",

            # expose id in both styles so comments.py can pick it up
            "guid":       cid or _guid_from([novel_title, author, posted_at, body[:80]]),
            "comment_id": cid,
            "commentId":  cid,
            "id":         cid,                
            "_id":        cid,                 

            "parent_id":  pid,
            "is_reply":   bool(obj.get("is_reply") or pid),

            "novel_id":   novel_id,
            "novel_slug": novel_slug,
            "chapter_id": obj.get("chapterId"),
        })

    print(f"[mistmint] loaded {len(out)} raw comment(s)")
    diag_ok("comments-loaded", count=len(out))
    for e in out[:5]:
        print(f"[mistmint] sample guid={e.get('guid')} title={e.get('novel_title')} chap={e.get('chapter')}")
    return out

# =============================================================================
# MISTMINT STATE HELPERS (multi-novel, keyed by short_code)
# =============================================================================

def _save_mistmint_state(state):
    with open(MISTMINT_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


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
    Mistmint (API): build paid items directly from the chapters endpoint.
    Only include chapters where isFree == False.
    Fields:
      volume      -> volumeTitle
      chaptername -> "Chapter {chapterNumber}"
      nameextend  -> title (e.g., "1.2")
      link        -> https://www.mistminthaven.com/novels/<novel_slug>/<slug>
      description -> mapping.custom_description (per novel)
      pubDate     -> createdAt (UTC)
      guid        -> id
      coin        -> price
    Falls back to state-file synthetic exporter if no cookie.
    """

    _log_mistmint_mode("scrape-paid", novel_url)
    if _mistmint_mode() == "STATE":
        return await _scrape_paid_chapters_mistmint_from_state(session, novel_url, host)

    # we are in API mode here
    novel_title, details = _mistmint_find_details_by_url(host, novel_url)
    desc_html = (details.get("custom_description") or "")
    novel_slug = _mistmint_slug_from_url(novel_url)
    short_code = (details.get("short_code") or "").strip()
    api_url = f"{BASE_API}/novels/slug/{novel_slug}/chapters"
    base = f"{BASE_APP}/novels/{novel_slug}/"

    items = []
    try:
        async with session.get(api_url, headers=_mistmint_headers(), timeout=AIOHTTP_TIMEOUT) as resp:
            if resp.status != 200:
                diag_fail("mistmint-paid-scrape-http", url=api_url, code=resp.status)
                return [], ""
            payload = await resp.json()
            _gha("notice", "mistmint-paid-scrape-ok", json.dumps({
                "url": api_url,
                "status": resp.status,
                "volumes": len((payload or {}).get("data", []) or []),
                "chapters": sum(len(v.get("chapters") or []) for v in (payload or {}).get("data", []))
            })[:300])
    except Exception as e:
        diag_fail("mistmint-paid-scrape-ex", url=api_url, error=str(e))
        return [], ""

    for vol in (payload or {}).get("data", []) or []:
        vol_title = (vol.get("volumeTitle") or "").strip()
        for ch in (vol.get("chapters") or []):
            if ch.get("isFree") is True:
                continue  # skip free
            if ch.get("isHidden"):
                continue
                
            chapter_num = str(ch.get("chapterNumber") or "").strip()
            nameextend  = (ch.get("title") or "").strip()           # e.g., "1.2"
            slug_tail   = (ch.get("slug") or "").strip()
            link        = base + slug_tail if slug_tail else novel_url
            api_uuid    = (ch.get("id") or "").strip() 
            guid        = (ch.get("id") or "").strip()
            price       = str(ch.get("price") if ch.get("price") is not None else "")
            created     = (ch.get("createdAt") or "").strip()

            try:
                pub_dt = datetime.datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(datetime.timezone.utc)
            except Exception:
                pub_dt = datetime.datetime.now(datetime.timezone.utc)
                
            # API policy: always prefer real UUID; if missing (shouldn’t happen), fall back to link
            guid_val = api_uuid or link
        
            items.append({
                "volume":      vol_title,
                "chaptername": f"Chapter {chapter_num}" if chapter_num else "Chapter",
                "nameextend":  nameextend,
                "link":        link,
                "description": desc_html,
                "pubDate":     pub_dt,                                      # from createdAt
                "guid":        guid_val,                                    # <- UUID when present
                "coin":        price,
                "source":      "api",                                       # NEW: so generator can skip override
                "api_guid":    api_uuid,                                    # keep explicit for logs
            })

    # Let the caller (paid_feed_generator) handle 7-day trimming and sorting.
    return items, ""


async def novel_has_paid_update_mistmint_async(session, novel_url: str) -> bool:
    _log_mistmint_mode("has-paid-check", novel_url)

    if _mistmint_mode() == "STATE":
        block = HOSTING_SITE_DATA.get("Mistmint Haven", {}).get("novels", {})
        short_code = None
        for _title, det in block.items():
            if (det.get("novel_url") or "").rstrip("/") == (novel_url or "").rstrip("/"):
                short_code = det.get("short_code"); break
        if not short_code:
            return False
        st = _load_mistmint_state()
        entry = st.get(short_code, {"last_posted_chapter": 0, "latest_available_chapter": 0})
        return int(entry.get("latest_available_chapter", 0)) > int(entry.get("last_posted_chapter", 0))
        
    cookie = _resolve_mistmint_cookie()

    # Fallback to state if no cookie or manual mode
    if _manual_mode_on() or not cookie:
        block = HOSTING_SITE_DATA.get("Mistmint Haven", {}).get("novels", {})
        short_code = None
        for _title, det in block.items():
            if (det.get("novel_url") or "").rstrip("/") == (novel_url or "").rstrip("/"):
                short_code = det.get("short_code"); break
        if not short_code:
            return False
        st = _load_mistmint_state()
        entry = st.get(short_code, {"last_posted_chapter": 0, "latest_available_chapter": 0})
        return int(entry.get("latest_available_chapter", 0)) > int(entry.get("last_posted_chapter", 0))

    # API path
    novel_slug = _mistmint_slug_from_url(novel_url)
    url = f"{BASE_API}/novels/slug/{novel_slug}/chapters"
    try:
        async with session.get(url, headers=_mistmint_headers(), timeout=AIOHTTP_TIMEOUT) as resp:
            if resp.status != 200:
                diag_fail("mistmint-paid-check-http", url=url, code=resp.status)
                return False
            data = await resp.json()
    except Exception as e:
        diag_fail("mistmint-paid-check-ex", url=url, error=str(e))
        return False

    nonfree = []
    for vol in (data or {}).get("data", []) or []:
        for ch in (vol.get("chapters") or []):
            if ch.get("isFree") is False and not ch.get("isHidden"):
                nonfree.append(ch)
    if not nonfree:
        return False

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)

    def _dt(s):
        try:
            return datetime.datetime.fromisoformat((s or "").replace("Z","+00:00")).astimezone(datetime.timezone.utc)
        except Exception:
            return None

    # Recent if createdAt OR updatedAt within 7 days
    try_recent = any(
        (lambda ca, ua: (ca and ca >= cutoff) or (ua and ua >= cutoff))(
            _dt(ch.get("createdAt")), _dt(ch.get("updatedAt"))
        )
        for ch in nonfree
    )

    # Or delta vs state (latest paid chapterNumber > last_posted_chapter)
    block = HOSTING_SITE_DATA.get("Mistmint Haven", {}).get("novels", {})
    short_code = None
    for _title, det in block.items():
        if (det.get("novel_url") or "").rstrip("/") == (novel_url or "").rstrip("/"):
            short_code = det.get("short_code"); break
    latest_num = max(int(float(ch.get("chapterNumber") or 0)) for ch in nonfree)
    last_posted = 0
    if short_code:
        st = _load_mistmint_state()
        last_posted = int((st.get(short_code, {}) or {}).get("last_posted_chapter", 0))

    return try_recent or (latest_num > last_posted)

def split_paid_chapter_mistmint(raw_title: str):
    """
    Kept for API compatibility with Dragonholic, but Mistmint premium
    chapters are synthetic, so there's nothing real to parse.
    """
    return ("", "")

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

 # Default/generic picker used by Mistmint (and others)
def pick_comment_html_default(entry) -> str:
    content = entry.get("content")
    if isinstance(content, list) and content:
        v = content[0].get("value") or ""
        if v:
            return v
    return unescape(entry.get("description", "") or "")

if __name__ == "__main__":
    cli_main()

# =============================================================================
# DISPATCH TABLE
# =============================================================================

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

    # Comments/etc.
    "build_comment_link": build_comment_link_mistmint,
    "extract_chapter":    extract_chapter_mistmint,
    "reply_flags_from_raw": _mistmint_reply_flags_from_raw,
    "load_comments": load_comments_mistmint,
    "pick_comment_html": pick_comment_html_default,

    # passthroughs to novel_mappings
    "get_novel_details":
        lambda host, title: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(title, {}),
    "get_host_translator":
        lambda host: HOSTING_SITE_DATA.get(host, {}).get("translator", ""),
    "get_host_logo":
        lambda host: HOSTING_SITE_DATA.get(host, {}).get("host_logo", ""),
    "get_featured_image":
        lambda host, title: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(title, {}).get("featured_image", ""),
    "get_novel_discord_role":
        lambda host, title: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(title, {}).get("discord_role_id", ""),
    "get_comments_feed_url":
        lambda host: HOSTING_SITE_DATA.get(host, {}).get("comments_feed_url", ""),
    "get_nsfw_novels":
        lambda: [],
}

