# host_utils/mistmint_haven/paid_chapters.py
from .common import *
from .client import _mistmint_headers, resolve_chapters_api_url

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
            chapter = f"Chapter {ch}"
            chaptername  = f"{arc_num}.{arc_local_index}"

            arc_slug = _slug_arc(arc_num, arc_title)
            link = f"{BASE_APP}/novels/{novel_slug}/{arc_slug}-chapter-{ch}"

            # STATE policy: always short_code-N
            guid_val = f"{short_code}-{ch}"

            pub_dt = now_utc + datetime.timedelta(seconds=idx)
            coin_amt = COIN_MANUAL_DEFAULT

            all_items.append({
                "volume":      volume,
                "chapter": chapter,
                "chaptername":  chaptername,
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
      chapter -> "Chapter {chapterNumber}"
      chaptername  -> title (e.g., "1.2")
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
    hostdata = HOSTING_SITE_DATA.get(host, {})

    details_for_api = dict(details or {})
    details_for_api.setdefault("novel_url", novel_url)

    desc_html = (details_for_api.get("custom_description") or "")
    novel_slug = _mistmint_slug_from_url(novel_url)
    short_code = (details_for_api.get("short_code") or "").strip()

    api_url = resolve_chapters_api_url(hostdata, novel_title, details_for_api)
    if not api_url:
        diag_fail("mistmint-paid-api-url-missing", novel_url=novel_url, host=host)
        return [], ""

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
            chaptername  = (ch.get("title") or "").strip()           # e.g., "1.2"
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
                "chapter": f"Chapter {chapter_num}" if chapter_num else "Chapter",
                "chaptername":  chaptername,
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
    host = "Mistmint Haven"
    hostdata = HOSTING_SITE_DATA.get(host, {})
    novel_title, details = _mistmint_find_details_by_url(host, novel_url)

    details_for_api = dict(details or {})
    details_for_api.setdefault("novel_url", novel_url)

    url = resolve_chapters_api_url(hostdata, novel_title, details_for_api)

    if not url:
        diag_fail("mistmint-paid-check-api-url-missing", novel_url=novel_url)
        return False

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

__all__ = [
    "scrape_paid_chapters_mistmint_async",
    "novel_has_paid_update_mistmint_async",
    "split_paid_chapter_mistmint",
]
