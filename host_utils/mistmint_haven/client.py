# host_utils/mistmint_haven/client.py
# Mistmint API/HTTP helpers and client class.

import os
import re
from typing import Any, Dict, Optional, Tuple

import requests

from .common import (
    ALL_COMMENTS_URL,
    BASE_API,
    BASE_APP,
    DEFAULT_HEADERS,
    UUID_RE,
    _mistmint_slug_from_url,
    _resolve_mistmint_cookie,
    diag_fail,
    diag_ok,
    diag_step,
)

CHAPTERID_RE = re.compile(
    rf'(?:"|\\")chapterId(?:"|\\")\s*:\s*(?:"|\\")({UUID_RE})(?:"|\\")',
    re.I,
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
        rf'"slug"\s*:\s*"{re.escape(chapter_slug)}".*?"id"\s*:\s*"({UUID_RE})"',
        re.I | re.S
    )
    m = pat1.search(html)
    if m:
        return m.group(1)

    # escaped-quote JSON path
    pat2 = re.compile(
        rf'slug\\\"\s*:\s*\\\"{re.escape(chapter_slug)}\\\".*?id\\\"\s*:\s*\\\"({UUID_RE})\\\"',
        re.I | re.S
    )
    m = pat2.search(html)
    if m:
        return m.group(1)

    return None

def resolve_chapters_api_url(hostdata, novel_title, novel):
    """
    Resolve Mistmint chapter API URL.

    Order:
    1. novel-level chapters_api_url override
    2. host-level chapters_api_url template
    3. fallback built from novel_url slug

    Supports:
    - {slug}
    - {novel_url_slug}
    """
    novel_url = (novel.get("novel_url") or "").rstrip("/")
    slug = _mistmint_slug_from_url(novel_url)

    raw_url = (
        novel.get("chapters_api_url")
        or hostdata.get("chapters_api_url")
        or ""
    ).strip()

    if raw_url:
        if "{slug}" in raw_url:
            if not slug:
                return ""
            return raw_url.replace("{slug}", slug)

        if "{novel_url_slug}" in raw_url:
            if not slug:
                return ""
            return raw_url.replace("{novel_url_slug}", slug)

        return raw_url

    if not slug:
        return ""

    return f"{BASE_API}/novels/slug/{slug}/chapters"

def _mistmint_base_headers() -> Dict[str, str]:
    return {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://www.mistminthaven.com",
        "Referer": "https://www.mistminthaven.com/",
    }


def _mistmint_auth_values() -> Tuple[str, str]:
    """
    Central Mistmint auth lookup.

    MISTMINT_TOKEN is the bearer token.
    MISTMINT_COOKIE can be set directly, or resolved via the host-level
    token_secret indirection handled by _resolve_mistmint_cookie().
    """
    token = os.getenv("MISTMINT_TOKEN", "").strip()
    cookie = _resolve_mistmint_cookie()
    return token, cookie


def _mistmint_headers(
    *,
    token: Optional[str] = None,
    cookie: Optional[str] = None,
) -> Dict[str, str]:
    """
    Shared Mistmint request headers.

    This is the same token/cookie header builder used by dashboard-style API
    calls. Passing cookie lets MistmintClient reuse an explicitly supplied
    cookie while still attaching MISTMINT_TOKEN when it exists.
    """
    env_token, env_cookie = _mistmint_auth_values()
    token = env_token if token is None else str(token or "").strip()
    cookie = env_cookie if cookie is None else str(cookie or "").strip()

    h = _mistmint_base_headers()

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
        token, resolved_cookie = _mistmint_auth_values()

        if translator_cookie is None:
            translator_cookie = resolved_cookie

        self.s = requests.Session()
        self.s.headers.update(_mistmint_base_headers())
        self.timeout = timeout
        self.token = token
        self.cookie = str(translator_cookie or "").strip()
        self.has_auth = bool(self.token or self.cookie)
        self._chapter_id_cache: Dict[Tuple[str, str], Optional[str]] = {}

    def _auth_headers(self) -> Dict[str, str]:
        return _mistmint_headers(token=self.token, cookie=self.cookie)

    def _get(self, url: str, use_cookie: bool = False) -> requests.Response:
        # keep use_cookie as the public/internal switch name, but it now means
        # "use Mistmint auth headers" (bearer token and/or cookie).
        headers = self._auth_headers() if use_cookie else _mistmint_base_headers()
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
        r = self._get(ALL_COMMENTS_URL, use_cookie=self.has_auth)
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
    
        # 2) authenticated HTML + smarter HTML JSON fallback + API fallback
        if self.has_auth:
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
            r = self._get(u, use_cookie=self.has_auth)
            try:
                data = r.json()
                diag_ok("thread-json", chapter_id=chapter_id, count=len(data.get("data", [])))
                return data
            except Exception as e:
                diag_fail("thread-json-parse", chapter_id=chapter_id, error=str(e))
                raise

__all__ = [
    "MistmintClient",
    "resolve_chapters_api_url",
    "resolve_chapter_id",
    "_mistmint_base_headers",
    "_mistmint_auth_values",
    "_mistmint_headers",
    "_http_get_json",
]
