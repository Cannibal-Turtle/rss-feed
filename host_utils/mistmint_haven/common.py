# host_utils/mistmint_haven/common.py
# Shared Mistmint helpers: mode readers, diagnostics, state, and parsing.

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
import types

from novel_mappings import HOSTING_SITE_DATA


# ================= MODE CONFIG =================
def _mistmint_hostdata():
    return HOSTING_SITE_DATA.get("Mistmint Haven", {})


def _free_chapters_source():
    """
    From mappings/hosts/mistmint_haven.toml:
      free_chapters_source = "feed" or "api"
    """
    return str(_mistmint_hostdata().get("free_chapters_source", "feed")).strip().lower()


def _paid_chapters_source():
    """
    From mappings/hosts/mistmint_haven.toml:
      paid_chapters_source = "api" or "feed"
    """
    return str(_mistmint_hostdata().get("paid_chapters_source", "api")).strip().lower()


def _chapter_mode():
    """
    From mappings/hosts/mistmint_haven.toml:
      chapter_mode = "auto" or "manual"
    """
    return str(_mistmint_hostdata().get("chapter_mode", "auto")).strip().lower()


def _comments_source():
    """
    From mappings/hosts/mistmint_haven.toml:

    comments_source = "trans"   # tokened /comments/trans/all-comments
    comments_source = "public"  # no-token public novel comments fallback
    comments_source = "auto"    # try trans first, fall back to public on auth failure
    """
    value = str(_mistmint_hostdata().get("comments_source", "trans")).strip().lower()
    return value if value in {"trans", "public", "auto"} else "trans"


def _use_api_feed():
    return _free_chapters_source() == "api"


def _manual_mode_on():
    return _chapter_mode() == "manual"


os.environ["MISTMINT_FORCE_STATE"] = "1" if _manual_mode_on() else "0"
# ==============================================

print(
    f"[MODE] Free = {_free_chapters_source().upper()} | "
    f"Paid source = {_paid_chapters_source().upper()} | "
    f"Paid mode = {'MANUAL' if _manual_mode_on() else 'AUTO'} | "
    f"Comments = {_comments_source().upper()}"
)

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

BASE_APP = "https://www.mistminthaven.com"
BASE_API = "https://api.mistminthaven.com/api"
ALL_COMMENTS_URL = f"{BASE_API}/comments/trans/all-comments"

UUID_RE = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'


def _mistmint_mode() -> str:
    # Manual forces state mode. Otherwise, try API first.
    # Cookie is optional: if one exists, API requests will send it;
    # if not, API requests should still be attempted.
    return "STATE" if _manual_mode_on() else "API"

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
        chapter = f"Chapter {after.strip()}"
    else:
        # "Chapter 13"
        chapter = middle.strip()

    return novel_title, chapter, subtitle



            
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



def _save_mistmint_state(state):
    with open(MISTMINT_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def chapter_num(chapter: str):
    s = (chapter or '').lower()

    # Extras → very large rank so they come after normal chapters
    m = re.search(r'chapter\s+extra\s+(\d+)', s)
    if not m:
        m = re.search(r'\bextra\s+(\d+)', s)
    if m:
        return (10**9, int(m.group(1)))  # extras at the end

    # Normal numeric (supports decimals like 12.5)
    nums = re.findall(r"\d+(?:\.\d+)?", chapter)
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

# Export private helpers too so feature modules can use a safe internal star import.
__all__ = [name for name in globals() if not name.startswith("__")]
