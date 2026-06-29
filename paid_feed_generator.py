import re
import datetime
import asyncio
import aiohttp
import feedparser
import PyRSS2Gen
import xml.dom.minidom
import json
import os
from xml.sax.saxutils import escape
from host_utils import get_host_utils
from feed_common import (
    chapter_fetch_concurrency,
    chapter_source_mode,
    entry_matches_chapter_type,
    fetch_parsed_feed_async,
    has_nsfw_marker,
    host_level_feed_url,
    load_completion_state,
    needs_novel_value,
    resolved_novel_feed_url,
    should_skip_completed,
    sort_feed_items,
    truthy,
)

# Import mapping functions and data from novel_mappings.py
from novel_mappings import (
    HOSTING_SITE_DATA,
    get_novel_url,
    get_featured_image,
    get_translator,
    get_host_logo,
    get_novel_short_code,
    get_nsfw_novels,
    get_novel_details
)


# ---------------- History Control ----------------
PAID_HISTORY_PATH = os.getenv("PAID_HISTORY_PATH", "paid_history.json")
USE_HISTORY = os.getenv("PAID_USE_HISTORY", "1") == "1"
NSFW_PAREN_RE = re.compile(r'\([^)]*\b(?:nsfw|r-?18|18\+|h{1,3})\b[^)]*\)', re.I)


def should_check_paid_novel(novel_title: str, details: dict, completion_state: dict) -> bool:
    if not details.get("paid_feed"):
        print(f"Skipping {novel_title}: has_paid=false or no paid_feed configured.")
        return False

    if truthy(details.get("force_paid_check", False)):
        print(f"Checking {novel_title}: force_paid_check=true.")
        return True

    if should_skip_completed(novel_title, "paid", details, state=completion_state):
        print(f"Skipping {novel_title}: paid_completion already exists.")
        return False

    return True
def load_history():
    if not USE_HISTORY: return []
    try:
        with open(PAID_HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_history(items):
    if not USE_HISTORY:
        return
    try:
        with open(PAID_HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _dt_to_iso(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).isoformat()

def _iso_to_dt(s: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))

def _paid_api_concurrency() -> int:
    return chapter_fetch_concurrency("paid", default=6)

def item_to_dict(item: PyRSS2Gen.RSSItem):
    return {
        "title": item.title,
        "link": item.link,
        "description": item.description,
        "guid": getattr(item.guid, "guid", None) if isinstance(item.guid, PyRSS2Gen.Guid) else item.guid,
        "isPermaLink": getattr(item.guid, "isPermaLink", False) if isinstance(item.guid, PyRSS2Gen.Guid) else False,
        "pubDate": _dt_to_iso(item.pubDate),
        "volume": getattr(item, "volume", ""),
        "chapter": getattr(item, "chapter", ""),
        "chaptername": getattr(item, "chaptername", ""),
        "coin": getattr(item, "coin", ""),
        "host": getattr(item, "host", ""),
        "is_nsfw": bool(getattr(item, "is_nsfw", False)),
    }

def dict_to_item(d):
    return MyRSSItem(
        title=d["title"],
        link=d["link"],
        description=d["description"],
        guid=PyRSS2Gen.Guid(d.get("guid") or d["link"], isPermaLink=d.get("isPermaLink", False)),
        pubDate=_iso_to_dt(d["pubDate"]),
        volume=d.get("volume",""),
        chapter=d.get("chapter",""),
        chaptername=d.get("chaptername",""),
        coin=d.get("coin",""),
        host=d.get("host",""),
        is_nsfw=d.get("is_nsfw", False),
    )

# ---------------- Concurrency Control ----------------
semaphore = asyncio.Semaphore(_paid_api_concurrency())

def entry_pub_date(entry):
    tt = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if tt:
        return datetime.datetime(*tt[:6], tzinfo=datetime.timezone.utc)

    return datetime.datetime.now(datetime.timezone.utc)


def build_paid_item(host, novel_title, chap):
    raw_chapter = chap["chapter"].strip()
    raw_chaptername = chap["chaptername"].strip()

    chapter = raw_chapter
    chaptername = raw_chaptername
    volume = chap.get("volume", "")

    pub_date = chap["pubDate"]
    if pub_date.tzinfo is None:
        pub_date = pub_date.replace(tzinfo=datetime.timezone.utc)

    # Case-insensitive detection for "(NSFW)", "(18+)", "(H)", "(HH)", "(HHH)"
    is_nsfw = has_nsfw_marker(
        raw_chapter,
        raw_chaptername,
        chap.get("description", ""),
        chap.get("volume", "")
    )

    return MyRSSItem(
        title=novel_title,
        link=chap["link"],
        description=chap["description"],
        guid=PyRSS2Gen.Guid(chap["guid"], isPermaLink=False),
        pubDate=pub_date,
        volume=volume,
        chapter=chapter,
        chaptername=chaptername,
        coin=chap.get("coin", ""),
        host=host,
        is_nsfw=is_nsfw,
    )


def append_paid_feed_entry_item(rss_items, host, utils, entry, *, forced_title="", forced_details=None):
    """Convert one paid feed entry into the existing paid RSS item shape.

    Host/global paid feeds match the novel from entry.title. Novel-level paid
    feeds can pass forced_title if entry.title omits the novel name.
    """

    main_title = ""
    chapter = ""
    chaptername = ""

    split_title = utils.get("split_title")
    if split_title:
        main_title, chapter, chaptername = split_title(getattr(entry, "title", "") or "")

    novel_details = get_novel_details(host, main_title) if main_title else {}
    if not novel_details and forced_title:
        main_title = forced_title
        novel_details = forced_details or get_novel_details(host, forced_title)

    if not novel_details:
        print("Skipping paid item (novel not found in mapping):", main_title or getattr(entry, "title", ""))
        return

    if not chapter:
        split_paid_title = utils.get("split_paid_title", lambda raw: (raw, ""))
        chapter, chaptername = split_paid_title(getattr(entry, "title", "") or "")

    volume = utils.get("extract_volume", lambda _t, _l: "")(
        getattr(entry, "title", "") or "",
        getattr(entry, "link", "") or "",
    )

    cleaner = utils.get("clean_description", lambda s: s)
    raw_desc = getattr(entry, "description", "") or ""
    description = cleaner(raw_desc)

    guid = getattr(entry, "id", "") or getattr(entry, "guid", "") or getattr(entry, "link", "") or chapter

    chap = {
        "volume": volume,
        "chapter": chapter,
        "chaptername": chaptername,
        "link": getattr(entry, "link", "") or "",
        "description": description,
        "pubDate": entry_pub_date(entry),
        "guid": guid,
        "coin": str(getattr(entry, "coin", "") or getattr(entry, "price", "") or ""),
    }

    rss_items.append(build_paid_item(host, main_title, chap))


def process_host_paid_feed(host, feed_url):
    utils = get_host_utils(host)
    parsed_feed = feedparser.parse(feed_url)
    items = []

    for entry in parsed_feed.entries:
        if not entry_matches_chapter_type(utils, entry, "paid"):
            continue
        append_paid_feed_entry_item(items, host, utils, entry)

    return items


def process_novel_paid_feed(host, novel_title, details, feed_url):
    utils = get_host_utils(host)
    parsed_feed = feedparser.parse(feed_url)
    items = []

    for entry in parsed_feed.entries:
        if not entry_matches_chapter_type(utils, entry, "paid"):
            continue
        append_paid_feed_entry_item(
            items,
            host,
            utils,
            entry,
            forced_title=novel_title,
            forced_details=details,
        )

    return items


async def process_novel_paid_feed_async(session, host, novel_title, details, feed_url):
    utils = get_host_utils(host)
    parsed_feed = await fetch_parsed_feed_async(
        session,
        feed_url,
        semaphore=semaphore,
        label="Paid feed",
    )
    items = []

    for entry in parsed_feed.entries:
        if not entry_matches_chapter_type(utils, entry, "paid"):
            continue
        append_paid_feed_entry_item(
            items,
            host,
            utils,
            entry,
            forced_title=novel_title,
            forced_details=details,
        )

    return items


async def process_novel(session, host, novel_title):
    async with semaphore:
        novel_url = get_novel_url(novel_title, host)
        print(f"Scraping: {novel_url}")
        utils = get_host_utils(host)

        # Host-agnostic: if the host exposes a cheap update check, use it.
        # Hosts can opt out when their "check" would hit the same expensive
        # source as the real scrape. Mistmint API mode does this because both
        # paths call /api/novels/slug/{slug}/chapters.
        skip_update_precheck = utils.get("skip_paid_update_precheck", False)
        if callable(skip_update_precheck):
            try:
                skip_update_precheck = bool(skip_update_precheck())
            except Exception:
                skip_update_precheck = False

        update_checker = utils.get("novel_has_paid_update_async")
        if not skip_update_precheck and callable(update_checker):
            try:
                has = await update_checker(session, novel_url)
                if not has:
                    print(f"Skipping {novel_title}: no recent paid update found.")
                    return []
            except Exception:
                # If a host-specific check fails, fall back to scraping attempt.
                pass

        paid_chapters, _main_desc = await utils["scrape_paid_chapters_async"](session, novel_url, host)
        return [build_paid_item(host, novel_title, chap) for chap in (paid_chapters or [])]

class MyRSSItem(PyRSS2Gen.RSSItem):
    def __init__(self, *args, volume="", chapter="", chaptername="", coin="", host="", is_nsfw=None, **kwargs):
        self.volume      = volume
        self.chapter = chapter
        self.chaptername  = chaptername
        self.coin        = coin
        self.host        = host
        self.is_nsfw     = is_nsfw
        super().__init__(*args, **kwargs)

    def writexml(self, writer, indent="", addindent="", newl=""):
        writer.write(indent + "  <item>" + newl)
        writer.write(indent + "    <title>%s</title>" % escape(self.title) + newl)
        writer.write(indent + "    <volume>%s</volume>" % escape(self.volume) + newl)
        writer.write(indent + "    <chapter>%s</chapter>" % escape(self.chapter) + newl)

        formatted_chaptername = self.chaptername.strip()
        writer.write(indent + "    <chaptername>%s</chaptername>" % escape(formatted_chaptername) + newl)

        writer.write(indent + "    <link>%s</link>" % escape(self.link) + newl)
        writer.write(indent + "    <description><![CDATA[%s]]></description>" % self.description + newl)

        nsfw_list = get_nsfw_novels()
        is_nsfw = bool(self.is_nsfw) or (self.title in nsfw_list)
        writer.write(indent + "    <category>%s</category>" % ("NSFW" if is_nsfw else "SFW") + newl)

        translator = get_translator(self.host, self.title)
        writer.write(indent + "    <translator>%s</translator>" % escape(translator) + newl)

        short_code = get_novel_short_code(self.title, self.host)
        writer.write(indent + "    <short_code>%s</short_code>" % escape(short_code) + newl)

        writer.write(indent + '    <featuredImage url="%s"/>' % escape(get_featured_image(self.title, self.host)) + newl)
        if self.coin:
            writer.write(indent + "    <coin>%s</coin>" % escape(str(self.coin)) + newl)

        writer.write(indent + "    <pubDate>%s</pubDate>" %
                     self.pubDate.strftime("%a, %d %b %Y %H:%M:%S +0000") + newl)

        writer.write(indent + "    <host>%s</host>" % escape(self.host) + newl)
        writer.write(indent + '    <hostLogo url="%s"/>' % escape(get_host_logo(self.host)) + newl)

        writer.write(indent + "    <guid isPermaLink=\"%s\">%s</guid>" %
                     (str(self.guid.isPermaLink).lower(), self.guid.guid) + newl)
        writer.write(indent + "  </item>" + newl)

class CustomRSS2(PyRSS2Gen.RSS2):
    def writexml(self, writer, indent="", addindent="", newl=""):
        writer.write('<?xml version="1.0" encoding="utf-8"?>' + newl)
        writer.write(
            '<rss xmlns:content="http://purl.org/rss/1.0/modules/content/" '
            'xmlns:wfw="http://wellformedweb.org/CommentAPI/" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:atom="http://www.w3.org/2005/Atom" '
            'xmlns:sy="http://purl.org/rss/1.0/modules/syndication/" '
            'xmlns:slash="http://purl.org/rss/1.0/modules/slash/" '
            'xmlns:webfeeds="http://www.webfeeds.org/rss/1.0" '
            'xmlns:georss="http://www.georss.org/georss" '
            'xmlns:geo="http://www.w3.org/2003/01/geo/wgs84_pos#" '
            'version="2.0">' + newl
        )
        writer.write(indent + "<channel>" + newl)
        writer.write(indent + addindent + "<title>%s</title>" % escape(self.title) + newl)
        writer.write(indent + addindent + "<link>%s</link>" % escape(self.link) + newl)
        writer.write(indent + addindent + "<description>%s</description>" % escape(self.description) + newl)
        if hasattr(self, 'language') and self.language:
            writer.write(indent + addindent + "<language>%s</language>" % escape(self.language) + newl)
        if hasattr(self, 'lastBuildDate') and self.lastBuildDate:
            writer.write(indent + addindent + "<lastBuildDate>%s</lastBuildDate>" %
                         self.lastBuildDate.strftime("%a, %d %b %Y %H:%M:%S +0000") + newl)
        if hasattr(self, 'docs') and self.docs:
            writer.write(indent + addindent + "<docs>%s</docs>" % escape(self.docs) + newl)
        if hasattr(self, 'generator') and self.generator:
            writer.write(indent + addindent + "<generator>%s</generator>" % escape(self.generator) + newl)
        if hasattr(self, 'ttl') and self.ttl is not None:
            writer.write(indent + addindent + "<ttl>%s</ttl>" % escape(str(self.ttl)) + newl)

        for item in self.items:
            item.writexml(writer, indent + addindent, addindent, newl)

        writer.write(indent + "</channel>" + newl)
        writer.write("</rss>" + newl)

async def main_async():
    # 1) scrape fresh items
    scraped = []
    completion_state = load_completion_state()

    async with aiohttp.ClientSession() as session:
        tasks = []

        for host, data in HOSTING_SITE_DATA.items():
            mode = chapter_source_mode(host, "paid")

            # Feed source, host/global scope: fetch once, match title after.
            # No completion gate here; the feed itself is the source of current entries.
            if mode == "feed":
                host_feed_url = host_level_feed_url(host, "paid")
                if host_feed_url and not needs_novel_value(host_feed_url):
                    scraped.extend(process_host_paid_feed(host, host_feed_url))
                    continue

                # Feed source, novel scope: loop novels and gate before fetching.
                any_novel_feed = False
                for novel_title, details in data.get("novels", {}).items():
                    feed_url = resolved_novel_feed_url(host, novel_title, details, "paid")
                    if not feed_url:
                        continue

                    any_novel_feed = True
                    if not details.get("paid_feed"):
                        print(f"Skipping {novel_title}: has_paid=false or no paid_feed configured.")
                        continue

                    if should_skip_completed(novel_title, "paid", details, state=completion_state):
                        print(f"Skipping {novel_title}: paid_completion already exists.")
                        continue

                    tasks.append(
                        asyncio.create_task(
                            process_novel_paid_feed_async(session, host, novel_title, details, feed_url)
                        )
                    )

                if not any_novel_feed:
                    print(f"No paid feed source defined for host: {host}")
                continue

            # API/source handled per novel.
            for novel_title, details in data.get("novels", {}).items():
                if not should_check_paid_novel(novel_title, details, completion_state):
                    continue

                tasks.append(asyncio.create_task(process_novel(session, host, novel_title)))

        if tasks:
            results = await asyncio.gather(*tasks)
            for items in results:
                scraped.extend(items)

    # 2) load previous history
    old_items = [dict_to_item(x) for x in load_history()]

    # 3) merge & de-dupe by GUID (new wins)
    merged = {}
    def key_for(it):
        return getattr(it.guid, "guid", None) if isinstance(it.guid, PyRSS2Gen.Guid) else it.guid or it.link

    for it in old_items:
        merged[key_for(it)] = it
    for it in scraped:
        merged[key_for(it)] = it

    # 4) keep last 7 days, sort, cap
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    seven_days_ago = now_utc - datetime.timedelta(days=7)
    kept = [it for it in merged.values() if it.pubDate >= seven_days_ago]

    sort_feed_items(kept)

    kept = kept[:200]

    # 5) save history back
    save_history([item_to_dict(it) for it in kept])

    # 6) publish RSS
    feed = CustomRSS2(
        title="Aggregated Paid Chapters Feed",
        link="https://github.com/cannibal-turtle/",
        description="Aggregated RSS feed for paid chapters across mapped novels.",
        lastBuildDate=now_utc,
        items=kept
    )

    output_file = "paid_chapters_feed.xml"
    with open(output_file, "w", encoding="utf-8") as f:
        feed.writexml(f, indent="  ", addindent="  ", newl="\n")

    with open(output_file, "r", encoding="utf-8") as f:
        xml_content = f.read()
    dom = xml.dom.minidom.parseString(xml_content)
    pretty = "\n".join([line for line in dom.toprettyxml(indent="  ").splitlines() if line.strip()])
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(pretty)

    print(f"Modified feed generated with {len(kept)} items.")
    print(f"Output written to {output_file}")

if __name__ == "__main__":
    asyncio.run(main_async())