import re
import datetime
import asyncio
import aiohttp
import PyRSS2Gen
import xml.dom.minidom
import json
import os
from xml.sax.saxutils import escape
from host_utils import get_host_utils

# Import mapping functions and data from novel_mappings.py
from novel_mappings import (
    HOSTING_SITE_DATA,
    get_novel_url,
    get_featured_image,
    get_host_translator,
    get_host_logo,
    get_novel_discord_role,
    get_nsfw_novels,
    get_coin_emoji
)

# ---------------- History Control ----------------
PAID_HISTORY_PATH = os.getenv("PAID_HISTORY_PATH", "paid_history.json")
USE_HISTORY = os.getenv("PAID_USE_HISTORY", "1") == "1"
NSFW_PAREN_RE = re.compile(r'\([^)]*\b(?:nsfw|r-?18|18\+|h{1,3})\b[^)]*\)', re.I)

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

def has_nsfw_marker(*texts: str) -> bool:
    for t in texts:
        if t and NSFW_PAREN_RE.search(t):
            return True
    return False

def item_to_dict(item: PyRSS2Gen.RSSItem):
    return {
        "title": item.title,
        "link": item.link,
        "description": item.description,
        "guid": getattr(item.guid, "guid", None) if isinstance(item.guid, PyRSS2Gen.Guid) else item.guid,
        "isPermaLink": getattr(item.guid, "isPermaLink", False) if isinstance(item.guid, PyRSS2Gen.Guid) else False,
        "pubDate": _dt_to_iso(item.pubDate),
        "volume": getattr(item, "volume", ""),
        "chaptername": getattr(item, "chaptername", ""),
        "nameextend": getattr(item, "nameextend", ""),
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
        chaptername=d.get("chaptername",""),
        nameextend=d.get("nameextend",""),
        coin=d.get("coin",""),
        host=d.get("host",""),
        is_nsfw=d.get("is_nsfw", False),
    )

# ---------------- Concurrency Control ----------------
semaphore = asyncio.Semaphore(100)

def normalize_date(dt):
    return dt.replace(microsecond=0)

async def process_novel(session, host, novel_title):
    async with semaphore:
        novel_url = get_novel_url(novel_title, host)
        print(f"Scraping: {novel_url}")
        utils = get_host_utils(host)
        
        # Host-agnostic: if the host exposes a cheap update check, use it.
        if "novel_has_paid_update_async" in utils:
            try:
                has = await utils["novel_has_paid_update_async"](session, novel_url)
                if not has:
                    print(f"Skipping {novel_title}: no recent paid update found.")
                    return []
            except Exception:
                # If a host-specific check fails, fall back to scraping attempt.
                pass
        
        paid_chapters, _main_desc = await utils["scrape_paid_chapters_async"](session, novel_url, host)
        items = []
        if paid_chapters:
            for chap in paid_chapters:
                raw_chaptername = chap["chaptername"].strip()
                raw_nameextend  = chap["nameextend"].strip()

                chaptername = raw_chaptername
                nameextend  = f"***{raw_nameextend}***" if raw_nameextend else ""
                volume = chap.get("volume", "")

                pub_date = chap["pubDate"]
                if pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=datetime.timezone.utc)

                # Case-insensitive detection for "(NSFW)", "(18+)", "(H)", "(HH)", "(HHH)"
                is_nsfw = has_nsfw_marker(
                    raw_chaptername,
                    raw_nameextend,
                    chap.get("description", ""),
                    chap.get("volume", "")
                )

                item = MyRSSItem(
                    title=novel_title,
                    link=chap["link"],
                    description=chap["description"],
                    guid=PyRSS2Gen.Guid(chap["guid"], isPermaLink=False),
                    pubDate=pub_date,
                    volume=volume,
                    chaptername=chaptername,
                    nameextend=nameextend,
                    coin=chap.get("coin", ""),
                    host=host,
                    is_nsfw=is_nsfw,
                )
                items.append(item)
        return items

class MyRSSItem(PyRSS2Gen.RSSItem):
    def __init__(self, *args, volume="", chaptername="", nameextend="", coin="", host="", is_nsfw=None, **kwargs):
        self.volume      = volume
        self.chaptername = chaptername
        self.nameextend  = nameextend
        self.coin        = coin
        self.host        = host
        self.is_nsfw     = is_nsfw
        super().__init__(*args, **kwargs)

    def writexml(self, writer, indent="", addindent="", newl=""):
        writer.write(indent + "  <item>" + newl)
        writer.write(indent + "    <title>%s</title>" % escape(self.title) + newl)
        writer.write(indent + "    <volume>%s</volume>" % escape(self.volume) + newl)
        writer.write(indent + "    <chaptername>%s</chaptername>" % escape(self.chaptername) + newl)

        formatted_nameextend = self.nameextend.strip()
        writer.write(indent + "    <nameextend>%s</nameextend>" % escape(formatted_nameextend) + newl)

        writer.write(indent + "    <link>%s</link>" % escape(self.link) + newl)
        writer.write(indent + "    <description><![CDATA[%s]]></description>" % self.description + newl)

        nsfw_list = get_nsfw_novels()
        is_nsfw = bool(self.is_nsfw) or (self.title in nsfw_list)
        writer.write(indent + "    <category>%s</category>" % ("NSFW" if is_nsfw else "SFW") + newl)

        translator = get_host_translator(self.host)
        writer.write(indent + "    <translator>%s</translator>" % escape(translator) + newl)

        discord_role = get_novel_discord_role(self.title, self.host)
        writer.write(indent + "    <discord_role_id><![CDATA[%s]]></discord_role_id>" % discord_role + newl)

        writer.write(indent + '    <featuredImage url="%s"/>' % escape(get_featured_image(self.title, self.host)) + newl)
        if self.coin:
            emoji = get_coin_emoji(self.host)
            writer.write(indent + "    <coin>%s %s</coin>" % (escape(emoji), escape(self.coin)) + newl)

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
    async with aiohttp.ClientSession() as session:
        tasks = []
        for host, data in HOSTING_SITE_DATA.items():
            for novel_title in data.get("novels", {}).keys():
                tasks.append(asyncio.create_task(process_novel(session, host, novel_title)))
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

    kept.sort(key=lambda it: (
        normalize_date(it.pubDate),
        get_host_utils(getattr(it, "host", "")).get("chapter_num", lambda s:(0,))(getattr(it, "chaptername",""))
    ), reverse=True)
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
