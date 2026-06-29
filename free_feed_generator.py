import datetime
import asyncio
import aiohttp
import feedparser
import PyRSS2Gen
import xml.dom.minidom
import re
from xml.sax.saxutils import escape

from host_utils import get_host_utils
from feed_common import (
    chapter_fetch_concurrency,
    chapter_source_mode,
    chapter_source_uses_api,
    chapter_source_uses_feed,
    entry_matches_chapter_type,
    feed_looks_capped_at_current_batch,
    fetch_parsed_feed_async,
    has_nsfw_marker,
    host_level_feed_url,
    load_completion_state,
    needs_novel_value,
    resolved_novel_feed_url,
    should_skip_completed,
    sort_feed_items,
)

# Import mapping functions and data from novel_mappings.py
from novel_mappings import (
    HOSTING_SITE_DATA,
    get_featured_image,
    get_translator,
    get_host_logo,
    get_novel_details,
    get_novel_short_code,
    get_nsfw_novels,
)

def compact_cdata(xml_str):
    """
    Finds <description><![CDATA[ ... ]]></description> sections and replaces
    newlines and extra whitespace inside the CDATA with a single space.
    Not currently used in final write because we want pretty multiline desc,
    but keeping it around is fine.
    """
    pattern = re.compile(r'(<description><!\[CDATA\[)(.*?)(\]\]></description>)', re.DOTALL)
    def repl(match):
        start, cdata, end = match.groups()
        compact = re.sub(r'\s+', ' ', cdata.strip())
        return f"{start}{compact}{end}"
    return pattern.sub(repl, xml_str)

class MyRSSItem(PyRSS2Gen.RSSItem):
    def __init__(self, *args, volume="", chapter="", chaptername="", host="", is_nsfw=None, **kwargs):
        self.volume = volume
        self.chapter = chapter
        self.chaptername = chaptername
        self.host = host
        self.is_nsfw = is_nsfw
        super().__init__(*args, **kwargs)
    
    def writexml(self, writer, indent="", addindent="", newl=""):
        writer.write(indent + "  <item>" + newl)

        # <title> is the novel title, not chapter
        writer.write(indent + "    <title>%s</title>" % escape(self.title) + newl)

        writer.write(indent + "    <volume>%s</volume>" % escape(self.volume) + newl)
        writer.write(indent + "    <chapter>%s</chapter>" % escape(self.chapter) + newl)

        chaptername = self.chaptername.strip()
        writer.write(indent + "    <chaptername>%s</chaptername>" % escape(chaptername) + newl)

        writer.write(indent + "    <link>%s</link>" % escape(self.link) + newl)

        # description goes in CDATA
        writer.write(indent + "    <description><![CDATA[%s]]></description>" % self.description + newl)
        
        # ── category: per-chapter detection OR whole-novel mapping
        nsfw_list = get_nsfw_novels()
        is_nsfw = bool(self.is_nsfw) or (self.title in nsfw_list)
        writer.write(indent + "    <category>%s</category>" % ("NSFW" if is_nsfw else "SFW") + newl)
        
        translator = get_translator(self.host, self.title)
        writer.write(indent + "    <translator>%s</translator>" % escape(translator) + newl)
        
        short_code = get_novel_short_code(self.title, self.host)
        writer.write(indent + "    <short_code>%s</short_code>" % escape(short_code) + newl)
        
        writer.write(indent + '    <featuredImage url="%s"/>' % escape(get_featured_image(self.title, self.host)) + newl)
        
        writer.write(
            indent + "    <pubDate>%s</pubDate>" %
            self.pubDate.strftime("%a, %d %b %Y %H:%M:%S +0000") + newl
        )
        
        writer.write(indent + "    <host>%s</host>" % escape(self.host) + newl)
        writer.write(indent + '    <hostLogo url="%s"/>' % escape(get_host_logo(self.host)) + newl)
        
        writer.write(
            indent + '    <guid isPermaLink="%s">%s</guid>' %
            (str(self.guid.isPermaLink).lower(), self.guid.guid) + newl
        )

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
            writer.write(
                indent + addindent + "<lastBuildDate>%s</lastBuildDate>" %
                self.lastBuildDate.strftime("%a, %d %b %Y %H:%M:%S +0000") + newl
            )
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


def entry_pub_date(entry):
    tt = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if tt:
        return datetime.datetime(*tt[:6], tzinfo=datetime.timezone.utc)

    # very rare: some feeds omit dates — fall back to "now" so we don't crash
    return datetime.datetime.now(datetime.timezone.utc)


def append_free_entry_item(rss_items, host, utils, entry, *, forced_title="", forced_details=None):
    """Convert one source entry into the existing free RSS item shape.

    forced_title is used only for novel-level feeds where the source may omit
    the novel name from entry.title. Host/global feeds still match by title.
    """

    main_title, chapter, chaptername = utils["split_title"](entry.title)

    # Make sure this novel is one YOU actually mapped.
    novel_details = get_novel_details(host, main_title)
    if not novel_details and forced_title:
        main_title = forced_title
        novel_details = forced_details or get_novel_details(host, forced_title)

    if not novel_details:
        # Skip other translators' stuff from the same site.
        print("Skipping item (novel not found in mapping):", main_title)
        return

    # volume
    volume = utils.get("extract_volume", lambda _t, _l: "")(entry.title, entry.link)

    # description (prefer custom, else cleaned RSS)
    entry_title = getattr(entry, "title", "") or ""
    raw_desc = getattr(entry, "description", "") or ""
    cleaner = utils.get("clean_description", lambda s: s)
    cleaned_desc = cleaner(raw_desc)
    desc_override = novel_details.get("custom_description")
    final_description = desc_override if desc_override else cleaned_desc

    # pubDate: take it exactly from the RSS/source entry (no overrides here)
    pub_date = entry_pub_date(entry)

    # Case-insensitive detection for "(NSFW)", "(18+)", "(H)", "(HH)", "(HHH)"
    is_nsfw = has_nsfw_marker(
        chapter,
        chaptername,
        entry_title,
        raw_desc
    )

    # Build RSS item object
    item = MyRSSItem(
        title=main_title,
        link=entry.link,  # could also be get_novel_url(main_title, host) if you ever want series root link
        description=final_description,
        guid=PyRSS2Gen.Guid(getattr(entry, "id", "") or entry.link, isPermaLink=False),
        pubDate=pub_date,
        volume=volume,
        chapter=chapter,
        chaptername=chaptername,
        host=host,
        is_nsfw=is_nsfw,
    )
    rss_items.append(item)


def build_free_item(host, novel_title, details, chap):
    """Convert one API chapter dict into the existing free RSS item shape.

    Feed entries are handled by append_free_entry_item(). API chapters should not
    need to pretend to be feedparser entries.
    """

    details = details or get_novel_details(host, novel_title) or {}

    raw_chapter = str(chap.get("chapter", "") or "").strip()
    raw_chaptername = str(chap.get("chaptername", "") or "").strip()
    volume = str(chap.get("volume", "") or "").strip()

    description = str(
        chap.get("description")
        or details.get("custom_description")
        or ""
    )

    pub_date = chap.get("pubDate") or chap.get("published") or chap.get("updated")
    if isinstance(pub_date, str):
        try:
            pub_date = datetime.datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
        except Exception:
            pub_date = None
    if not isinstance(pub_date, datetime.datetime):
        pub_date = datetime.datetime.now(datetime.timezone.utc)
    if pub_date.tzinfo is None:
        pub_date = pub_date.replace(tzinfo=datetime.timezone.utc)

    link = str(chap.get("link", "") or "").strip()
    guid = str(chap.get("guid") or chap.get("id") or link or f"{host}:{novel_title}:{raw_chapter}:{raw_chaptername}")

    is_nsfw = bool(chap.get("is_nsfw")) or has_nsfw_marker(
        raw_chapter,
        raw_chaptername,
        description,
        volume,
    )

    return MyRSSItem(
        title=novel_title,
        link=link,
        description=description,
        guid=PyRSS2Gen.Guid(guid, isPermaLink=False),
        pubDate=pub_date,
        volume=volume,
        chapter=raw_chapter,
        chaptername=raw_chaptername,
        host=host,
        is_nsfw=is_nsfw,
    )


def _free_fetch_concurrency() -> int:
    return chapter_fetch_concurrency("free", default=6)


free_fetch_semaphore = asyncio.Semaphore(_free_fetch_concurrency())


async def fetch_feed_async(session, feed_url):
    return await fetch_parsed_feed_async(
        session,
        feed_url,
        semaphore=free_fetch_semaphore,
        label="Free feed",
    )


def build_host_free_items_from_parsed_feed(host, parsed_feed):
    utils = get_host_utils(host)
    items = []

    for entry in parsed_feed.entries:
        if not entry_matches_chapter_type(utils, entry, "free"):
            continue
        append_free_entry_item(items, host, utils, entry)

    return items


def process_host_free_feed(host, feed_url):
    parsed_feed = feedparser.parse(feed_url)
    return build_host_free_items_from_parsed_feed(host, parsed_feed)


def _free_item_dedupe_key(item):
    guid_obj = getattr(item, "guid", None)
    guid = getattr(guid_obj, "guid", "") or ""
    link = getattr(item, "link", "") or ""
    return guid.strip() or link.strip()


def dedupe_free_items(items):
    merged = {}

    for item in items:
        key = _free_item_dedupe_key(item)
        if not key:
            key = f"{item.host}:{item.title}:{item.volume}:{item.chapter}:{item.chaptername}:{item.link}"

        existing = merged.get(key)
        if existing is None or item.pubDate > existing.pubDate:
            merged[key] = item

    return list(merged.values())


async def process_novel_free_feed(session, host, novel_title, details, feed_url):
    utils = get_host_utils(host)
    parsed_feed = await fetch_feed_async(session, feed_url)
    items = []

    for entry in parsed_feed.entries:
        if not entry_matches_chapter_type(utils, entry, "free"):
            continue
        append_free_entry_item(
            items,
            host,
            utils,
            entry,
            forced_title=novel_title,
            forced_details=details,
        )

    return items


async def process_free_api_novel(session, host, novel_title, details):
    """Fetch one novel's free chapters through a real API scraper hook."""

    utils = get_host_utils(host)
    scraper = utils.get("scrape_free_chapters_async")
    if not scraper:
        return []

    async with free_fetch_semaphore:
        try:
            chapters = await scraper(session, host, novel_title, details)
        except Exception as exc:
            print(f"Free API scrape failed for {host} / {novel_title}: {exc}")
            return []

    return [build_free_item(host, novel_title, details, chap) for chap in (chapters or [])]


def should_check_free_novel(novel_title, details, completion_state):
    if should_skip_completed(novel_title, "free", details, state=completion_state):
        print(f"Skipping {novel_title}: free completion already exists.")
        return False

    return True


def add_novel_free_feed_tasks(tasks, session, host, data, completion_state):
    """Queue novel-scoped free feed fetches for one host.

    This keeps feed scheduling separate from source-mode control flow, so
    main_async only decides *when* to use feed/API and these helpers decide
    *which mapped novels* should be checked.
    """

    any_novel_feed = False

    for novel_title, details in data.get("novels", {}).items():
        feed_url = resolved_novel_feed_url(host, novel_title, details, "free")
        if not feed_url:
            continue

        any_novel_feed = True

        if completion_state is None:
            completion_state = load_completion_state()

        if not should_check_free_novel(novel_title, details, completion_state):
            continue

        tasks.append(
            asyncio.create_task(
                process_novel_free_feed(session, host, novel_title, details, feed_url)
            )
        )

    return any_novel_feed, completion_state


def add_free_api_tasks(tasks, session, host, data, completion_state):
    """Queue free API fetches for one host.

    Plain api mode and feed_api fallback both call this same helper, so the
    fallback uses the exact same mapped-novel API path as normal api mode.
    """

    utils = get_host_utils(host)
    scrape_free_chapters_async = utils.get("scrape_free_chapters_async")

    if not scrape_free_chapters_async:
        print(f"No scrape_free_chapters_async defined for host: {host}")
        return completion_state

    if completion_state is None:
        completion_state = load_completion_state()

    any_api_novel = False

    for novel_title, details in data.get("novels", {}).items():
        any_api_novel = True

        if not should_check_free_novel(novel_title, details, completion_state):
            continue

        tasks.append(
            asyncio.create_task(
                process_free_api_novel(session, host, novel_title, details)
            )
        )

    if not any_api_novel:
        print(f"No free API novels defined for host: {host}")

    return completion_state


async def main_async():
    rss_items = []

    # Loaded only if we actually hit a novel-scoped source.
    completion_state = None

    connector = aiohttp.TCPConnector(limit=_free_fetch_concurrency())
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []

        # Loop over each host defined in the mapping.
        for host, data in HOSTING_SITE_DATA.items():
            mode = chapter_source_mode(host, "free")
            api_scan_reason = ""

            # Feed modes: plain feed OR feed_api hybrid.
            # feed_api only falls back to API when a host/global feed looks capped.
            if chapter_source_uses_feed(mode):
                host_feed_url = host_level_feed_url(host, "free")

                if host_feed_url and not needs_novel_value(host_feed_url):
                    parsed_feed = feedparser.parse(host_feed_url)
                    rss_items.extend(build_host_free_items_from_parsed_feed(host, parsed_feed))

                    if mode == "feed_api" and feed_looks_capped_at_current_batch(parsed_feed):
                        api_scan_reason = (
                            f"{host} feed shows {len(parsed_feed.entries)} visible entries "
                            "and the oldest visible row is still in the current batch"
                        )
                else:
                    any_novel_feed, completion_state = add_novel_free_feed_tasks(
                        tasks,
                        session,
                        host,
                        data,
                        completion_state,
                    )

                    if not any_novel_feed:
                        print(f"No free feed source defined for host: {host}")
                        if mode == "feed_api":
                            api_scan_reason = f"{host} has no usable free feed source"

                if not chapter_source_uses_api(mode):
                    continue

                if not api_scan_reason:
                    continue

                print(f"[free-feed] {api_scan_reason}; scanning mapped novels through API fallback.")

            # API modes: plain api OR feed_api fallback.
            # Both paths queue API fetches through the same helper.
            if chapter_source_uses_api(mode):
                completion_state = add_free_api_tasks(
                    tasks,
                    session,
                    host,
                    data,
                    completion_state,
                )
                continue

        if tasks:
            results = await asyncio.gather(*tasks)
            for items in results:
                rss_items.extend(items)

    # feed_api can surface the same chapter from both feed and API.
    # Dedupe before sorting so downstream repos see one item per GUID/link.
    rss_items = dedupe_free_items(rss_items)

    # Sort all items newest-first.
    # Tie-breaker: host/title alphabetical, then chapter number.
    sort_feed_items(rss_items)

    now_utc = datetime.datetime.now(datetime.timezone.utc)

    seven_days_ago = now_utc - datetime.timedelta(days=7)

    rss_items = [item for item in rss_items if item.pubDate >= seven_days_ago]

    rss_items = rss_items[:200]

    # Build the aggregated feed.
    new_feed = CustomRSS2(
        title="Aggregated Free Chapters Feed",
        link="https://github.com/cannibal-turtle/",
        description="Aggregated RSS feed for free chapters across all hosting sites.",
        lastBuildDate=datetime.datetime.now(datetime.timezone.utc),
        items=rss_items
    )

    output_file = "free_chapters_feed.xml"

    # Write raw
    with open(output_file, "w", encoding="utf-8") as f:
        new_feed.writexml(f, indent="  ", addindent="  ", newl="\n")


    # Pretty-print pass (keeps line breaks in <description> because we DO NOT compact here)
    with open(output_file, "r", encoding="utf-8") as f:
        xml_content = f.read()
    dom = xml.dom.minidom.parseString(xml_content)
    pretty_xml = "\n".join(
        [line for line in dom.toprettyxml(indent="  ").splitlines() if line.strip()]
    )

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(pretty_xml)

    print("Modified feed generated with", len(rss_items), "items.")
    print("Output written to", output_file)

if __name__ == "__main__":
    asyncio.run(main_async())