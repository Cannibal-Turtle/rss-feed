import re
import datetime
import asyncio
import aiohttp
from bs4 import BeautifulSoup
import PyRSS2Gen
import xml.dom.minidom
from xml.sax.saxutils import escape
from collections import defaultdict

# Import mapping functions and data from novel_mappings.py
from novel_mappings import (
    HOSTING_SITE_DATA,
    get_novel_url,
    get_featured_image,
    get_host_translator,
    get_host_logo,
    get_novel_details,
    get_novel_discord_role,
    get_nsfw_novels,
    get_pub_date_override
)

# Import host utilities dispatcher from host_utils.py
from host_utils import get_host_utils

# ---------------- Concurrency Control ----------------
semaphore = asyncio.Semaphore(100)

# ---------------- Helper Functions ----------------

def normalize_date(dt):
    """Normalizes a datetime by removing microseconds."""
    return dt.replace(microsecond=0)

# ---------------- Main Processing Functions ----------------

async def process_novel(session, host, novel_title):
    """Processes a single novel under the semaphore limit."""
    async with semaphore:
        novel_url = get_novel_url(novel_title, host)
        print(f"Scraping: {novel_url}")
        utils = get_host_utils(host)

        # Check for recent premium update using the host-specific function.
        if not await utils["novel_has_paid_update_async"](session, novel_url):
            print(f"Skipping {novel_title}: no recent premium update found.")
            return []

        # Scrape paid chapters using the host-specific function.
        paid_chapters, main_desc = await utils["scrape_paid_chapters_async"](session, novel_url)
        items = []

        if paid_chapters:
            for chap in paid_chapters:
                # The scraped data:
                # chap["chaptername"] might be "Chapter 639"
                # chap["nameextend"] might be "The Abandoned Supporting Female Role 021"
                raw_chaptername = chap["chaptername"].strip() if chap["chaptername"] else ""
                raw_nameextend = chap["nameextend"].strip() if chap["nameextend"] else ""

                # If "Chapter 639" is in chap["chaptername"] and "The Abandoned Supporting Female Role 021"
                # is in chap["nameextend"], then keep them as is:
                chaptername = raw_chaptername  # e.g. "Chapter 639"
                nameextend = f"***{raw_nameextend}***" if raw_nameextend else ""

                pub_date = chap["pubDate"]
                if pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=datetime.timezone.utc)

                # Apply publication date override if defined.
                override = get_pub_date_override(novel_title, host)
                if override:
                    pub_date = pub_date.replace(**override)

                # Create RSS item
                item = MyRSSItem(
                    title=novel_title,
                    link=chap["link"],
                    description=chap["description"],
                    guid=PyRSS2Gen.Guid(chap["guid"], isPermaLink=False),
                    pubDate=pub_date,
                    chaptername=chaptername,
                    nameextend=nameextend,
                    coin=chap.get("coin", ""),
                    host=host
                )
                items.append(item)

        return items

# ---------------- RSS Generation Classes ----------------

class MyRSSItem(PyRSS2Gen.RSSItem):
    def __init__(self, *args, chaptername="", nameextend="", coin="", host="", **kwargs):
        self.chaptername = chaptername
        self.nameextend = nameextend
        self.coin = coin
        self.host = host  # e.g., "Dragonholic"
        super().__init__(*args, **kwargs)

    def writexml(self, writer, indent="", addindent="", newl=""):
        writer.write(indent + "  <item>" + newl)
        writer.write(indent + "    <title>%s</title>" % escape(self.title) + newl)
        writer.write(indent + "    <chaptername>%s</chaptername>" % escape(self.chaptername) + newl)
        formatted_nameextend = f"{self.nameextend}" if self.nameextend.strip() else ""
        writer.write(indent + "    <nameextend>%s</nameextend>" % escape(formatted_nameextend) + newl)
        writer.write(indent + "    <link>%s</link>" % escape(self.link) + newl)
        writer.write(indent + "    <description><![CDATA[%s]]></description>" % self.description + newl)

        nsfw_list = get_nsfw_novels()
        category_value = "NSFW" if self.title in nsfw_list else "SFW"
        writer.write(indent + "    <category>%s</category>" % escape(category_value) + newl)

        translator = get_host_translator(self.host)
        writer.write(indent + "    <translator>%s</translator>" % escape(translator) + newl)

        discord_role = get_novel_discord_role(self.title, self.host)
        writer.write(indent + "    <discord_role_id><![CDATA[%s]]></discord_role_id>" % discord_role + newl)

        writer.write(indent + '    <featuredImage url="%s"/>' % escape(get_featured_image(self.title, self.host)) + newl)
        if self.coin:
            writer.write(indent + "    <coin>%s</coin>" % escape(self.coin) + newl)

        # Format the pubDate
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
    rss_items = []
    async with aiohttp.ClientSession() as session:
        tasks = []
        # Iterate over each host and each novel in the mapping
        for host, data in HOSTING_SITE_DATA.items():
            for novel_title in data["novels"].keys():
                tasks.append(asyncio.create_task(process_novel(session, host, novel_title)))
        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks)
        for items in results:
            rss_items.extend(items)

    # Sort items primarily by pubDate, then chapter number
    rss_items.sort(key=lambda item: (
        normalize_date(item.pubDate),
        get_host_utils(item.host)["chapter_num"](item.chaptername)
    ), reverse=True)

    # Debug
    for item in rss_items:
        print(f"{item.title} - {item.chaptername} ({get_host_utils(item.host)['chapter_num'](item.chaptername)}) : {item.pubDate}")

    new_feed = CustomRSS2(
        title="Aggregated Paid Chapters Feed",
        link="https://github.com/cannibal-turtle/",
        description="Aggregated RSS feed for paid chapters across mapped novels.",
        lastBuildDate=datetime.datetime.now(datetime.timezone.utc),
        items=rss_items
    )

    output_file = "paid_chapters_feed.xml"
    with open(output_file, "w", encoding="utf-8") as f:
        new_feed.writexml(f, indent="  ", addindent="  ", newl="\n")

    with open(output_file, "r", encoding="utf-8") as f:
        xml_content = f.read()
    dom = xml.dom.minidom.parseString(xml_content)
    pretty_xml = "\n".join([
        line for line in dom.toprettyxml(indent="  ").splitlines()
        if line.strip()
    ])
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(pretty_xml)

    # Debug
    for item in rss_items:
        print(f"{item.title} - {item.chaptername} ({get_host_utils(item.host)['chapter_num'](item.chaptername)}) : {item.pubDate}")

    print(f"Modified feed generated with {len(rss_items)} items.")
    print(f"Output written to {output_file}")

if __name__ == "__main__":
    asyncio.run(main_async())
