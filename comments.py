#!/usr/bin/env python
import os
import re
import html
import time
import json
import base64
import datetime
import feedparser
import PyRSS2Gen
import xml.dom.minidom
from pathlib import Path
from xml.sax.saxutils import escape
from bs4 import BeautifulSoup
import hashlib
import requests

from novel_mappings import HOSTING_SITE_DATA
from host_utils import get_host_utils

# --- token expiry → repository_dispatch (no Discord creds here) ---

ALERT_STATE_FILE = ".token_alert_state.json"

def _load_alert_state() -> dict:
    try:
        return json.loads(Path(ALERT_STATE_FILE).read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_alert_state(d: dict) -> None:
    Path(ALERT_STATE_FILE).write_text(json.dumps(d, indent=2), encoding="utf-8")

def _jwt_expiry_unix(token: str):
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return int(payload.get("exp")) if "exp" in payload else None
    except Exception:
        return None

def maybe_dispatch_token_alerts(threshold_days: int = 1):
    """Alert once per (host, token_secret, exp) when a JWT is ≤ threshold from expiry."""
    repo = os.getenv("GITHUB_REPOSITORY", "")
    token = os.getenv("PAT_GITHUB") or os.getenv("GITHUB_TOKEN")  # ← prefer PAT, fallback to GITHUB_TOKEN
    if not repo or not token:
        return

    state = _load_alert_state()
    now = int(time.time())
    url = f"https://api.github.com/repos/{repo}/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    for host, data in HOSTING_SITE_DATA.items():
        token_secret = data.get("token_secret")
        if not token_secret:
            continue
        token = os.getenv(token_secret, "").strip()
        if not token:
            continue

        exp = _jwt_expiry_unix(token)
        if not exp:
            continue

        secs_left = exp - now
        if secs_left > threshold_days * 86400:
            continue

        key = f"{host}:{token_secret}:last_exp"
        if int(state.get(key, 0)) == exp:
            continue  # already alerted for this exact token

        payload = {
            "event_type": "token-expiring",
            "client_payload": {
                "host": host,
                "token_secret_name": token_secret,
                "exp": exp,
                "secs_left": secs_left,
            },
        }
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=15)
            r.raise_for_status()
            state[key] = exp
            _save_alert_state(state)
            print(f"[alert] dispatched token-expiring → {host} ({token_secret})")
        except Exception as e:
            print(f"[warn] repository_dispatch failed for {host}: {e}")

# --- Construct Guid ---
def _guid_from(parts):  # local helper for deterministic IDs
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p).encode("utf-8", "ignore"))
        h.update(b"\x1f")
    return h.hexdigest()
    
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
        
        utils = get_host_utils(self.host)

        # <chapter> via host-specific extractor
        if "extract_chapter" in utils:
            chapter_info = utils["extract_chapter"](self.link)
        else:
            from urllib.parse import urlparse, unquote
            parsed = urlparse(self.link)
            segments = [seg for seg in parsed.path.split('/') if seg]
            chapter_info = "Homepage" if len(segments) <= 2 else unquote(segments[-1]).replace('-', ' ')
        writer.write(indent + "    <chapter>%s</chapter>" % escape(chapter_info) + newl)
    
        # Build a proper permalink
        real_link = self.link
        builder = utils.get("build_comment_link")
        if builder:
            real_link = builder(self.novel_title, self.host, self.link)
            
        writer.write(indent + "    <link>%s</link>" % escape(real_link) + newl)
        writer.write(indent + "    <dc:creator><![CDATA[%s]]></dc:creator>" % escape(self.author) + newl)
        writer.write(indent + "    <description><![CDATA[%s]]></description>" % self.description + newl)

        if self.reply_chain:
            rc = (self.reply_chain or "").strip()
            if rc and not rc.lower().startswith("in reply to"):
                rc = f"In reply to {rc}"
            writer.write(indent + "    <reply_chain><![CDATA[ᯓ✿ %s]]></reply_chain>" % escape(rc) + newl)

        # Get other metadata using host-specific functions.
        translator = utils.get("get_host_translator", lambda host: "")(self.host)
        writer.write(indent + "    <translator>%s</translator>" % escape(translator) + newl)
        discord_role = utils["get_novel_discord_role"](self.host, self.novel_title)
        writer.write(indent + "    <discord_role_id><![CDATA[%s]]></discord_role_id>" % discord_role + newl)
        featured_image = utils["get_featured_image"](self.host, self.novel_title)
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
    # Fire repo_dispatch if any host JWT is within 1 day of expiry (throttled).
    maybe_dispatch_token_alerts(threshold_days=1)
    all_rss_items = []
    # Loop over all hosts in your mappings.
    for host, data in HOSTING_SITE_DATA.items():
        # Retrieve comments feed URL from mappings.
        comments_feed_url = data.get("comments_feed_url")
        if not comments_feed_url:
            print(f"No comments feed URL defined for host: {host}")
            continue
        print(f"Fetching comments for host: {host} from {comments_feed_url}")

        utils = get_host_utils(host)
        
        def _parse_iso_utc_local(s: str):
            try:
                return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
            except Exception:
                return datetime.datetime.now(datetime.timezone.utc)
        
        # If host provides a custom comments loader (e.g., Mistmint JSON), use it.
        loader = utils.get("load_comments")
        if loader:
            try:
                norm_items = loader(comments_feed_url)
        
                # ---- NEW: treat empty as a notice, not a failure ----
                if not norm_items:
                    try:
                        from host_utils import _gha  # optional; falls back to print
                        _gha("notice", "mistmint-empty", f"{host} returned 0 items; skipping.")
                    except Exception:
                        print(f"[{host}] empty; skipping host.")
                    continue  # go to next host without error
                # -----------------------------------------------------
        
                print(f"[loader] {host}: {len(norm_items)} items from loader (url={comments_feed_url})")
                for obj in norm_items:
                    novel_title   = obj.get("novel_title", "").strip()
                    if not novel_title:
                        continue
                    novel_details = utils.get("get_novel_details", lambda h, nt: {})(host, novel_title)
                    if not novel_details:
                        print("Skipping item (novel not found in mapping):", novel_title)
                        continue
        
                    chapter_label = obj.get("chapter", "")
                    author_name   = obj.get("author", "")
                    body          = obj.get("description", "").strip()
                    posted_at     = obj.get("posted_at", "")
                    reply_to      = obj.get("reply_to", "")
        
                    guid_val = (
                        str(obj.get("guid") or "") or
                        next((str(obj.get(k)) for k in ("commentId", "comment_id", "id", "_id") if obj.get(k)), "") or
                        _guid_from([novel_title, author_name, posted_at, body[:80]])
                    )
                    label = (chapter_label or "").strip()
                    where = "homepage" if (not label or label.lower() == "homepage") else label
                    print(f"[loader] using guid={guid_val} for {novel_title} ({where})")
        
                    item = MyCommentRSSItem(
                        novel_title=novel_title,
                        title=novel_title,
                        link=chapter_label,  # label or URL; writexml will fix per-host
                        author=author_name,
                        description=body,
                        reply_chain=reply_to,
                        guid=PyRSS2Gen.Guid(guid_val, isPermaLink=False),
                        pubDate=_parse_iso_utc_local(posted_at).astimezone(datetime.timezone.utc) if posted_at
                                else datetime.datetime.now(datetime.timezone.utc),
                        host=host
                    )
                    all_rss_items.append(item)
        
                continue  # next host
            except Exception as e:
                print(f"[{host}] load_comments failed, falling back to generic: {e}")

        parsed_feed = feedparser.parse(comments_feed_url)

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

            pp = getattr(entry, "published_parsed", None)
            pub_date = (
                datetime.datetime(*pp[:6], tzinfo=datetime.timezone.utc)
                if pp else datetime.datetime.now(datetime.timezone.utc)
            )
            
            # 1) let host_utils decide which HTML to split (description vs content)
            pick_html = utils.get("pick_comment_html")
            if callable(pick_html):
                raw_html = pick_html(entry)
            else:
                # generic fallback
                raw_html = None
                content = entry.get("content")
                if isinstance(content, list) and content:
                    raw_html = content[0].get("value")
                if raw_html is None:
                    raw_html = html.unescape(entry.get("description", "") or "")
            
            # 2) Split off “In reply to …” → put only the name line in <reply_chain>
            split_reply_chain = get_host_utils(host).get("split_reply_chain", lambda s: ("", s))
            reply_chain, post_html = split_reply_chain(raw_html)
            
            # 3) Strip tags and fix stray spaces before punctuation in the body
            soup = BeautifulSoup(post_html, "html.parser")
            description_text = soup.get_text(separator=" ").strip()
            description_text = re.sub(r"\s+([.,!?;:])", r"\1", description_text)
    
            m = re.search(r"#comment-(\d+)", entry.get("link", "") or "")
            cid = m.group(1) if m else None
            guid_val = (getattr(entry, "id", "") or cid or _guid_from([
                novel_title,
                entry.get("author", ""),
                entry.get("published", "") or str(getattr(entry, "published_parsed", "")),
                description_text[:80],
            ]))
    
            # 4) pass both into your RSS item
            item = MyCommentRSSItem(
                novel_title=novel_title,
                title=novel_title,
                link=entry.link,
                author=entry.get("author", ""),
                description=description_text,
                reply_chain=reply_chain,
                guid=PyRSS2Gen.Guid(guid_val, isPermaLink=False),
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
