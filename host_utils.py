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

async def scrape_paid_chapters_async(session, novel_url):
    """
    Scrapes the Dragonholic page for **paid** chapters.
    Uses `split_paid_chapter_dragonholic` to correctly extract:
      - `chaptername`
      - `nameextend`
    """
    try:
        html = await fetch_page(session, novel_url)
    except Exception as e:
        print(f"Error fetching {novel_url}: {e}")
        return [], ""

    soup = BeautifulSoup(html, "html.parser")
    desc_div = soup.find("div", class_="description-summary")
    main_desc = clean_description(desc_div.decode_contents()) if desc_div else ""

    chapters = soup.find_all("li", class_="wp-manga-chapter premium")
    paid_chapters = []
    now = datetime.datetime.now(datetime.timezone.utc)

    for chap in chapters:
        pub_dt = extract_pubdate_from_soup(chap)
        if pub_dt < now - datetime.timedelta(days=7):
            break

        a_tag = chap.find("a")
        if not a_tag:
            continue

        raw_title = a_tag.get_text(" ", strip=True)
        chaptername, nameextend = split_paid_chapter_dragonholic(raw_title)  # **Correct function called here**

        href = a_tag.get("href", "").strip()
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

    return paid_chapters, main_desc

# ---------------- CHAPTER NUMBER EXTRACTION (DO NOT TOUCH) ----------------

def chapter_num_dragonholic(chaptername):
    """
    Extracts numeric sequences from chapter names.
    """
    numbers = re.findall(r'\d+(?:\.\d+)?', chaptername)
    return tuple(float(n) if '.' in n else int(n) for n in numbers) if numbers else (0,)

# ---------------- DISPATCHER FOR DRAGONHOLIC ----------------

DRAGONHOLIC_UTILS = {
    "split_title": split_title_dragonholic,  # Free feed
    "split_paid_title": split_paid_chapter_dragonholic,  # Paid feed
    "chapter_num": chapter_num_dragonholic,
    "clean_description": clean_description,
    "extract_pubdate": extract_pubdate_from_soup,
    "novel_has_paid_update_async": novel_has_paid_update_async,
    "scrape_paid_chapters_async": scrape_paid_chapters_async
}

def get_host_utils(host):
    """
    Returns utility functions for the given host.
    """
    if host == "Dragonholic":
        return DRAGONHOLIC_UTILS
    return {}
