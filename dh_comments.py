#!/usr/bin/env python
import re
import datetime
import feedparser
import PyRSS2Gen
import xml.dom.minidom
from xml.sax.saxutils import escape

# Import mapping functions and data from your novel_mappings.py
from novel_mappings import (
    get_novel_details,
    get_novel_url,
    get_featured_image,
    get_host_translator,
    get_host_logo,
    get_novel_discord_role,  # Not used here; we'll override
    get_nsfw_novels
)

# Override function: return only the base Discord role (no NSFW extra appended)
def get_novel_discord_role_no_nsfw(novel_title, host="Dragonholic"):
    """Returns only the base Discord role without appending the NSFW extra role."""
    details = get_novel_details(host, novel_title)
    return details.get("discord_role_id", "")

# Regex to extract the novel title from the comment's title.
# This will capture everything between "Comment on" and "by"
COMMENT_TITLE_REGEX = re.compile(r"Comment on\s*(.*?)\s*by", re.IGNORECASE)

class MyCommentRSSItem(PyRSS2Gen.RSSItem):
    """
    Customized RSS item for comment feed items.
    """
    def __init__(self, *args, novel_title="", **kwargs):
        self.novel_title = novel_title
        super().__init__(*args, **kwargs)

    def writexml(self, writer, indent="", addindent="", newl=""):
        writer.write(indent + "  <item>" + newl)
        writer.write(indent + "    <title>%s</title>" % escape(self.novel_title) + newl)
        writer.write(indent + "    <link>%s</link>" % escape(self.link) + newl)
        writer.write(indent + "    <dc:creator><![CDATA[%s]]></dc:creator>" % escape(self.author) + newl)
        writer.write(indent + "    <pubDate>%s</pubDate>" % self.pubDate.strftime("%a, %d %b %Y %H:%M:%S +0000") + newl)
        writer.write(indent + "    <description><![CDATA[%s]]></description>" % self.description + newl)
        writer.write(indent + "    <content:encoded><![CDATA[%s]]></content:encoded>" % self.description + newl)
        # Escape GUID to avoid invalid tokens (e.g. unescaped ampersands)
        writer.write(indent + "    <guid isPermaLink=\"%s\">%s</guid>" %
                     (str(self.guid.isPermaLink).lower(), escape(self.guid.guid)) + newl)
        # Additional fields from the mapping (assuming host is "Dragonholic")
        host = "Dragonholic"
        translator = get_host_translator(host)
        writer.write(indent + "    <translator>%s</translator>" % escape(translator) + newl)
        # Use the overridden function here to ensure no extra NSFW role is appended.
        discord_role = get_novel_discord_role_no_nsfw(self.novel_title, host)
        writer.write(indent + "    <discord_role_id><![CDATA[%s]]></discord_role_id>" % discord_role + newl)
        featured_image = get_featured_image(self.novel_title, host)
        writer.write(indent + '    <featuredImage url="%s"/>' % escape(featured_image) + newl)
        writer.write(indent + "    <host>%s</host>" % escape(host) + newl)
        host_logo = get_host_logo(host)
        writer.write(indent + '    <hostLogo url="%s"/>' % escape(host_logo) + newl)
        # Determine category based on NSFW list (this is still done for categorization)
        nsfw_list = get_nsfw_novels()
        category_value = "NSFW" if self.novel_title in nsfw_list else "SFW"
        writer.write(indent + "    <category>%s</category>" % escape(category_value) + newl)
        writer.write(indent + "  </item>" + newl)

class CustomCommentRSS2(PyRSS2Gen.RSS2):
    """
    Customized RSS feed that uses our MyCommentRSSItem items.
    """
    def writexml(self, writer, indent="", addindent="", newl=""):
        writer.write('<?xml version="1.0" encoding="utf-8"?>' + newl)
        writer.write(
            '<rss xmlns:content="http://purl.org/rss/1.0/modules/content/" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:atom="http://www.w3.org/2005/Atom" '
            'xmlns:sy="http://purl.org/rss/1.0/modules/syndication/" '
            'xmlns:georss="http://www.georss.org/georss" '
            'xmlns:geo="http://www.w3.org/2003/01/geo/wgs84_pos#" '
            'version="2.0">' + newl
        )
        writer.write(indent + "<channel>" + newl)
        writer.write(indent + addindent + "<title>%s</title>" % escape(self.title) + newl)
        writer.write(indent + addindent + "<link>%s</link>" % escape(self.link) + newl)
        writer.write(indent + addindent + "<description>%s</description>" % escape(self.description) + newl)
        if hasattr(self, 'lastBuildDate') and self.lastBuildDate:
            writer.write(indent + addindent + "<lastBuildDate>%s</lastBuildDate>" %
                         self.lastBuildDate.strftime("%a, %d %b %Y %H:%M:%S +0000") + newl)
        for item in self.items:
            item.writexml(writer, indent + addindent, addindent, newl)
        writer.write(indent + "</channel>" + newl)
        writer.write("</rss>" + newl)

def compact_cdata(xml_str):
    """
    Compacts CDATA sections by replacing multiple whitespace characters with a single space.
    """
    pattern = re.compile(r'(<description><!\[CDATA\[)(.*?)(\]\]></description>)', re.DOTALL)
    def repl(match):
        start, cdata, end = match.groups()
        compact = re.sub(r'\s+', ' ', cdata.strip())
        return f"{start}{compact}{end}"
    return pattern.sub(repl, xml_str)

def main():
    comments_feed_url = "https://dragonholic.com/comments/feed/"
    parsed_feed = feedparser.parse(comments_feed_url)
    
    rss_items = []
    for entry in parsed_feed.entries:
        match = COMMENT_TITLE_REGEX.search(entry.title)
        if match:
            novel_title = match.group(1).strip()
        else:
            print(f"Skipping entry, unable to extract novel title from: {entry.title}")
            continue

        # Check if the novel exists in your mappings.
        novel_details = get_novel_details("Dragonholic", novel_title)
        if not novel_details:
            print("Skipping item (novel not found in mapping):", novel_title)
            continue

        pub_date = datetime.datetime(*entry.published_parsed[:6])
        description = entry.get("content:encoded", entry.get("description", ""))
        item = MyCommentRSSItem(
            novel_title=novel_title,
            title=novel_title,
            link=entry.link,
            author=entry.get("author", ""),
            description=description,
            guid=PyRSS2Gen.Guid(entry.id, isPermaLink=False),
            pubDate=pub_date
        )
        rss_items.append(item)
    
    # Sort items by publication date descending.
    rss_items.sort(key=lambda i: i.pubDate, reverse=True)
    
    new_feed = CustomCommentRSS2(
        title="Aggregated Comments Feed",
        link="https://yourwebsite.example.com/",
        description="Aggregated RSS feed for comments (with enhanced metadata) across novels.",
        lastBuildDate=datetime.datetime.now(),
        items=rss_items
    )
    
    output_file = "aggregated_comments_feed.xml"
    with open(output_file, "w", encoding="utf-8") as f:
        new_feed.writexml(f, indent="  ", addindent="  ", newl="\n")
    
    with open(output_file, "r", encoding="utf-8") as f:
        xml_content = f.read()
    try:
        dom = xml.dom.minidom.parseString(xml_content)
    except Exception as e:
        print("Error parsing generated XML:", e)
        raise
    pretty_xml = "\n".join([line for line in dom.toprettyxml(indent="  ").splitlines() if line.strip()])
    compacted_xml = compact_cdata(pretty_xml)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(compacted_xml)
    
    print("Modified comments feed generated with", len(rss_items), "items.")
    print("Output written to", output_file)

if __name__ == "__main__":
    main()
