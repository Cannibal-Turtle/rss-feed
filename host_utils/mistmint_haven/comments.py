# host_utils/mistmint_haven/comments.py
from .common import *
from .client import MistmintClient, _http_get_json, _mistmint_headers
from bs4 import BeautifulSoup
from pathlib import Path
from urllib.parse import urlencode, parse_qsl, urlunparse
import email.utils
import xml.etree.ElementTree as ET
import asyncio
import aiohttp

# --- Config-----------------------
try:
    from config_loader import get_comments_config
except Exception:
    def get_comments_config(source: str):
        return {}

COMMENTS_SOURCE = "mistmint_haven"


def _mistmint_comments_int(key: str, default: int) -> int:
    cfg = get_comments_config(COMMENTS_SOURCE)
    try:
        return int(cfg.get(key, default))
    except Exception:
        return default


def _mistmint_comments_clamped_int(key: str, default: int, minimum: int, maximum: int) -> int:
    value = _mistmint_comments_int(key, default)
    return max(minimum, min(value, maximum))


def _comments_dashboard_limit() -> int:
    return _mistmint_comments_clamped_int("dashboard_comments_limit_default", 10, 1, 100)


def _comments_dashboard_page_scan() -> int:
    return _mistmint_comments_clamped_int("dashboard_comments_page_scan_default", 1, 1, 5)


def _comments_novel_limit() -> int:
    return _mistmint_comments_clamped_int("novel_comments_limit_default", 50, 1, 100)


def _comments_novel_page_scan() -> int:
    return _mistmint_comments_clamped_int("novel_comments_page_scan_default", 1, 1, 5)


def _comments_chapter_limit() -> int:
    return _mistmint_comments_clamped_int("chapter_comments_limit_default", 100, 1, 100)


def _comments_chapter_page_scan() -> int:
    return _mistmint_comments_clamped_int("chapter_comments_page_scan_default", 3, 1, 5)

def _append_query_params(url: str, params: dict) -> str:
    """Return url with params merged/overridden.

    Keep host TOML URLs clean, e.g. /comments/trans/all-comments, and let
    backend code attach Mistmint pagination values.
    """
    parsed = urlparse(str(url or ""))
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if value is None or value == "":
            continue
        query[str(key)] = str(value)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _local_xml_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _parse_comment_dt(value: str) -> datetime.datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    try:
        dt = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        try:
            dt = email.utils.parsedate_to_datetime(raw)
        except Exception:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def _comment_dt_key(value: str) -> int | None:
    dt = _parse_comment_dt(value)
    if dt is None:
        return None
    return int(dt.timestamp())


def _comment_identity_key(
    *,
    novel_title: str,
    chapter: str,
    author: str,
    posted_at: str,
    body: str,
):
    when = _comment_dt_key(posted_at)
    if when is None:
        return None
    return (
        str(novel_title or "").strip().casefold(),
        normalize_mistmint_chapter_label(chapter),
        _canon_name(author),
        when,
        _norm(body or ""),
    )


def _existing_reply_to_from_feed(raw: str) -> str:
    text = str(raw or "").strip()
    if text.startswith("ᯓ✿"):
        text = text.replace("ᯓ✿", "", 1).strip()
    low = text.lower()
    if low.startswith("in reply to"):
        text = text[len("in reply to"):].strip()
    return text


def _existing_mistmint_comment_items_from_xml(path: str = "aggregated_comments_feed.xml"):
    """Return previously generated Mistmint comments keyed by display identity.

    Used only as a pre-enrichment cache: if the dashboard page contains a
    comment already present in the existing RSS XML, reuse that RSS-ready row
    instead of resolving chapterId/reply chains again. Mistmint API remains the
    source of truth for which latest comments appear.
    """
    feed_path = Path(os.getenv("COMMENTS_FEED_XML", path))
    if not feed_path.exists():
        return {}, None

    try:
        root = ET.parse(feed_path).getroot()
    except Exception as e:
        diag_fail("comments-existing-xml-parse", path=str(feed_path), error=str(e))
        return {}, None

    def child_text(item, wanted: str) -> str:
        for child in list(item):
            if _local_xml_name(child.tag) == wanted:
                return (child.text or "").strip()
        return ""

    def child_attr(item, wanted: str, attr: str) -> str:
        for child in list(item):
            if _local_xml_name(child.tag) == wanted:
                return str(child.attrib.get(attr) or "").strip()
        return ""

    existing = {}
    cutoff = None

    for item in root.iter():
        if _local_xml_name(item.tag) != "item":
            continue
        if child_text(item, "host") != MISTMINT_HOST:
            continue

        novel_title = child_text(item, "title")
        chapter = child_text(item, "chapter")
        author = child_text(item, "creator")
        body = child_text(item, "description")
        posted_at = child_text(item, "pubDate")
        dt = _parse_comment_dt(posted_at)
        if dt is None:
            continue

        cutoff = dt if cutoff is None or dt > cutoff else cutoff
        key = _comment_identity_key(
            novel_title=novel_title,
            chapter=chapter,
            author=author,
            posted_at=posted_at,
            body=body,
        )
        if key is None:
            continue

        existing[key] = {
            "novel_title": novel_title,
            "chapter": chapter,
            "author": author,
            "description": body,
            "comment_image_url": child_attr(item, "commentImage", "url"),
            "reply_to": _existing_reply_to_from_feed(child_text(item, "reply_chain")),
            "posted_at": dt.isoformat(),
            "guid": child_text(item, "guid"),
            "url": child_text(item, "link"),
        }

    if existing:
        diag_ok("comments-existing-xml-cache", count=len(existing), cutoff=cutoff.isoformat() if cutoff else "")
    return existing, cutoff


def _raw_dashboard_comment_key(obj: dict, pick_func):
    novel_title = pick_func(obj, "novel", "novelTitle", "title").strip()
    author = _user_str(obj.get("user") or pick_func(obj, "author", "username", "name", "displayName"))
    body_raw = (pick_func(obj, "content", "body", "text", "message") or "").strip()
    body, _image = split_mistmint_sticker_image(body_raw)
    posted_at = pick_func(obj, "postedAt", "createdAt", "created_at", "date", "timestamp")
    chapter = normalize_mistmint_chapter_label(pick_func(obj, "chapter", "chapterLabel", "chapterTitle"))
    return _comment_identity_key(
        novel_title=novel_title,
        chapter=chapter,
        author=author,
        posted_at=posted_at,
        body=body,
    )


def _comment_created_dt(obj: dict) -> datetime.datetime | None:
    if not isinstance(obj, dict):
        return None
    for key in ("createdAt", "postedAt", "created_at", "date", "timestamp"):
        dt = _parse_comment_dt(obj.get(key))
        if dt is not None:
            return dt
    return None


def _iter_comment_page_objects(items: list):
    for top in items or []:
        if not isinstance(top, dict):
            continue
        yield top
        for rep in (top.get("replies") or []):
            if isinstance(rep, dict):
                yield rep


def _oldest_comment_dt_in_page(items: list) -> datetime.datetime | None:
    oldest = None
    for obj in _iter_comment_page_objects(items):
        dt = _comment_created_dt(obj)
        if dt is None:
            continue
        oldest = dt if oldest is None or dt < oldest else oldest
    return oldest


def _comment_page_covers_target(items: list, target_dt: datetime.datetime | None) -> bool:
    """Return True when this page appears old enough to include target_dt.

    This is a stop condition for smart paging. Page scans still have a hard
    max from config, but we do not fetch the next page when the current page
    already reaches older than the comment/cutoff timestamp we care about.
    """
    if target_dt is None:
        return False
    oldest = _oldest_comment_dt_in_page(items)
    if oldest is None:
        return False
    return oldest <= target_dt


def _merge_comment_payloads(payloads: list[dict]) -> dict:
    merged = {"data": []}
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        for item in (payload.get("data") or []):
            merged["data"].append(item)
    return merged


def _existing_mistmint_comment_cutoffs_by_novel(path: str = "aggregated_comments_feed.xml"):
    """Return latest existing Mistmint comment timestamp per novel title.

    Public novel-comment paging uses this only as a cutoff/checkpoint. The
    Mistmint API remains the source of truth.
    """
    feed_path = Path(os.getenv("COMMENTS_FEED_XML", path))
    if not feed_path.exists():
        return {}

    try:
        root = ET.parse(feed_path).getroot()
    except Exception as e:
        diag_fail("comments-existing-xml-cutoff-parse", path=str(feed_path), error=str(e))
        return {}

    def child_text(item, wanted: str) -> str:
        for child in list(item):
            if _local_xml_name(child.tag) == wanted:
                return (child.text or "").strip()
        return ""

    cutoffs = {}
    for item in root.iter():
        if _local_xml_name(item.tag) != "item":
            continue
        if child_text(item, "host") != MISTMINT_HOST:
            continue

        title = child_text(item, "title")
        dt = _parse_comment_dt(child_text(item, "pubDate"))
        if not title or dt is None:
            continue

        key = title.strip().casefold()
        prev = cutoffs.get(key)
        if prev is None or dt > prev:
            cutoffs[key] = dt

    if cutoffs:
        diag_ok("comments-existing-xml-novel-cutoffs", count=len(cutoffs))
    return cutoffs


_MISTMINT_HOME_PAGE_CACHE: dict[str, dict[int, dict]] = {}


def _fetch_homepage_comments_for_target(novel_id: str, target_dt: datetime.datetime | None = None) -> dict:
    """Fetch novel-page comments with smart paging.

    `novel_comments_page_scan_default` is the maximum number of pages allowed.
    We stop early when the current page is empty or already reaches the target
    timestamp.
    """
    if not novel_id:
        return {}

    limit = _comments_novel_limit()
    max_pages = _comments_novel_page_scan()
    pages = _MISTMINT_HOME_PAGE_CACHE.setdefault(novel_id, {})
    payloads = []

    for page in range(max_pages):
        if page not in pages:
            url = f"{BASE_API}/comments/novel/{novel_id}?skipPage={page}&limit={limit}"
            pages[page] = _http_get_json(url) or {}
            diag_ok("homepage-fetch", novel_id=novel_id, page=page)
        else:
            diag_ok("homepage-cache-hit", novel_id=novel_id, page=page)

        payload = pages[page]
        payloads.append(payload)
        page_items = payload.get("data") or []

        if not page_items:
            diag_ok("homepage-stop-empty-page", novel_id=novel_id, page=page)
            break

        if _comment_page_covers_target(page_items, target_dt):
            diag_ok("homepage-stop-time-covered", novel_id=novel_id, page=page)
            break

    merged = _merge_comment_payloads(payloads)
    _MISTMINT_HOME_CACHE[novel_id] = merged
    return merged


# --- Mistmint website sticker text -> comment image URL -----------------------
MISTMINT_STICKER_IMAGES = {
    ":shirone_banned:": "https://cdn.discordapp.com/emojis/1514344193378619392.webp?size=128&quality=lossless",
    ":shirone_cool:": "https://cdn.discordapp.com/emojis/1514344190371430562.webp?size=128&quality=lossless",
    ":shirone_flower:": "https://cdn.discordapp.com/emojis/1514344187862978611.webp?size=128&quality=lossless",
    ":shirone_girlfailure:": "https://cdn.discordapp.com/emojis/1514344185585733723.webp?size=128&quality=lossless",
    ":shirone_heart:": "https://cdn.discordapp.com/emojis/1514344183475732520.webp?size=128&quality=lossless",
    ":shirone_hi:": "https://cdn.discordapp.com/emojis/1514344180418084924.webp?size=128&quality=lossless",
    ":shirone_hmm:": "https://cdn.discordapp.com/emojis/1514344178207952946.webp?size=128&quality=lossless",
    ":shirone_lol:": "https://cdn.discordapp.com/emojis/1514344176026648646.webp?size=128&quality=lossless",
    ":shirone_pout:": "https://cdn.discordapp.com/emojis/1514344173350944949.webp?size=128&quality=lossless",
    ":shirone_sad:": "https://cdn.discordapp.com/emojis/1514344170746286160.webp?size=128&quality=lossless",
}

def split_mistmint_sticker_image(text: str):
    """
    Returns (clean_text, image_url).

    ':shirone_cool:Re-reading' -> ('Re-reading', cool_url)
    'Thanks :shirone_lol:'     -> ('Thanks', lol_url)
    ':shirone_sad:'            -> ('Sticker comment', sad_url)
    """
    clean_text = text or ""
    image_url = ""

    for sticker_code, url in MISTMINT_STICKER_IMAGES.items():
        if sticker_code in clean_text:
            image_url = url
            clean_text = clean_text.replace(sticker_code, "", 1).strip()
            break

    if image_url and not clean_text:
        clean_text = "Sticker comment"

    return clean_text, image_url

def match_comment_on_homepage_by_id(novel_id: str, author: str, body_raw: str, posted_at: str):
    """
    Return (matching_comment_obj, parent_user_name) from the novel homepage thread.
    Behaves like the chapter-thread matcher: canonicalized name, tolerant timestamp,
    and (if provided) normalized body equality as a tie-breaker.
    """
    if not novel_id:
        return None, ""

    want_name = _canon_name(author)
    want_dt   = _iso_dt(posted_at)
    want_body = _norm(body_raw)
    payload = _fetch_homepage_comments_for_target(novel_id, want_dt)

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
    thread_cache: Dict[str, Dict[int, Dict[str, Any]]] = {}

    def cached_chapter_page(chapter_id: str, page: int, limit: int) -> Dict[str, Any]:
        pages = thread_cache.setdefault(chapter_id, {})
        if page not in pages:
            time.sleep(0.2)
            pages[page] = client.fetch_chapter_comments(chapter_id, skip_page=page, limit=limit)
        return pages[page]

    def fetch_chapter_thread_for_target(chapter_id: str, username: str, created_at: str):
        limit = _comments_chapter_limit()
        max_pages = _comments_chapter_page_scan()
        target_dt = _parse_comment_dt(created_at)
        payloads = []

        for page in range(max_pages):
            payload = cached_chapter_page(chapter_id, page, limit)
            payloads.append(payload)
            page_items = payload.get("data") or []

            hit = match_comment_in_thread({"data": page_items}, username=username, created_at_iso=created_at)
            if hit:
                return _merge_comment_payloads(payloads), hit

            if not page_items:
                diag_ok("comment-match-stop-empty-page", chapter_id=chapter_id, page=page)
                break

            if _comment_page_covers_target(page_items, target_dt):
                diag_ok("comment-match-stop-time-covered", chapter_id=chapter_id, page=page)
                break

        return _merge_comment_payloads(payloads), None

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
                            
        if chapter_slug:
            item["url"] = client.build_url(novel_slug, chapter_slug)

        item["chapterId"] = cid
        item["gated"] = gated

        # If a chapter thread exists, try to match the comment and mark reply info.
        # Page scan is smart: page_scan is a max cap, and later pages are only
        # fetched while the current page has not reached the target timestamp.
        if cid:
            _thread, hit = fetch_chapter_thread_for_target(cid, username=username, created_at=created_at)
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
        # Smart scan: page_scan is a max cap, not pages always fetched.
        # Stop once the current page reaches the target timestamp.
        limit = _comments_chapter_limit()
        page_scan = _comments_chapter_page_scan()
        for page in range(page_scan):
            payload = client.fetch_chapter_comments(chapter_id, skip_page=page, limit=limit)
            page_items = payload.get("data") or []

            for top in page_items:
                parent_user = _name(top.get("user"))
                if _is_same(top):
                    diag_ok("reply-resolve-top", chapter_id=chapter_id, page=page)
                    return ""
                for rep in (top.get("replies") or []):
                    if _is_same(rep):
                        who = parent_user or _name(rep.get("toUser"))
                        diag_ok("reply-resolve-hit", chapter_id=chapter_id, parent=who, page=page)
                        return (who or "").strip()

            if not page_items:
                diag_ok("reply-resolve-stop-empty-page", chapter_id=chapter_id, page=page)
                break

            if _comment_page_covers_target(page_items, want_dt):
                diag_ok("reply-resolve-stop-time-covered", chapter_id=chapter_id, page=page)
                break

        diag_fail("reply-resolve-miss", chapter_id=chapter_id, author=author)
        return ""
        
                                             
def resolve_reply_to_on_homepage_by_id(novel_id: str, author: str, body_raw: str, posted_at: str) -> str:
    if not novel_id:
        return ""

    want_author = _canon_name(author)
    want_body = _norm(body_raw)
    want_dt = _iso_dt(posted_at)
    payload = _fetch_homepage_comments_for_target(novel_id, want_dt)

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

# --- Public/no-token Mistmint comments fallback -------------------------------

def _public_pick(d, *keys, default=""):
    for key in keys:
        value = d.get(key) if isinstance(d, dict) else None
        if value not in (None, ""):
            return value
    return default


def _public_data_list(payload):
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        for key in ("data", "items", "results", "comments", "entries"):
            value = payload.get(key)
            if isinstance(value, list):
                return value

        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("comments", "items", "results", "data", "entries"):
                value = data.get(key)
                if isinstance(value, list):
                    return value

    return []


def _public_headers():
    return {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://www.mistminthaven.com",
        "Referer": "https://www.mistminthaven.com/",
    }


def _comments_public_concurrency() -> int:
    default = _mistmint_comments_int("public_concurrency_default", 6)
    max_value = _mistmint_comments_int("public_concurrency_max", 10)

    raw = (
        os.getenv("MISTMINT_COMMENTS_PUBLIC_CONCURRENCY")
        or str(_mistmint_hostdata().get("comments_public_concurrency", "") or "")
        or str(default)
    )

    try:
        value = int(str(raw).strip())
    except Exception:
        value = default

    return max(1, min(value, max_value))


def _comments_public_timeout_seconds() -> int:
    default = _mistmint_comments_int("public_fetch_timeout_seconds", 20)

    raw = os.getenv("MISTMINT_COMMENTS_PUBLIC_TIMEOUT_SECONDS") or str(default)

    try:
        value = int(str(raw).strip())
    except Exception:
        value = default

    return max(1, value)


def _fetch_public_novel_comments(
    novel_slug: str,
    novel_id: str,
    limit: int,
    page_scan: int = 1,
    cutoff_dt: datetime.datetime | None = None,
):
    """
    Public endpoint fallback.

    The public Mistmint comments endpoint is /comments/novel/{identifier}.
    Existing code has used novel_id successfully; some API paths may also accept
    novel_slug. Try both and prefer the first response that actually has items.
    """
    candidates = []

    # Prefer novel_id because the existing homepage matcher already uses it.
    if novel_id:
        candidates.append(novel_id)

    if novel_slug and novel_slug not in candidates:
        candidates.append(novel_slug)

    first_url = ""
    first_items = []

    for ident in candidates:
        all_items = []
        first_ident_url = ""

        for page in range(page_scan):
            url = f"{BASE_API}/comments/novel/{ident}?skipPage={page}&limit={limit}"
            payload = _http_get_json(url, headers=_public_headers())

            if payload is None:
                continue

            items = _public_data_list(payload)
            diag_ok("public-comments-fetch", ident=ident, page=page, count=len(items))

            if not first_url:
                first_url = url
                first_items = items
            if not first_ident_url:
                first_ident_url = url

            all_items.extend(items)
            if not items:
                break

            if _comment_page_covers_target(items, cutoff_dt):
                diag_ok("public-comments-stop-time-covered", ident=ident, page=page)
                break

        if all_items:
            return first_ident_url, all_items

    return first_url, first_items


async def _http_get_json_async(session: aiohttp.ClientSession, url: str, headers: dict | None = None):
    try:
        async with session.get(
            url,
            headers=headers or {},
            timeout=aiohttp.ClientTimeout(total=_comments_public_timeout_seconds()),
        ) as resp:

            if resp.status // 100 != 2:
                diag_fail("public-comments-http", status=resp.status, url=url)
                return None

            try:
                return await resp.json(content_type=None)
            except Exception as e:
                diag_fail("public-comments-json", url=url, error=str(e))
                return None

    except Exception as e:
        diag_fail("public-comments-exception", url=url, error=str(e))
        return None


async def _fetch_public_novel_comments_async(
    session: aiohttp.ClientSession,
    novel_slug: str,
    novel_id: str,
    limit: int,
    page_scan: int = 1,
    cutoff_dt: datetime.datetime | None = None,
):
    """
    Async version of _fetch_public_novel_comments().

    Try novel_id first, then slug. Prefer the first response that actually has items.
    """
    candidates = []

    if novel_id:
        candidates.append(novel_id)

    if novel_slug and novel_slug not in candidates:
        candidates.append(novel_slug)

    first_url = ""
    first_items = []

    for ident in candidates:
        all_items = []
        first_ident_url = ""

        for page in range(page_scan):
            url = f"{BASE_API}/comments/novel/{ident}?skipPage={page}&limit={limit}"
            payload = await _http_get_json_async(session, url, headers=_public_headers())

            if payload is None:
                continue

            items = _public_data_list(payload)
            diag_ok("public-comments-fetch", ident=ident, page=page, count=len(items))

            if not first_url:
                first_url = url
                first_items = items
            if not first_ident_url:
                first_ident_url = url

            all_items.extend(items)
            if not items:
                break

            if _comment_page_covers_target(items, cutoff_dt):
                diag_ok("public-comments-stop-time-covered", ident=ident, page=page)
                break

        if all_items:
            return first_ident_url, all_items

    return first_url, first_items


async def _fetch_public_comments_for_novel_async(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    novel_title: str,
    meta: dict,
    limit: int,
    page_scan: int,
    cutoff_by_novel: dict | None = None,
):
    async with sem:
        novel_url = (meta.get("novel_url") or "").rstrip("/")
        novel_slug = novel_url.split("/")[-1] if novel_url else ""
        novel_id = str(meta.get("novel_id") or "").strip()

        if not novel_slug and not novel_id:
            diag_fail("public-comments-skip-no-id", novel=novel_title)
            return novel_title, novel_slug, novel_id, "", []

        cutoff_dt = None
        if cutoff_by_novel:
            cutoff_dt = cutoff_by_novel.get(str(novel_title or "").strip().casefold())

        url, items = await _fetch_public_novel_comments_async(
            session=session,
            novel_slug=novel_slug,
            novel_id=novel_id,
            limit=limit,
            page_scan=page_scan,
            cutoff_dt=cutoff_dt,
        )

        return novel_title, novel_slug, novel_id, url, items


async def _load_comments_mistmint_public_async(
    novels: dict,
    limit: int,
    page_scan: int,
    cutoff_by_novel: dict | None = None,
):
    concurrency = _comments_public_concurrency()
    sem = asyncio.Semaphore(concurrency)

    headers = _public_headers()
    timeout = aiohttp.ClientTimeout(total=60)

    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        tasks = [
            _fetch_public_comments_for_novel_async(
                session=session,
                sem=sem,
                novel_title=novel_title,
                meta=meta,
                limit=limit,
                page_scan=page_scan,
                cutoff_by_novel=cutoff_by_novel,
            )
            for novel_title, meta in novels.items()
        ]

        if not tasks:
            return []

        return await asyncio.gather(*tasks)


def _public_comment_item(
    *,
    novel_title: str,
    novel_slug: str,
    novel_id: str,
    obj: dict,
    reply_to: str = "",
    default_chapter: str = "Homepage",
):
    author = _user_str(
        obj.get("user")
        or _public_pick(obj, "author", "username", "name", "displayName")
    )

    body_raw = (
        _public_pick(obj, "content", "body", "text", "message")
        or ""
    ).strip()

    body, comment_image_url = split_mistmint_sticker_image(body_raw)

    posted_at = _public_pick(
        obj,
        "postedAt",
        "createdAt",
        "created_at",
        "date",
        "timestamp",
    )

    cid = _public_pick(obj, "commentId", "comment_id", "id", "_id")
    cid = str(cid).strip() if cid else ""

    pid = _public_pick(
        obj,
        "parentId",
        "parent_id",
        "replyToId",
        "reply_to_id",
        "inReplyTo",
        "in_reply_to",
    )
    pid = str(pid).strip() if pid else ""

    chapter_slug = _public_pick(obj, "chapterSlug", "chapter_slug")
    chapter_lbl = _public_pick(
        obj,
        "chapter",
        "chapterLabel",
        "chapterTitle",
        default=default_chapter,
    )

    chapter = normalize_mistmint_chapter_label(chapter_lbl)

    url = MistmintClient.build_url(novel_slug, chapter_slug) if novel_slug else ""

    guid = cid or _guid_from([
        "mistmint-public",
        novel_title,
        author,
        posted_at,
        body_raw[:100],
    ])

    return {
        "novel_title": novel_title,
        "chapter": chapter,
        "author": author,
        "description": body,
        "comment_image_url": comment_image_url,
        "reply_to": reply_to,
        "posted_at": posted_at or "",

        "guid": guid,
        "comment_id": cid,
        "commentId": cid,
        "id": cid,
        "_id": cid,

        "parent_id": pid,
        "is_reply": bool(reply_to or pid),

        "novel_id": novel_id,
        "novel_slug": novel_slug,
        "chapter_slug": chapter_slug,
        "url": url,
    }


def load_comments_mistmint_public(comments_api_url: str = ""):
    """
    No-token fallback.

    Loops through mapped Mistmint novels and fetches public novel comments.
    Public mode is novel-level, so this uses gentle concurrency.
    """
    out = []
    limit = _comments_novel_limit()
    page_scan = _comments_novel_page_scan()

    novels = HOSTING_SITE_DATA.get("Mistmint Haven", {}).get("novels", {}) or {}
    concurrency = _comments_public_concurrency()
    cutoff_by_novel = _existing_mistmint_comment_cutoffs_by_novel() if page_scan > 1 else {}

    with diag_step("comments-public-load", novel_count=len(novels), limit=limit, page_scan=page_scan, concurrency=concurrency):
        results = asyncio.run(_load_comments_mistmint_public_async(
            novels,
            limit,
            page_scan,
            cutoff_by_novel=cutoff_by_novel,
        ))

        for novel_title, novel_slug, novel_id, url, items in results:
            print(f"[mistmint/public] {novel_title}: {len(items)} item(s) from {url or 'no-url'}")

            for top in items:
                top_author = _user_str(top.get("user") or _public_pick(top, "author", "username", "name", "displayName"))

                out.append(_public_comment_item(
                    novel_title=novel_title,
                    novel_slug=novel_slug,
                    novel_id=novel_id,
                    obj=top,
                    reply_to="",
                    default_chapter="Homepage",
                ))

                for rep in (top.get("replies") or []):
                    out.append(_public_comment_item(
                        novel_title=novel_title,
                        novel_slug=novel_slug,
                        novel_id=novel_id,
                        obj=rep,
                        reply_to="",
                        default_chapter="Homepage",
                    ))

    diag_ok("comments-public-loaded", count=len(out))
    print(f"[mistmint/public] loaded {len(out)} public comment(s)")
    return out

# --- Mistmint comments loader (JSON recent-comments endpoint) ---------------

def load_comments_mistmint_trans(comments_api_url: str, resolved_label: str = ""):
    """
    Returns list[dict] with keys:
      novel_title, chapter, author, description, reply_to, posted_at
    """
    out = []
    request_headers = _mistmint_headers()

    def unauth(payload_text: str, payload_json: dict | None) -> bool:
        try:
            if isinstance(payload_json, dict) and str(payload_json.get("code", "")).startswith("401"):
                return True
        except Exception:
            pass
        t = (payload_text or "").lower()
        return ("you must be logged in" in t) or ('"code":401' in t)

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

    dashboard_limit = _comments_dashboard_limit()
    dashboard_page_scan = _comments_dashboard_page_scan()

    def dashboard_page_url(page: int) -> str:
        return _append_query_params(
            comments_api_url,
            {"skipPage": page, "limit": dashboard_limit, "type": "all"},
        )

    def get_with(url: str, headers: dict, label: str):
        r = requests.get(url, headers=headers, timeout=20)
        # tiny snapshot about the HTTP attempt
        diag_snapshot(f"comments-fetch-{label}", {
            "url": url,
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
    items = []

    # ── FETCH PHASE ────────────────────────────────────────────────────────────
    with diag_step(
        "comments-fetch",
        url=comments_api_url,
        dashboard_limit=dashboard_limit,
        dashboard_page_scan=dashboard_page_scan,
        has_token=bool(request_headers.get("Authorization")),
        has_cookie=bool(request_headers.get("Cookie")),
    ):
        for page in range(dashboard_page_scan):
            page_url = dashboard_page_url(page)
            r, raw, pj = get_with(page_url, request_headers, f"shared-page-{page}")
            if unauth(raw, pj):
                diag_fail("comments-fetch-unauthorized", mode="shared", page=page)
                print("[mistmint] unauthorized; set MISTMINT_TOKEN or MISTMINT_COOKIE")

                # Same behavior as before: fail loudly so upstream can alert.
                raise RuntimeError("AUTH_ERROR: Mistmint unauthorized (token invalid or expired)")

            page_payload = pj if pj is not None else {}
            if payload is None:
                payload = page_payload
            raw_used += raw or ""

            page_items = pick_list(page_payload)
            diag_ok("comments-fetch-ok", mode="shared", page=page, count=len(page_items))
            items.extend(page_items)

            # keep this snapshot light; don’t dump the whole JSON
            top_keys = list(page_payload)[:8] if isinstance(page_payload, dict) else []
            diag_snapshot("comments-raw", {"type": type(page_payload).__name__, "top_keys": top_keys, "page": page})

            if not page_items:
                break

    payload = payload if payload is not None else {}
    diag_snapshot("comments-items", {"count": len(items)})

    if not items:
        preview = str(payload)
        preview = preview[:200] + ("…" if len(preview) > 200 else "")
        print(f"[mistmint] no items; top-level keys={list(payload)[:6]} sample={preview!r}")
    
        # 🚨 mark as failure + trigger alert upstream
        diag_fail("comments-empty-response", note="possible auth failure")
    
        raise RuntimeError("AUTH_ERROR: Mistmint returned empty (likely bad token)")

    if resolved_label:
        print(f"[mistmint] comments_source={resolved_label} resolved=trans")
        diag_ok("comments-auto-resolved", resolved="trans", phase="fetched")

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

    existing_by_key, existing_cutoff = _existing_mistmint_comment_items_from_xml()
    reused_existing = []
    enrich_candidates = []

    if existing_by_key and existing_cutoff:
        cutoff_slop = existing_cutoff + datetime.timedelta(seconds=1)
        for obj in items:
            key = _raw_dashboard_comment_key(obj, pick)
            obj_dt = _parse_comment_dt(pick(obj, "postedAt", "createdAt", "created_at", "date", "timestamp"))
            if key in existing_by_key and obj_dt is not None and obj_dt <= cutoff_slop:
                reused_existing.append(existing_by_key[key])
            else:
                enrich_candidates.append(obj)
        if reused_existing:
            diag_ok(
                "comments-enrich-skip-existing",
                reused=len(reused_existing),
                candidates=len(enrich_candidates),
                cutoff=existing_cutoff.isoformat(),
            )
    else:
        enrich_candidates = items

    with diag_step("comments-enrich", candidates=len(enrich_candidates), reused=len(reused_existing)):
        client = MistmintClient(translator_cookie=_resolve_mistmint_cookie())
        enriched = enrich_all_comments(client, enrich_candidates) if enrich_candidates else []
        diag_snapshot("comments-enriched", {"count": len(enriched), "reused": len(reused_existing)})

    out.extend(reused_existing)

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
        chapter = normalize_mistmint_chapter_label(chapter_lbl)
        
        # Keep chapterSlug separately if you still need it later
        if chapter_slug:
            obj["chapterSlug"] = chapter_slug

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

        # UI-style reply resolution (Mistmint visual stacking)
        if not reply_to and bool(obj.get("is_reply")) and i > 0:
            prev = enriched[i - 1]
        
            prev_author = _user_str(prev.get("user") or pick(prev, *user_keys))
            same_novel = novel_title == (pick(prev, "novel", "novelTitle", "title").strip())
        
            if same_novel and prev_author and (ALLOW_SELF_REPLIES or prev_author != author):
                reply_to = prev_author
                diag_ok("reply-ui-style", child=author, parent=prev_author)

        body, comment_image_url = split_mistmint_sticker_image(body_raw)

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
            "comment_image_url": comment_image_url,
            "reply_to": reply_to,                 # <- this is what becomes <reply_chain> later
            "posted_at": posted_at or "",

            # expose id in both styles so comments.py can pick it up
            "guid": cid or _guid_from([novel_title, author, posted_at, body_raw[:80]]),
            "comment_id": cid,
            "commentId":  cid,
            "id":         cid,                
            "_id":        cid,                 

            "parent_id":  pid,
            "is_reply":   bool(obj.get("is_reply") or pid),

            "novel_id":   novel_id,
            "novel_slug": novel_slug,
            "chapter_id": obj.get("chapterId"),
            "chapter_slug": chapter_slug,
            "url": client.build_url(novel_slug, chapter_slug) if novel_slug and chapter_slug else "",
        })

    print(f"[mistmint] loaded {len(out)} raw comment(s)")
    diag_ok("comments-loaded", count=len(out))
    for e in out[:5]:
        print(f"[mistmint] sample guid={e.get('guid')} title={e.get('novel_title')} chap={e.get('chapter')}")
    return out


def load_comments_mistmint(comments_api_url: str):
    source = _comments_source()

    if source == "public":
        print("[mistmint] comments_source=public")
        diag_ok("comments-source", source="public")
        return load_comments_mistmint_public(comments_api_url)

    if source == "trans":
        print("[mistmint] comments_source=trans")
        diag_ok("comments-source", source="trans")
        return load_comments_mistmint_trans(comments_api_url)

    # auto mode
    print("[mistmint] comments_source=auto; trying trans first")
    diag_ok("comments-source", source="auto", first_try="trans")

    try:
        rows = load_comments_mistmint_trans(comments_api_url, resolved_label="auto")
        return rows
    except RuntimeError as e:
        msg = str(e)

        if "AUTH_ERROR" not in msg:
            raise

        diag_fail("comments-auto-public-fallback", error=msg)
        print("[mistmint] comments_source=auto resolved=public")
        print("[mistmint] trans/all-comments auth failed; falling back to public per-novel comments")
        return load_comments_mistmint_public(comments_api_url)


if __name__ == "__main__":
    cli_main()

__all__ = [
    "split_mistmint_sticker_image",
    "extract_chapter_mistmint",
    "build_comment_link_mistmint",
    "normalize_mistmint_chapter_label",
    "load_comments_mistmint",
    "load_comments_mistmint_trans",
    "load_comments_mistmint_public",
    "pick_comment_html_default",
    "_mistmint_reply_flags_from_raw",
    "cli_main",
]
