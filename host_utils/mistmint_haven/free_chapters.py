# host_utils/mistmint_haven/free_chapters.py
from .common import *
from .client import _http_get_json, _mistmint_headers, resolve_chapters_api_url
import asyncio

def load_feed_mistmint_via_api(host: str):
    """
    Mimics feedparser.parse() but uses Mistmint API instead.
    Returns an object with `.entries` just like feedparser.
    """

    entries = []

    block = HOSTING_SITE_DATA.get(host, {}).get("novels", {})
    hostdata = HOSTING_SITE_DATA.get(host, {})

    # This loader is API/novel-scoped even though it returns feed-shaped entries.
    # Gate here so completed novels are skipped before API calls.
    from feed_common import load_completion_state, should_skip_completed
    completion_state = load_completion_state()

    for novel_title, details in block.items():
        if should_skip_completed(novel_title, "free", details, state=completion_state):
            print(f"Skipping {novel_title}: free completion already exists.")
            continue

        novel_slug = _mistmint_slug_from_url(details.get("novel_url", ""))
        api_url = resolve_chapters_api_url(hostdata, novel_title, details)

        if not api_url:
            print(f"[mistmint] no chapters_api_url for {novel_title}")
            diag_fail("free-feed-api-url-missing", novel=novel_title)
            continue

        payload = _http_get_json(api_url)

        if not payload:
            print(f"[mistmint] free feed fetch failed for {novel_title}")
            diag_fail("free-feed-fetch-fail", novel=novel_title, api_url=api_url)
            continue
    
        for vol in payload.get("data", []):
            vol_title = (vol.get("volumeTitle") or "").strip()

            for ch in vol.get("chapters", []):
                if not ch.get("isFree"):
                    continue
                if ch.get("isHidden"):
                    continue

                chapter_num = str(ch.get("chapterNumber") or "").strip()
                chaptername  = (ch.get("title") or "").strip()
                slug_tail   = (ch.get("slug") or "").strip()

                link = f"{BASE_APP}/novels/{novel_slug}/{slug_tail}"

                free_at = ch.get("freeAt")
                
                if not free_at:
                    # fallback just in case (rare)
                    free_at = ch.get("createdAt")
                
                try:
                    dt = datetime.datetime.fromisoformat(free_at.replace("Z", "+00:00"))
                except Exception:
                    dt = datetime.datetime.now(datetime.timezone.utc)

                # 🔥 CRITICAL: recreate ORIGINAL TITLE FORMAT
                if vol_title:
                    full_title = f"{novel_title} — {vol_title}, Chapter {chapter_num}"
                else:
                    full_title = f"{novel_title} — Chapter {chapter_num}"

                if chaptername:
                    full_title += f" — {chaptername}"

                entry = types.SimpleNamespace(
                    title=full_title,
                    link=link,
                    id=ch.get("id") or link,
                    published_parsed=dt.timetuple(),
                    description=details.get("custom_description", "")
                )

                entries.append(entry)

    # return object like feedparser
    return types.SimpleNamespace(entries=entries)


async def _build_free_entries_for_novel_async(session, host: str, hostdata: dict, novel_title: str, details: dict):
    entries = []

    novel_slug = _mistmint_slug_from_url(details.get("novel_url", ""))
    api_url = resolve_chapters_api_url(hostdata, novel_title, details)

    if not api_url:
        print(f"[mistmint] no chapters_api_url for {novel_title}")
        diag_fail("free-feed-api-url-missing", novel=novel_title)
        return entries

    try:
        async with session.get(api_url, headers=_mistmint_headers(), timeout=AIOHTTP_TIMEOUT) as resp:
            if resp.status != 200:
                print(f"[mistmint] free feed fetch failed for {novel_title}: HTTP {resp.status}")
                diag_fail("free-feed-fetch-fail", novel=novel_title, api_url=api_url, code=resp.status)
                return entries
            payload = await resp.json()
    except Exception as exc:
        print(f"[mistmint] free feed fetch failed for {novel_title}: {exc}")
        diag_fail("free-feed-fetch-fail", novel=novel_title, api_url=api_url, error=str(exc))
        return entries

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

            link = f"{BASE_APP}/novels/{novel_slug}/{slug_tail}"

            free_at = ch.get("freeAt") or ch.get("createdAt")
            try:
                dt = datetime.datetime.fromisoformat(free_at.replace("Z", "+00:00"))
            except Exception:
                dt = datetime.datetime.now(datetime.timezone.utc)

            if vol_title:
                full_title = f"{novel_title} — {vol_title}, Chapter {chapter_num}"
            else:
                full_title = f"{novel_title} — Chapter {chapter_num}"

            if chaptername:
                full_title += f" — {chaptername}"

            entries.append(types.SimpleNamespace(
                title=full_title,
                link=link,
                id=ch.get("id") or link,
                published_parsed=dt.timetuple(),
                description=details.get("custom_description", "")
            ))

    return entries


async def load_feed_mistmint_via_api_async(session, host: str):
    """
    Async version of load_feed_mistmint_via_api(). It returns the same
    feedparser-like object, but fetches each novel's chapters API concurrently.
    """

    entries = []
    block = HOSTING_SITE_DATA.get(host, {}).get("novels", {})
    hostdata = HOSTING_SITE_DATA.get(host, {})

    from feed_common import load_completion_state, should_skip_completed
    completion_state = load_completion_state()

    tasks = []
    for novel_title, details in block.items():
        if should_skip_completed(novel_title, "free", details, state=completion_state):
            print(f"Skipping {novel_title}: free completion already exists.")
            continue

        tasks.append(asyncio.create_task(
            _build_free_entries_for_novel_async(session, host, hostdata, novel_title, details)
        ))

    if tasks:
        results = await asyncio.gather(*tasks)
        for novel_entries in results:
            entries.extend(novel_entries)

    return types.SimpleNamespace(entries=entries)

__all__ = ["load_feed_mistmint_via_api", "load_feed_mistmint_via_api_async"]
