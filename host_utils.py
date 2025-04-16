"""
host_utils.py

This module handles **both** free and paid chapter title parsing for Dragonholic.

**DO NOT MODIFY free feed logic**:
  - `split_title_dragonholic`: Used for free feeds.
  - `split_paid_chapter_dragonholic`: Used only for paid feeds (to handle <i> tags properly).
"""

import re
import datetime
import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urlparse, unquote
from novel_mappings import HOSTING_SITE_DATA

# ---------------- FREE FEED Split Function (DO NOT TOUCH) ----------------

def split_title_dragonholic(full_title):
    """
    Splits a Dragonholic chapter title.
    Expected format: "Main Title - Chapter Name - (Optional Extension)"
    Returns a tuple: (main_title, chaptername, nameextend)
    """
    parts = full_title.split(" - ")
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip(), ""
    elif len(parts) >= 3:
        main_title = parts[0].strip()
        chaptername = parts[1].strip()
        nameextend = parts[2].strip() if parts[2].strip() else (parts[3].strip() if len(parts) > 3 else "")
        return main_title, chaptername, nameextend
    else:
        return full_title.strip(), "", ""

# ---------------- PAID FEED Split Function (Handles <i> Tags) ----------------

def split_paid_chapter_dragonholic(raw_title):
    """
    Handles raw paid feed titles like:
      "Chapter 640 <i class=\"fas fa-lock\"></i> - The Abandoned Supporting Female Role 022"
    1) Remove <i ...>...</i>.
    2) Split once on " - " to separate "Chapter 640" from "The Abandoned...".
    Returns (chaptername, nameextend).
    """
    # Remove <i ...>...</i>
    cleaned = re.sub(r'<i[^>]*>.*?</i>', '', raw_title).strip()
    parts = cleaned.split(' - ', 1)
    if len(parts) == 2:
        chaptername = parts[0].strip()
        nameextend  = parts[1].strip()
    else:
        chaptername = cleaned
        nameextend  = ""
    return chaptername, nameextend

# ---------------- CLEANING FUNCTIONS ----------------

def clean_description(raw_desc):
    """
    Cleans up raw HTML descriptions.
    """
    soup = BeautifulSoup(raw_desc, "html.parser")
    for div in soup.find_all("div", class_="c-content-readmore"):
        div.decompose()
    return re.sub(r'\s+', ' ', soup.decode_contents()).strip()

def extract_pubdate_from_soup(chap):
    """
    Extracts the publication date from chapter metadata.
    """
    release_span = chap.find("span", class_="chapter-release-date")
    if release_span:
        i_tag = release_span.find("i")
        if i_tag:
            date_str = i_tag.get_text(strip=True)
            try:
                pub_dt = datetime.datetime.strptime(date_str, "%B %d, %Y")
                return pub_dt.replace(tzinfo=datetime.timezone.utc)
            except Exception:
                return datetime.datetime.now(datetime.timezone.utc)
    return datetime.datetime.now(datetime.timezone.utc)

async def fetch_page(session, url):
    """
    Fetch a webpage asynchronously.
    """
    async with session.get(url) as response:
        return await response.text()

async def novel_has_paid_update_async(session, novel_url):
    """
    Checks if a Dragonholic novel has a **recent** premium update (within 7 days).
    """
    try:
        html_text = await fetch_page(session, novel_url)
    except Exception as e:
        print(f"Error fetching {novel_url}: {e}")
        return False

    soup = BeautifulSoup(html_text, "html.parser")
    chapter_li = soup.find("li", class_="wp-manga-chapter")
    if chapter_li and "premium" in chapter_li.get("class", []):
        pub_dt = extract_pubdate_from_soup(chapter_li)
        if pub_dt >= datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7):
            return True
    return False

# ---------------- SCRAPING PAID CHAPTERS (Calls split_paid_chapter_dragonholic) ----------------

import feedparser

async def scrape_paid_chapters_async(session, novel_url, host):
    """
    Fetches paid chapters for a novel.
    - If the host has a `paid_feed_url`, it will parse the feed.
    - Otherwise, it scrapes the website.
    """
    utils = get_host_utils(host)
    paid_feed_url = HOSTING_SITE_DATA.get(host, {}).get("paid_feed_url")  # Check for a paid feed

    if paid_feed_url:
        print(f"DEBUG: Fetching paid chapters from feed: {paid_feed_url}")
        parsed_feed = feedparser.parse(paid_feed_url)
        paid_chapters = []

        for entry in parsed_feed.entries:
            # Use host-specific title splitting
            chaptername, nameextend = utils["split_paid_title"](entry.title)

            pub_date = datetime.datetime(*entry.published_parsed[:6], tzinfo=datetime.timezone.utc)
            guid = entry.id if entry.id else chaptername

            paid_chapters.append({
                "chaptername": chaptername,
                "nameextend": nameextend,
                "link": entry.link,
                "description": entry.description,
                "pubDate": pub_date,
                "guid": guid,
                "coin": ""  # Some feeds don't provide coin data
            })

        print(f"DEBUG: {len(paid_chapters)} paid chapters fetched from feed ({host})")
        return paid_chapters, ""

    # Fallback: Scrape paid chapters from the website
    print(f"DEBUG: Scraping paid chapters from {novel_url}")

    try:
        html = await fetch_page(session, novel_url)
    except Exception as e:
        print(f"ERROR fetching {novel_url}: {e}")
        return [], ""

    soup = BeautifulSoup(html, "html.parser")
    desc_div = soup.find("div", class_="description-summary")
    main_desc = clean_description(desc_div.decode_contents()) if desc_div else ""

    # ✅ Fix: Properly selecting all PAID chapters (premium)
    chapters = soup.select("li.wp-manga-chapter.premium")
    print(f"DEBUG: Found {len(chapters)} paid chapters on {novel_url}")

    paid_chapters = []
    now = datetime.datetime.now(datetime.timezone.utc)

    for chap in chapters:
        pub_dt = extract_pubdate_from_soup(chap)
        if pub_dt < now - datetime.timedelta(days=7):
            print(f"DEBUG: Skipping old chapter ({pub_dt})")
            break

        a_tag = chap.find("a")
        if not a_tag:
            print("DEBUG: Skipping chapter with no <a> tag")
            continue

        raw_title = a_tag.get_text(" ", strip=True)
        print(f"DEBUG: Processing chapter - {raw_title}")

        # ✅ Fix: Use `split_paid_chapter_dragonholic()`
        chaptername, nameextend = utils["split_paid_title"](raw_title)

        href = a_tag.get("href", "").strip()
        print(f"DEBUG: Extracted href: {href}")
        # Fallback: If href is missing or a placeholder, reconstruct the URL.
        if not href or href == "#":
            # Attempt to extract the chapter number from chaptername.
            parts = chaptername.split()
            chapter_num_str = parts[-1] if parts else "unknown"
            href = f"{novel_url}chapter-{chapter_num_str}/"
            print(f"DEBUG: Fallback constructed href: {href}")

        guid = next((cls.replace("data-chapter-", "") for cls in chap.get("class", []) if cls.startswith("data-chapter-")), "unknown")
        coin_span = chap.find("span", class_="coin")
        coin_value = coin_span.get_text(strip=True) if coin_span else ""

        paid_chapters.append({
            "chaptername": chaptername,
            "nameextend": nameextend,
            "link": href,
            "description": main_desc,
            "pubDate": pub_dt,
            "guid": guid,
            "coin": coin_value
        })

    print(f"DEBUG: {len(paid_chapters)} paid chapters processed from {novel_url}")
    return paid_chapters, main_desc

# ---------------- CHAPTER NUMBER EXTRACTION (DO NOT TOUCH) ----------------

def chapter_num_dragonholic(chaptername):
    """
    Extracts numeric sequences from chapter names.
    """
    numbers = re.findall(r'\d+(?:\.\d+)?', chaptername)
    return tuple(float(n) if '.' in n else int(n) for n in numbers) if numbers else (0,)

# ---------------- NEW: HOST-SPECIFIC COMMENT FUNCTIONS ----------------

def split_comment_title_dragonholic(comment_title):
    """
    Extracts the novel title from a Dragonholic comment title.
    Expected format: "Comment on [Novel Title] by [Commenter]"
    Returns the extracted novel title.
    """
    match = re.search(r"Comment on\s*(.*?)\s*by", comment_title, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""

def extract_chapter_dragonholic(link):
    """
    Extracts the chapter (or equivalent) text from a Dragonholic URL.
    - If the URL's path has two or fewer nonempty segments, returns "Homepage".
    - Otherwise, returns a human‑readable version of the last segment.
    For example:
      https://dragonholic.com/novel/quick-transmigration-the-villain-is-too-pampered-and-alluring/#comment-3111 
        yields "Homepage"
      https://dragonholic.com/novel/xyz/chapter-1-the-novice-adventurer/ 
        yields "Chapter 1 The Novice Adventurer"
    """
    parsed = urlparse(link)
    segments = [seg for seg in parsed.path.split('/') if seg]
    if len(segments) <= 2:
        return "Homepage"
    else:
        last_seg = segments[-1]
        decoded = unquote(last_seg)
        chapter_raw = decoded.replace('-', ' ')
        # Capitalize each word for readability.
        return ' '.join(word.capitalize() for word in chapter_raw.split())

# ---------------- DISPATCHER FOR DRAGONHOLIC ----------------

DRAGONHOLIC_UTILS = {
    "split_title": split_title_dragonholic,  # Free feed
    "split_paid_title": split_paid_chapter_dragonholic,  # Paid feed
    "chapter_num": chapter_num_dragonholic,
    "clean_description": clean_description,
    "extract_pubdate": extract_pubdate_from_soup,
    "novel_has_paid_update_async": novel_has_paid_update_async,
    "scrape_paid_chapters_async": scrape_paid_chapters_async,
    "split_comment_title": split_comment_title_dragonholic,  # NEW for comment title splitting
    "extract_chapter": extract_chapter_dragonholic,          # NEW for chapter extraction from link
    "get_novel_details": lambda host, novel_title: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(novel_title, {}),
    "get_host_translator": lambda host: HOSTING_SITE_DATA.get(host, {}).get("translator", ""),
    "get_host_logo": lambda host: HOSTING_SITE_DATA.get(host, {}).get("host_logo", ""),
    "get_featured_image": lambda novel_title, host: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(novel_title, {}).get("featured_image", ""),
    "get_novel_discord_role": lambda novel_title, host: HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(novel_title, {}).get("discord_role_id", ""),
    "get_nsfw_novels": lambda: []  # Replace with actual NSFW novel list if available.
}

def get_host_utils(host):
    """
    Returns utility functions for the given host.
    """
    if host == "Dragonholic":
        return DRAGONHOLIC_UTILS
    return {}
