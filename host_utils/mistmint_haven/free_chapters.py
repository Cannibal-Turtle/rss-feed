# host_utils/mistmint_haven/free_chapters.py
from .common import *
from .client import _http_get_json, _mistmint_headers, resolve_chapters_api_url

async def _build_free_chapters_for_novel_async(session, host: str, hostdata: dict, novel_title: str, details: dict):
    """Return real free chapter dicts for one Mistmint novel.

    This is the API-shaped data used by free_feed_generator.py.
    """

    chapters = []

    novel_slug = _mistmint_slug_from_url(details.get("novel_url", ""))
    api_url = resolve_chapters_api_url(hostdata, novel_title, details)

    if not api_url:
        print(f"[mistmint] no chapters_api_url for {novel_title}")
        diag_fail("free-feed-api-url-missing", novel=novel_title)
        return chapters

    try:
        async with session.get(api_url, headers=_mistmint_headers(), timeout=AIOHTTP_TIMEOUT) as resp:
            if resp.status != 200:
                print(f"[mistmint] free feed fetch failed for {novel_title}: HTTP {resp.status}")
                diag_fail("free-feed-fetch-fail", novel=novel_title, api_url=api_url, code=resp.status)
                return chapters
            payload = await resp.json()
    except Exception as exc:
        print(f"[mistmint] free feed fetch failed for {novel_title}: {exc}")
        diag_fail("free-feed-fetch-fail", novel=novel_title, api_url=api_url, error=str(exc))
        return chapters

    for vol in payload.get("data", []):
        vol_title = (vol.get("volumeTitle") or "").strip()

        for ch in vol.get("chapters", []):
            if not ch.get("isFree"):
                continue
            if ch.get("isHidden"):
                continue

            chapter_num = str(ch.get("chapterNumber") or "").strip()
            chaptername = (ch.get("title") or "").strip()
            slug_tail = (ch.get("slug") or "").strip()

            link = f"{BASE_APP}/novels/{novel_slug}/{slug_tail}" if slug_tail else f"{BASE_APP}/novels/{novel_slug}"

            free_at = ch.get("freeAt") or ch.get("createdAt")
            try:
                dt = datetime.datetime.fromisoformat(free_at.replace("Z", "+00:00"))
            except Exception:
                dt = datetime.datetime.now(datetime.timezone.utc)

            chapters.append({
                "volume": vol_title,
                "chapter": f"Chapter {chapter_num}" if chapter_num else "",
                "chaptername": chaptername,
                "link": link,
                "description": details.get("custom_description", ""),
                "pubDate": dt,
                "guid": ch.get("id") or link,
            })

    return chapters


async def scrape_free_chapters_mistmint_async(session, host: str, novel_title: str, details: dict):
    hostdata = HOSTING_SITE_DATA.get(host, {})
    return await _build_free_chapters_for_novel_async(session, host, hostdata, novel_title, details)


__all__ = ["scrape_free_chapters_mistmint_async"]
