#!/usr/bin/env python
import datetime
import feedparser
import PyRSS2Gen
import xml.dom.minidom
import re
import html
from xml.sax.saxutils import escape
from bs4 import BeautifulSoup

# Import your host mapping data and utilities.
from novel_mappings import HOSTING_SITE_DATA
from host_utils import get_host_utils

# --- token expiry + dispatch helpers ---
import os, base64, json, time, requests, pathlib

ALERT_STATE_FILE = ".token_alert_state.json"

def _load_alert_state() -> dict:
    try:
        with open(ALERT_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}

def _save_alert_state(d: dict) -> None:
    with open(ALERT_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)

def _jwt_expiry_unix(token: str) -> int | None:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return int(payload.get("exp")) if "exp" in payload else None
    except Exception:
        return None

def maybe_dispatch_token_alert(threshold_days: int = 1):
    """
    Fires a repository_dispatch if MISTMINT_TOKEN expires within N days.
    Throttled: will only send once per unique exp value.
    Requires env:
      - MISTMINT_TOKEN
      - PAT_GITHUB            (fine-grained PAT with repo + actions scopes)
      - GITHUB_REPOSITORY     (e.g. 'Cannibal-Turtle/rss-feed')
    """
    token = os.getenv("MISTMINT_TOKEN", "").strip()
    if not token:
        return
    exp = _jwt_expiry_unix(token)
    if not exp:
        return

    now = int(time.time())
    secs_left = exp - now
    if secs_left > threshold_days * 86400:
        return  # not expiring soon

    state = _load_alert_state()
    last_alerted_exp = int(state.get("last_alerted_exp", 0))
    if last_alerted_exp == exp:
        return  # already alerted for this exact token

    repo = os.getenv("GITHUB_REPOSITORY", "")
    pat  = os.getenv("PAT_GITHUB", "")
    if not repo or not pat:
        return

    url = f"https://api.github.com/repos/{repo}/dispatches"
    payload = {
        "event_type": "mistmint-token-expiring",
        "client_payload": {"exp": exp, "secs_left": secs_left}
    }
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {pat}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        r.raise_for_status()
        # mark alerted for this exp
        state["last_alerted_exp"] = exp
        _save_alert_state(state)
    except Exception as e:
        print(f"[warn] repository_dispatch failed: {e}")


# --- Compact Description ---
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

# ---------------- Comments Feed Item ----------------

class MyCommentRSSItem(PyRSS2Gen.RSSItem):
    def __init__(self, *args, novel_title="", host="", reply_chain="", **kwargs):
        self.novel_title = novel_title  # As derived from the comment's title.
        self.host = host
        self.reply_chain  = reply_chain
        super().__init__(*args, **kwargs)
    def writexml(self, writer, indent="", addindent="", newl=""):
        writer.write(indent + "  <item>" + newl)
        writer.write(indent + "    <title>%s</title>" % escape(self.novel_title) + newl)
        # Retrieve host-specific utilities.
        utils = get_host_utils(self.host)
        # Extract chapter info via host-specific function; fallback to default.
        if "extract_chapter" in utils:
            chapter_info = utils["extract_chapter"](self.link)
        else:
            # Default: use the last nonempty segment (if >2 segments) or "Homepage"
            from urllib.parse import urlparse, unquote
            parsed = urlparse(self.link)
            segments = [seg for seg in parsed.path.split('/') if seg]
            if len(segments) <= 2:
                chapter_info = "Homepage"
            else:
                chapter_info = unquote(segments[-1]).replace('-', ' ')
        writer.write(indent + "    <chapter>%s</chapter>" % escape(chapter_info) + newl)
        real_link = self.link
        if self.link.startswith("https://dragonholic.com/comments/feed"):
            # use the host_utils builder
            real_link = get_host_utils(self.host)["build_comment_link"](
                self.novel_title, self.host, self.link
            )
        writer.write(indent + "    <link>%s</link>" % escape(real_link) + newl)
        writer.write(indent + "    <dc:creator><![CDATA[%s]]></dc:creator>" % escape(self.author) + newl)
        writer.write(indent + "    <description><![CDATA[%s]]></description>" % self.description + newl)
        # if there's a reply chain, emit it as its own element
        if self.reply_chain:
            # add the ᯓ✿ prefix before the reply text
            writer.write(
                indent
                + "    <reply_chain><![CDATA[ᯓ✿ %s]]></reply_chain>"
                % escape(self.reply_chain)
                + newl
            )
        # Get other metadata using host-specific functions.
        translator = utils.get("get_host_translator", lambda host: "")(self.host)
        writer.write(indent + "    <translator>%s</translator>" % escape(translator) + newl)
        discord_role = utils.get("get_novel_discord_role", lambda nt, host: "")(self.novel_title, self.host)
        writer.write(indent + "    <discord_role_id><![CDATA[%s]]></discord_role_id>" % discord_role + newl)
        featured_image = utils.get("get_featured_image", lambda nt, host: "")(self.novel_title, self.host)
        writer.write(indent + '    <featuredImage url="%s"/>' % escape(featured_image) + newl)
        writer.write(indent + "    <host>%s</host>" % escape(self.host) + newl)
        host_logo = utils.get("get_host_logo", lambda host: "")(self.host)
        writer.write(indent + '    <hostLogo url="%s"/>' % escape(host_logo) + newl)
        nsfw_list = utils.get("get_nsfw_novels", lambda: [])()
        category_value = "NSFW" if self.novel_title in nsfw_list else "SFW"
        writer.write(indent + "    <category>%s</category>" % escape(category_value) + newl)
        writer.write(indent + "    <pubDate>%s</pubDate>" % 
                     self.pubDate.strftime("%a, %d %b %Y %H:%M:%S +0000") + newl)
        writer.write(indent + "    <guid isPermaLink=\"%s\">%s</guid>" %
                     (str(self.guid.isPermaLink).lower(), escape(self.guid.guid)) + newl)
        writer.write(indent + "  </item>" + newl)

class CustomCommentRSS2(PyRSS2Gen.RSS2):
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

def main():
    # Alert if token is close to expiring; does nothing if OK/missing.
    maybe_dispatch_token_alert(threshold_days=1)
    all_rss_items = []
    # Loop over all hosts in your mappings.
    for host, data in HOSTING_SITE_DATA.items():
        # Retrieve comments feed URL from mappings.
        comments_feed_url = data.get("comments_feed_url")
        if not comments_feed_url:
            print(f"No comments feed URL defined for host: {host}")
            continue
        print(f"Fetching comments for host: {host} from {comments_feed_url}")
        parsed_feed = feedparser.parse(comments_feed_url)
        utils = get_host_utils(host)
        # Get the host-specific function to split comment titles.
        split_comment_title = utils.get("split_comment_title", lambda title: re.sub(r'^Comment on (.+?) by .+$', r'\1', title).strip())
        
        for entry in parsed_feed.entries:
            # Use host-specific logic to extract the novel title from the comment title.
            novel_title = split_comment_title(entry.title)
            if not novel_title:
                print(f"Skipping entry, unable to extract novel title from: {entry.title}")
                continue

            # Retrieve novel details using host-specific function.
            novel_details = utils.get("get_novel_details", lambda h, nt: {})(host, novel_title)
            if not novel_details:
                print("Skipping item (novel not found in mapping):", novel_title)
                continue

            pub_date = datetime.datetime(*entry.published_parsed[:6])
            # 1) prefer the real HTML block if it exists
            raw_html = entry.get("content:encoded")
            if raw_html is None:
                # fallback: un-escape the escaped <description> CDATA
                raw_html = html.unescape(entry.get("description", ""))
            
            # 2) split off the “In reply to…” header, but keep your existing reply_chain logic
            reply_chain, post_html = utils["split_reply_chain"](raw_html)
            
            # 3) strip *all* HTML tags (including both real <p> and ones that were &lt;p&gt;)
            soup = BeautifulSoup(post_html, "html.parser")
            description_text = soup.get_text(separator=" ").strip()
        
            # 4) pass both into your RSS item
            item = MyCommentRSSItem(
                novel_title=novel_title,
                title=novel_title,
                link=entry.link,
                author=entry.get("author", ""),
                description=description_text,
                reply_chain=reply_chain,
                guid=PyRSS2Gen.Guid(entry.id, isPermaLink=False),
                pubDate=pub_date,
                host=host
            )
            all_rss_items.append(item)
    
    # Sort aggregated items by publication date descending.
    all_rss_items.sort(key=lambda i: i.pubDate, reverse=True)
    
    new_feed = CustomCommentRSS2(
        title="Aggregated Comments Feed",
        link="https://github.com/Cannibal-Turtle",
        description="Aggregated RSS feed for comments across hosting sites.",
        lastBuildDate=datetime.datetime.now(),
        items=all_rss_items
    )
    
    output_file = "aggregated_comments_feed.xml"
    with open(output_file, "w", encoding="utf-8") as f:
        new_feed.writexml(f, indent="  ", addindent="  ", newl="\n")
    
    with open(output_file, "r", encoding="utf-8") as f:
        xml_content = f.read()
    dom = xml.dom.minidom.parseString(xml_content)
    pretty_xml = "\n".join([line for line in dom.toprettyxml(indent="  ").splitlines() if line.strip()])
    compacted_xml = compact_cdata(pretty_xml)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(compacted_xml)
    
    print("Modified aggregated comments feed generated with", len(all_rss_items), "items.")
    print("Output written to", output_file)

if __name__ == "__main__":
    main()
