from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlparse

import requests

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore


# File path expected: rss-feed/novelupdates/nu_weekly_readers.py
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from novel_mappings import HOSTING_SITE_DATA, get_novelupdates_url
except Exception as e:
    print("[fatal] Could not import novel_mappings.HOSTING_SITE_DATA:", e, file=sys.stderr)
    raise

try:
    from message_renderer import load_template_settings, render_message, to_discord_api_payload
except Exception as e:
    print("[fatal] Could not import message_renderer:", e, file=sys.stderr)
    raise


DISCORD_API_BASE = "https://discord.com/api/v10"

_TEMPLATE_SETTINGS = load_template_settings("nu_weekly_readers")


def _setting_str(key: str, default: str = "", *, env: str = "") -> str:
    env_value = os.environ.get(env, "").strip() if env else ""
    if env_value:
        return env_value
    value = _TEMPLATE_SETTINGS.get(key, default)
    return str(value if value is not None else default).strip()


def _setting_bool(key: str, default: bool = False, *, env: str = "") -> bool:
    raw = os.environ.get(env, "").strip() if env else ""
    if raw == "":
        raw = _TEMPLATE_SETTINGS.get(key, default)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


GLOBAL_MENTION = _setting_str("global_mention", env="GLOBAL_MENTION")

# Same target channel/thread as revenue. Kept as env because it is a secret/workflow target.
CHANNEL_DEFAULT = os.environ.get("DISCORD_MOD_CHANNEL_ID", "").strip()

EMBED_COLOR_HEX = _setting_str("embed_color", "2D3F51", env="EMBED_COLOR_HEX").lstrip("#")
NOVEL_DISCORD_MAP_URL = _setting_str("novel_discord_map_url", env="NOVEL_DISCORD_MAP_URL")
NO_DATA_TEXT = _setting_str("no_data_text", "_No data this week (no NU counts retrieved)._")
DEFAULT_ALLOW_ROLE_PINGS = _setting_bool("allow_role_pings", True, env="ALLOW_ROLE_PINGS")

DEFAULT_STATE_PATH = os.environ.get(
    "NU_STATE_PATH",
    str(ROOT / "novelupdates" / "nu_readers.json"),
)

_RLIST_RE = re.compile(
    r"On\s*<b[^>]*class=[\"']rlist[\"'][^>]*>\s*([\d,]+)\s*</b>\s*Reading Lists",
    re.I,
)

# Timestamp in embeds will use UTC so Discord localizes it per user; TZ env not needed.
DEFAULT_TZ = "UTC"

# ---------------------------- helpers ----------------------------------

def _now_tz(tz_name: str) -> dt.datetime:
    # Kept for compatibility, but we always post UTC timestamps in the embed.
    return dt.datetime.now(dt.timezone.utc)


def clean_short_code(value: Any) -> str:
    return str(value or "").strip().upper()


def normalize_role_id(value: Any) -> str:
    match = re.search(r"\d{5,}", str(value or ""))
    return match.group(0) if match else ""


def load_role_map(url: Optional[str] = None) -> Dict[str, str]:
    url = NOVEL_DISCORD_MAP_URL if url is None else str(url).strip()
    if not url:
        return {}

    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        data = tomllib.loads(r.text)
    except Exception as exc:
        print(f"[warn] could not load novel Discord map: {exc}", file=sys.stderr)
        return {}

    out: Dict[str, str] = {}
    if not isinstance(data, Mapping):
        return out

    for raw_code, raw_value in data.items():
        code = clean_short_code(raw_code)
        if not code:
            continue

        role_id = ""
        if isinstance(raw_value, Mapping):
            role_id = normalize_role_id(raw_value.get("role_id") or raw_value.get("id"))
        else:
            role_id = normalize_role_id(raw_value)

        if role_id:
            out[code] = f"<@&{role_id}>"

    return out


def _slug_from_series_url(series_url: str) -> str:
    p = urlparse(series_url)
    parts = [s for s in p.path.split("/") if s]
    slug = parts[-1] if parts else series_url
    return slug


def _novel_key(novel_title: str, nd: Dict[str, Any], series_url: str) -> str:
    # 1) explicit override wins
    sk = (nd.get("state_key") or "").strip()
    if sk:
        return sk.upper()
    # 2) default to mapping title (normalized)
    return re.sub(r"\W+", "_", str(novel_title)).strip("_").upper()


def _fetch_reading_lists_count(series_url: str, timeout: int = 30) -> Optional[int]:
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.7",
        "Connection": "close",
        "Referer": series_url,
    }

    def _try_parse(text: str) -> Optional[int]:
        m = _RLIST_RE.search(text)
        if not m:
            return None
        try:
            return int(m.group(1).replace(",", ""))
        except Exception:
            return None

    # 1) requests first
    try:
        r = requests.get(series_url, headers=headers, timeout=timeout)
        if r.status_code == 200:
            n = _try_parse(r.text)
            if n is not None:
                return n
            print(f"[warn] Pattern not found on {series_url}. Snippet: {r.text[:250]!r}")
        else:
            print(f"[warn] GET {series_url} -> HTTP {r.status_code}")
    except Exception as e:
        print(f"[warn] requests exception {series_url}: {e}")

    # 2) optional fallback if CF blocks the runner
    try:
        import cloudscraper  # pip install cloudscraper
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        r2 = scraper.get(series_url, timeout=timeout)
        if r2.status_code == 200:
            n = _try_parse(r2.text)
            if n is not None:
                return n
            print(f"[warn] cloudscraper miss {series_url}. Snippet: {r2.text[:250]!r}")
        else:
            print(f"[warn] cloudscraper GET {series_url} -> HTTP {r2.status_code}")
    except ImportError:
        print("[info] cloudscraper not installed; skipping CF fallback")
    except Exception as e:
        print(f"[warn] cloudscraper exception {series_url}: {e}")

    return None

# --------------------------- state handling -----------------------------

def _acquire_lock(lock_path: str, timeout: int = 30) -> Optional[int]:
    """Simple cross-run lock using an exclusive lock file (best-effort)."""
    start = time.time()
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.write(fd, str(os.getpid()).encode("utf-8", "ignore"))
            return fd
        except FileExistsError:
            if time.time() - start > timeout:
                print(f"[warn] lock timeout on {lock_path}; proceeding unlocked")
                return None
            time.sleep(0.5)


def _release_lock(fd: Optional[int], lock_path: str) -> None:
    try:
        if fd is not None:
            os.close(fd)
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except Exception:
        pass

# --------------------------- state handling -----------------------------

def _load_state(path: str) -> Dict[str, Any]:
   if not os.path.exists(path):
       return {}
   try:
       with open(path, "r", encoding="utf-8") as f:
           return json.load(f)
   except Exception as e:
       # keep the broken file for inspection
       try:
           os.replace(path, path + ".bad")
           print(f"[warn] {path} was invalid JSON; moved to {path}.bad ({e})")
       except Exception:
           print(f"[warn] {path} invalid JSON; could not backup ({e})")
       return {}


def _save_state(path: str, data: Dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# --------------------------- message building -----------------------------

def _format_delta(delta: Optional[int]) -> str:
    if delta is None:
        return "*first run*"
    if delta < 0:
        return f"*{delta} readers*"
    return f"*+{delta} new readers*"


def _build_description(lines: List[Tuple[str, int, Optional[int]]]) -> str:
    # lines: list of (role_mention, current_count, delta)
    parts: List[str] = []
    for role, count, delta in lines:
        role_txt = role or "(no-role)"
        row = render_message(
            "nu_weekly_readers",
            {
                "role_mention": role_txt,
                "delta_text": _format_delta(delta),
                "count": count,
            },
            variant="row",
        ).get("content", "")
        if row:
            parts.append(row)
    return "\n".join(parts)


def _embed_color_int() -> int:
    return int(EMBED_COLOR_HEX, 16)


def _build_payload(description: str) -> Dict[str, Any]:
    now_utc = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    return to_discord_api_payload(
        render_message(
            "nu_weekly_readers",
            {
                "global_mention": GLOBAL_MENTION,
                "description": description,
                "timestamp": now_utc.isoformat().replace("+00:00", "Z"),
                "embed_color": _embed_color_int(),
            },
            variant="message",
        )
    )


# -------------------------- Discord posting ----------------------------

def _send_or_edit_discord_payload(
    payload: Dict[str, Any],
    token: str,
    channel_id: str,
    message_id: Optional[str] = None,
    allow_pings: bool = False,
) -> None:
    url_base = DISCORD_API_BASE
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }

    if not allow_pings:
        payload = dict(payload)
        payload["allowed_mentions"] = {"parse": []}

    sess = requests.Session()
    try:
        if message_id:
            url = f"{url_base}/channels/{channel_id}/messages/{message_id}"
            r = sess.patch(url, headers=headers, json=payload, timeout=30)
        else:
            url = f"{url_base}/channels/{channel_id}/messages"
            r = sess.post(url, headers=headers, json=payload, timeout=30)
        if r.status_code // 100 != 2:
            print("[error] Discord API failure:", r.status_code, r.text, file=sys.stderr)
        else:
            obj = r.json()
            mid = obj.get("id")
            print(f"[ok] Discord message {'edited' if message_id else 'sent'}: id={mid}")
    finally:
        sess.close()


# ------------------------------- main ----------------------------------

def collect_targets() -> List[Tuple[str, str, str, str]]:
    """
    Return list of (key, novel_title, role_mention, series_url)
    for all novels that have `novelupdates_url`.
    """
    role_map = load_role_map()

    out: List[Tuple[str, str, str, str]] = []

    for host, cfg in (HOSTING_SITE_DATA or {}).items():
        novels = cfg.get("novels") or {}

        for novel_title, nd in novels.items():
            series_url = get_novelupdates_url(nd)
            if not series_url:
                continue

            key = _novel_key(novel_title, nd, series_url)
            short_code = clean_short_code(nd.get("short_code"))
            role = role_map.get(short_code) or f"@{short_code or 'UNKNOWN'}"

            out.append((key, novel_title, role, series_url))

    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print-only", action="store_true", help="Don't post to Discord; print report only")
    ap.add_argument("--state", help="State JSON path (default env NU_STATE_PATH or nu_readers_state.json)")
    ap.add_argument("--channel", help="Discord channel id (overrides default thread id)")
    ap.add_argument("--message", help="Discord message id to edit (overrides env)")
    args = ap.parse_args(argv)

    state_path = args.state or DEFAULT_STATE_PATH
    lock_fd = _acquire_lock(state_path + ".lock")

    targets = collect_targets()
    print(f"[info] Found {len(targets)} NU targets")
    for _, title, role, url in targets:
        print(f"[info]  • {title}  {role or '(no-role)'}  -> {url}")
    if not targets:
        print("[info] No novels with novelupdates_url found in mappings.")
        _release_lock(lock_fd, state_path + ".lock")
        return 0

    state = _load_state(state_path)
    nu = state.get("nu_readers", {}) if isinstance(state, dict) else {}
    prev_counts: Dict[str, Dict[str, Any]] = nu.get("counts", {})

    results: List[Tuple[str, int, Optional[int]]] = []  # (role_mention, current, delta)
    new_counts: Dict[str, Dict[str, Any]] = dict(prev_counts)  # copy
    had_success = False

    for key, title, role, url in targets:
        curr = _fetch_reading_lists_count(url)
        print(f"[debug] key={key} curr={curr}")

        if curr is None:
            prev_entry = prev_counts.get(key)
            if prev_entry is None:
                # first-ever run but NU failed → nothing reliable to show
                continue
            else:
                # NU failed, but we have a baseline → +0 new readers
                results.append((role, prev_entry["count"], 0))
            continue

        had_success = True

        if curr is not None:
            new_counts[key] = {
                "count": int(curr),
                "when": dt.datetime.utcnow().isoformat() + "Z"
            }

        prev_entry = prev_counts.get(key)
        print(f"[debug] key={key} prev_entry={prev_entry}")

        delta: Optional[int]
        if prev_entry is None:
            # True first run: we have no baseline yet
            delta = None
        else:
            # Always compute delta if we have a baseline
            delta = curr - int(prev_entry.get("count", 0))

        results.append((role, curr, delta))

    description = _build_description(results)
    if not description.strip():
        description = NO_DATA_TEXT
    payload = _build_payload(description)

    # Persist state (with lock)
    if not had_success:
        print("[warn] No successful NU fetches; skipping state save")
        _release_lock(lock_fd, state_path + ".lock")
        return 0

    nu["last_updated"] = dt.datetime.utcnow().isoformat() + "Z"
    nu["counts"] = new_counts
    state["nu_readers"] = nu
    _save_state(state_path, state)
    _release_lock(lock_fd, state_path + ".lock")
    print(f"[ok] State saved: {state_path}")

    # Decide to post
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()

    # Post specifically to your given thread unless overridden via --channel
    channel_id = args.channel or CHANNEL_DEFAULT
    message_id = (
        args.message
        or os.environ.get("DISCORD_NU_MESSAGE_ID", "").strip()
    )
    # Default to pinging roles unless explicitly disabled
    allow_pings = DEFAULT_ALLOW_ROLE_PINGS

    if args.print_only or not token or not channel_id:
        print("\n=== EMBED PREVIEW (dry-run) ===")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    _send_or_edit_discord_payload(payload, token, channel_id, message_id or None, allow_pings=allow_pings)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
