#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
revenue/hosts/mistmint_haven.py

Mistmint Haven revenue adapter.

This file only:
- fetches Mistmint novel revenue data
- matches Mistmint API novels to local TOML mappings
- keeps only novels where is_paid = true in the novel TOML
- normalizes rows for revenue/report.py

It does NOT:
- calculate monthly deltas
- save state
- send Discord messages
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore


HOST_KEY = "mistmint_haven"
HOST_NAME = "Mistmint Haven"

# file path: rss-feed/revenue/hosts/mistmint_haven.py
ROOT = Path(__file__).resolve().parents[2]
HOST_TOML = ROOT / "mappings" / "hosts" / "mistmint_haven.toml"
NOVELS_DIR = ROOT / "mappings" / "novels"


def load_toml(path: Path, *, required: bool = True) -> Dict[str, Any]:
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        if required:
            raise
        return {}


def load_host_config() -> Dict[str, Any]:
    return load_toml(HOST_TOML, required=False)


def slug_from_url(url: str) -> str:
    parts = [p for p in urlparse(url or "").path.split("/") if p]

    if "novels" in parts:
        i = parts.index("novels")
        if i + 1 < len(parts):
            return parts[i + 1].strip().lower()

    if "slug" in parts:
        i = parts.index("slug")
        if i + 1 < len(parts):
            return parts[i + 1].strip().lower()

    return ""


def norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip()).casefold()


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(str(value).replace(",", "").strip()))
    except Exception:
        return default


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def fallback_short_code(slug: str, title: str) -> str:
    base = slug or title or "UNKNOWN"
    base = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_").upper()
    return base or "UNKNOWN"


def set_query_param(url: str, **params: Any) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for k, v in params.items():
        query[k] = str(v)
    return urlunparse(parsed._replace(query=urlencode(query)))


def revenue_novels_url(host_cfg: Mapping[str, Any]) -> str:
    """
    URL priority:
    1. GitHub secret/env MISTMINT_REVENUE_NOVELS_URL
    2. revenue_novels_url in mappings/hosts/mistmint_haven.toml
    3. novel_api in mappings/hosts/mistmint_haven.toml

    Your current host TOML can simply use:
      novel_api = "https://api.mistminthaven.com/api/my-novels"
    """
    url = (
        os.getenv("MISTMINT_REVENUE_NOVELS_URL", "").strip()
        or str(host_cfg.get("revenue_novels_url") or "").strip()
        or str(host_cfg.get("novel_api") or "").strip()
    )

    if not url:
        raise RuntimeError(
            "Missing Mistmint revenue URL. Add `novel_api` to "
            "mappings/hosts/mistmint_haven.toml."
        )

    return set_query_param(url, skipPage=0, limit=100)


def load_local_novel_indexes() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """
    Load local Mistmint novel TOMLs and index them by id, slug, and title.

    report.py only receives novels whose local TOML has:
      is_paid = true
    """
    by_id: Dict[str, Dict[str, Any]] = {}
    by_slug: Dict[str, Dict[str, Any]] = {}
    by_title: Dict[str, Dict[str, Any]] = {}

    if not NOVELS_DIR.exists():
        raise FileNotFoundError(f"Missing novel mappings directory: {NOVELS_DIR}")

    for path in sorted(NOVELS_DIR.glob("*.toml")):
        data = load_toml(path)
        if str(data.get("host", "")).strip() != HOST_NAME:
            continue

        title = str(data.get("title") or "").strip()
        slug = (
            slug_from_url(str(data.get("novel_url") or ""))
            or slug_from_url(str(data.get("paid_feed_url") or ""))
        )
        novel_id = str(data.get("novel_id") or "").strip().lower()

        data = dict(data)
        data["_mapping_file"] = str(path.relative_to(ROOT))
        data["_slug"] = slug
        data["_title_norm"] = norm_title(title)
        data["_novel_id_norm"] = novel_id

        if novel_id:
            by_id[novel_id] = data
        if slug:
            by_slug[slug] = data
        if title:
            by_title[norm_title(title)] = data

    return {"id": by_id, "slug": by_slug, "title": by_title}


def match_local_mapping(
    api_novel: Mapping[str, Any],
    indexes: Mapping[str, Dict[str, Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """Match API novel to local TOML: novel_id first, then slug, then title."""
    api_id = str(api_novel.get("id") or "").strip().lower()
    api_slug = str(api_novel.get("slug") or "").strip().lower()
    api_title = norm_title(str(api_novel.get("title") or ""))

    return (
        indexes["id"].get(api_id)
        or indexes["slug"].get(api_slug)
        or indexes["title"].get(api_title)
    )


def resolve_cookie(host_cfg: Mapping[str, Any]) -> str:
    """
    Prefer MISTMINT_COOKIE directly.
    Also supports:
      token_secret = "MISTMINT_COOKIE"
    in host TOML.
    """
    cookie = os.getenv("MISTMINT_COOKIE", "").strip()
    if cookie:
        return cookie

    env_name = str(host_cfg.get("token_secret") or "").strip()
    return os.getenv(env_name, "").strip() if env_name else ""


def mistmint_headers(host_cfg: Mapping[str, Any]) -> Dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36",
        "Origin": "https://www.mistminthaven.com",
        "Referer": "https://www.mistminthaven.com/trans/dashboard",
    }

    cookie = resolve_cookie(host_cfg)
    token = os.getenv("MISTMINT_TOKEN", "").strip()

    if cookie:
        headers["Cookie"] = cookie
    if token:
        headers["Authorization"] = f"Bearer {token}"

    return headers


def is_auth_error(status: int, text: str, payload: Any) -> bool:
    if status in (401, 403):
        return True

    if isinstance(payload, dict):
        code = str(payload.get("code") or payload.get("statusCode") or "")
        if code in ("401", "403"):
            return True

    low = (text or "").lower()
    return (
        "you must be logged in" in low
        or '"code":401' in low
        or '"statuscode":401' in low
    )


def fetch_json(url: str, host_cfg: Optional[Mapping[str, Any]] = None) -> Any:
    cfg = host_cfg or load_host_config()
    headers = mistmint_headers(cfg)

    if not headers.get("Cookie") and not headers.get("Authorization"):
        raise RuntimeError("Missing Mistmint auth. Set GitHub secret MISTMINT_COOKIE.")

    r = requests.get(url, headers=headers, timeout=30)
    text = r.text

    try:
        payload = r.json()
    except Exception:
        payload = None

    if is_auth_error(r.status_code, text, payload):
        raise RuntimeError("AUTH_ERROR: Mistmint unauthorized. MISTMINT_COOKIE may be expired.")

    if r.status_code // 100 != 2:
        raise RuntimeError(f"Mistmint HTTP {r.status_code}: {text[:500]}")

    if payload is None:
        raise RuntimeError(f"Mistmint returned non-JSON response: {text[:500]}")

    return payload


def fetch_my_novels(host_cfg: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    """Fetch all novels from the Mistmint my-novels endpoint."""
    cfg = host_cfg or load_host_config()
    url = revenue_novels_url(cfg)

    payload = fetch_json(url, cfg)
    data = payload.get("data", []) if isinstance(payload, dict) else []

    if not isinstance(data, list):
        raise RuntimeError("Mistmint my-novels response does not have data: list.")

    novels = [x for x in data if isinstance(x, dict)]

    # Fetch later pages if Mistmint returns more than one page.
    paging = payload.get("paging", {}) if isinstance(payload, dict) else {}
    total_pages = as_int(paging.get("totalPages"), 1) if isinstance(paging, dict) else 1

    for skip_page in range(1, max(total_pages, 1)):
        page_url = set_query_param(url, skipPage=skip_page, limit=100)
        page_payload = fetch_json(page_url, cfg)
        page_data = page_payload.get("data", []) if isinstance(page_payload, dict) else []
        if isinstance(page_data, list):
            novels.extend(x for x in page_data if isinstance(x, dict))

    return novels


def normalize_row(
    api_novel: Mapping[str, Any],
    local: Mapping[str, Any],
    host_cfg: Mapping[str, Any],
) -> Dict[str, Any]:
    api_title = str(api_novel.get("title") or "").strip()
    api_slug = str(api_novel.get("slug") or "").strip().lower()
    api_id = str(api_novel.get("id") or "").strip()

    short_code = str(local.get("short_code") or "").strip().upper()
    if not short_code:
        short_code = fallback_short_code(api_slug, api_title)

    novel_url = str(local.get("novel_url") or "").strip()
    if not novel_url and api_slug:
        novel_url = f"https://www.mistminthaven.com/novels/{api_slug}"

    return {
        "host_key": HOST_KEY,
        "host_name": str(host_cfg.get("name") or HOST_NAME).strip(),
        "host_emoji": str(host_cfg.get("host_emoji") or "").strip(),
        "state_key": f"{HOST_KEY}:{short_code}",
        "short_code": short_code,
        "title": str(local.get("title") or api_title).strip(),
        "slug": str(local.get("_slug") or api_slug or slug_from_url(novel_url)).strip().lower(),
        "novel_id": str(local.get("novel_id") or api_id).strip(),
        "novel_url": novel_url,
        "coins": as_int(api_novel.get("coins"), 0),
        "tickets": as_int(api_novel.get("membershipTicketCount"), 0),
        "is_paid": as_bool(local.get("is_paid", False)),
        "is_membership": as_bool(local.get("is_membership", False)),
        "coin_emoji": str(host_cfg.get("coin_emoji") or "").strip(),
        "ticket_emoji": str(host_cfg.get("ticket_emoji") or "").strip(),
        "latest_chapter": str(api_novel.get("latestChapter") or "").strip(),
        "total_chapters": as_int(api_novel.get("totalChapters"), 0),
        "views": as_int(api_novel.get("views"), 0),
        "is_mapped": True,
    }


def collect_revenue_rows() -> List[Dict[str, Any]]:
    """
    Main function used by revenue/report.py.

    Only returns novels whose local novel TOML has:
      is_paid = true
    """
    host_cfg = load_host_config()
    indexes = load_local_novel_indexes()
    api_novels = fetch_my_novels(host_cfg)

    rows: List[Dict[str, Any]] = []
    for api_novel in api_novels:
        local = match_local_mapping(api_novel, indexes)
        if not local:
            continue
        if not as_bool(local.get("is_paid", False)):
            continue
        rows.append(normalize_row(api_novel, local, host_cfg))

    rows.sort(key=lambda r: r["short_code"])
    return rows


def collect() -> List[Dict[str, Any]]:
    return collect_revenue_rows()


def get_revenue_rows() -> List[Dict[str, Any]]:
    return collect_revenue_rows()


def main(argv: Optional[List[str]] = None) -> int:
    try:
        rows = collect_revenue_rows()
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
