import datetime
import feedparser
import PyRSS2Gen
import xml.dom.minidom
import re
from xml.sax.saxutils import escape
from host_utils import get_host_utils, format_volume_from_url

# Import mapping functions and data from novel_mappings.py
from novel_mappings import (
    HOSTING_SITE_DATA,
    get_novel_url,
    get_featured_image,
    get_host_translator,
    get_host_logo,
    get_novel_details,
    get_novel_discord_role,
    get_nsfw_novels
)

def compact_cdata(xml_str):
    """
    Finds <description><![CDATA[ ... ]]></description> sections and replaces
    newlines and extra whitespace inside the CDATA with a single space.
    """
    pattern = re.compile(r'(<description><!\[CDATA\[)(.*?)(\]\]></description>)', re.DOTALL)
    def repl(match):
        start, cdata, end = match.groups()
        compact = re.sub(r'\s+', ' ', cdata.strip())
        return f"{start}{compact}{end}"
    return pattern.sub(repl, xml_str)

class MyRSSItem(PyRSS2Gen.RSSItem):
    def __init__(self, *args, volume="", chaptername="", nameextend="", host="", **kwargs):
        self.volume = volume
        self.chaptername = chaptername
        self.nameextend = nameextend
        self.host = host  # e.g., "Dragonholic", "Foxaholic", etc.
        super().__init__(*args, **kwargs)
    
    def writexml(self, writer, indent="", addindent="", newl=""):
        writer.write(indent + "  <item>" + newl)
        writer.write(indent + "    <title>%s</title>" % escape(self.title) + newl)
        writer.write(indent + "    <volume>%s</volume>" % escape(self.volume) + newl)
        writer.write(indent + "    <chaptername>%s</chaptername>" % escape(self.chaptername) + newl)
        formatted_nameextend = f"***{self.nameextend}***" if self.nameextend.strip() else ""
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
        
        writer.write(indent + "    <pubDate>%s</pubDate>" % self.pubDate.strftime("%a, %d %b %Y %H:%M:%S +0000") + newl)
        
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

def main():
    rss_items = []
    # Loop over each host defined in the mapping.
    for host, data in HOSTING_SITE_DATA.items():
        # Expect each host mapping to include a "feed_url" for free chapters.
        feed_url = data.get("feed_url")
        if not feed_url:
            print(f"No feed URL defined for host: {host}")
            continue
        parsed_feed = feedparser.parse(feed_url)
        utils = get_host_utils(host)
        for entry in parsed_feed.entries:
            # Use the host-specific split_title function.
            main_title, chaptername, nameextend = utils["split_title"](entry.title)
            
            # host-specific volume extraction
            volume = utils.get("extract_volume", lambda t, l: "")(entry.title, entry.link)
            # Retrieve novel details using the host and main title.
            novel_details = get_novel_details(host, main_title)
            if not novel_details:
                print("Skipping item (novel not found in mapping):", main_title)
                continue
            pub_date = datetime.datetime(*entry.published_parsed[:6])
            item = MyRSSItem(
                title=main_title,
                link=entry.link,  # Alternatively, use get_novel_url(main_title, host)
                description=entry.description,
                guid=PyRSS2Gen.Guid(entry.id, isPermaLink=False),
                pubDate=pub_date,
                volume=volume,
                chaptername=chaptername,
                nameextend=nameextend,
                host=host
            )
            rss_items.append(item)
    
    # Sort items by publication date, title, and chapter number (using host's chapter_num)
    rss_items.sort(
        key=lambda item: (
            item.pubDate,
            item.title,
            get_host_utils(item.host)["chapter_num"](item.chaptername),
        ),
        reverse=True
    )
    
    # Define generic feed properties for aggregated free chapters.    
    new_feed = CustomRSS2(
        title="Aggregated Free Chapters Feed",
        link="https://github.com/cannibal-turtle/",
        description="Aggregated RSS feed for free chapters across all hosting sites.",
        lastBuildDate=datetime.datetime.now(), 
        items=rss_items
    )
    
    output_file = "free_chapters_feed.xml"
    with open(output_file, "w", encoding="utf-8") as f:
        new_feed.writexml(f, indent="  ", addindent="  ", newl="\n")
    
    with open(output_file, "r", encoding="utf-8") as f:
        xml_content = f.read()
    dom = xml.dom.minidom.parseString(xml_content)
    pretty_xml = "\n".join([line for line in dom.toprettyxml(indent="  ").splitlines() if line.strip()])
    compacted_xml = compact_cdata(pretty_xml)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(pretty_xml)
    
    print("Modified feed generated with", len(rss_items), "items.")
    print("Output written to", output_file)

if __name__ == "__main__":
    main()
