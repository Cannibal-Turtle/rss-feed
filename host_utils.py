"""
host_utils.py

This module groups all host-specific logic for Dragonholic (and potentially other hosts).
We have two split functions:

1) split_title_dragonholic:
   - Used by the free feed logic. 
   - Expected format: "Main Title - Chapter XX - Optional Extension".

2) split_paid_chapter_dragonholic:
   - Used by the paid feed logic, which often includes <i class="fas fa-lock"></i>.
   - Removes <i> tags, then splits on " - " once.

Plus other helper functions for:
  - cleaning HTML descriptions
  - extracting publication dates
  - checking for premium updates
  - scraping paid chapters
"""

import re
import datetime
import aiohttp
from bs4 import BeautifulSoup

# ---------------- Free Feed Split Function ----------------

def split_title_dragonholic(full_title):
    """
    Splits a standard Dragonholic free feed title, e.g.:
      "After Rebirth, I Married My Archenemy - Chapter 76 - Because of Guilt"
    Returns (main_title, chaptername, nameextend).

    Example:
      Input: "After Rebirth, I Married My Archenemy - Chapter 76 - Because of Guilt"
      Output: ("After Rebirth, I Married My Archenemy", "Chapter 76", "Because of Guilt")
    """
    parts = full_title.split(" - ")
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip(), ""
    elif len(parts) >= 3:
        main_title = parts[0].strip()
        chaptername = parts[1].strip()
        # If there's a third part
        nameextend = parts[2].strip() if parts[2].strip() else ""
        return main_title, chaptername, nameextend
    else:
        # fallback if there's no " - "
        return full_title.strip(), "", ""

# ---------------- Paid Feed Split Function ----------------

def split_paid_chapter_dragonholic(raw_title):
    """
    Handles a raw paid feed title like:
      "Chapter 640 <i class=\"fas fa-lock\"></i> - The Abandoned Supporting Female Role 022"
    1) Remove <i ...>...</i>.
    2) Split once on " - " to separate "Chapter 640" from "The Abandoned..." extension.
    Returns (chaptername, nameextend).
    """
    # Remove <i ...>...</i>
    cleaned = re.sub(r'<i[^>]*>.*?</i>', '', raw_title).strip()
    # e.g. "Chapter 640  - The Abandoned Supporting Female Role 022"

    # Split once on ' - '
    parts = cleaned.split(' - ', 1)
    if len(parts) == 2:
        chaptername = parts[0].strip()
        nameextend  = parts[1].strip()
    else:
        chaptername = cleaned
        nameextend  = ""
    return chaptername, nameextend

# ---------------- Cleaning Description ----------------

def clean_description(raw_desc):
    """
    Removes <div class="c-content-readmore"> and extra whitespace from the raw HTML description.
    """
    soup = BeautifulSoup(raw_desc, "html.parser")
    for div in soup.find_all("div", class_="c-content-readmore"):
        div.decompose()
    cleaned = soup.decode_contents()
    return re.sub(r'\s+', ' ', cleaned).strip()

# ---------------- Extracting Publication Date ----------------

def extract_pubdate_from_soup(chap):
    """
    Finds <span class="chapter-release-date"> <i>...</i></span>,
    e.g. "February 16, 2025" or "2 days ago".
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
                if "ago" in date_str.lower():
                    now = datetime.datetime.now(datetime.timezone.utc)
                    parts = date_str.lower().split()
                    try:
                        number = int(parts[0])
                        unit = parts[1]
                        if "minute" in unit:
                            return now - datetime.timedelta(minutes=number)
                        elif "hour" in unit:
                            return now - datetime.timedelta(hours=number)
                        elif "day" in unit:
                            return now - datetime.timedelta(days=number)
                        elif "week" in unit:
                            return now - datetime.timedelta(weeks=number)
                    except Exception as e:
                        print(f"Error parsing relative date '{date_str}': {e}")
    return datetime.datetime.now(datetime.timezone.utc)

# ---------------- Checking for Premium Updates ----------------

async def fetch_page(session, url):
    async with session.get(url) as response:
        return await response.text()

async def novel_has_paid_update_async(session, novel_url):
    """
    Checks if there's a recent premium chapter in the last 7 days.
    """
    try:
        html_text = await fetch_page(session, novel_url)
    except Exception as e:
        print(f"Error fetching {novel_url} for quick check: {e}")
        return False

    soup = BeautifulSoup(html_text, "html.parser")
    chapter_li = soup.find("li", class_="wp-manga-chapter")
    if chapter_li:
        classes = chapter_li.get("class", [])
        if "premium" in classes and "free-chap" not in classes:
            pub_span = chapter_li.find("span", class_="chapter-release-date")
            if pub_span:
                i_tag = pub_span.find("i")
                if i_tag:
                    date_str = i_tag.get_text(strip=True)
                    try:
                        pub_dt = datetime.datetime.strptime(date_str, "%B %d, %Y").replace(tzinfo=datetime.timezone.utc)
                    except Exception:
                        pub_dt = datetime.datetime.now(datetime.timezone.utc)
                    now = datetime.datetime.now(datetime.timezone.utc)
                    if pub_dt >= now - datetime.timedelta(days=7):
                        return True
            else:
                # If there's no date but it's premium, assume it's recent
                return True
    return False

# ---------------- Scraping Paid Chapters ----------------

async def scrape_paid_chapters_async(session, novel_url):
    """
    Scrapes the Dragonholic novel page for paid chapters, specifically:
      <li class="wp-manga-chapter premium">
    Calls `split_paid_chapter_dragonholic` to handle <i class="fas fa-lock"></i> and " - " logic.
    Returns (paid_chapters, main_desc).
    """
    try:
        html = await fetch_page(session, novel_url)
    except Exception as e:
        print(f"Error fetching {novel_url}: {e}")
        return [], ""

    soup = BeautifulSoup(html, "html.parser")
    desc_div = soup.find("div", class_="description-summary")
    if desc_div:
        main_desc = clean_description(desc_div.decode_contents())
        print("Main description fetched.")
    else:
        main_desc = ""
        print("No main description found.")

    chapters = soup.find_all("li", class_="wp-manga-chapter")
    paid_chapters = []
    now = datetime.datetime.now(datetime.timezone.utc)
    print(f"Found {len(chapters)} chapter elements on {novel_url}")

    for chap in chapters:
        # Skip if not premium
        if "free-chap" in chap.get("class", []):
            continue
        if "premium" not in chap.get("class", []):
            continue

        pub_dt = extract_pubdate_from_soup(chap)
        if pub_dt < now - datetime.timedelta(days=7):
            break

        a_tag = chap.find("a")
        if not a_tag:
            continue

        raw_title = a_tag.get_text(" ", strip=True)
        print(f"Processing chapter: {raw_title}")

        # Use the specialized paid function
        chaptername, nameextend = split_paid_chapter_dragonholic(raw_title)

        href = a_tag.get("href", "").strip()
        if not href or href == "#":
            # fallback if we can't get the link
            parts = chaptername.split()
            chapter_num_str = parts[-1] if parts else "unknown"
            href = f"{novel_url}chapter-{chapter_num_str}/"

        # Build guid from data-chapter-xxx class
        guid = None
        for cls in chap.get("class", []):
            if cls.startswith("data-chapter-"):
                guid = cls.replace("data-chapter-", "")
                break
        if not guid:
            # fallback
            parts = chaptername.split()
            guid = parts[-1] if parts else "unknown"

        # Coins, if any
        coin_span = chap.find("span", class_="coin")
        coin_value = coin_span.get_text(strip=True) if coin_span else ""

        paid_chapters.append({
            "chaptername": chaptername,   # e.g. "Chapter 640"
            "nameextend": nameextend,     # e.g. "The Abandoned Supporting Female Role 022"
            "link": href,
            "description": main_desc,
            "pubDate": pub_dt,
            "guid": guid,
            "coin": coin_value
        })

    print(f"Total paid chapters processed from {novel_url}: {len(paid_chapters)}")
    return paid_chapters, main_desc

# ---------------- Additional Helper: Extract Chapter Number ----------------

def chapter_num_dragonholic(chaptername):
    """
    Extracts numeric sequences from the chapter name (e.g. "Chapter 640").
    Returns a tuple of ints or floats for sorting.
    """
    numbers = re.findall(r'\d+(?:\.\d+)?', chaptername)
    if not numbers:
        return (0,)
    return tuple(float(n) if '.' in n else int(n) for n in numbers)

# ---------------- Dispatcher for Dragonholic ----------------

DRAGONHOLIC_UTILS = {
    "split_title": split_title_dragonholic,         # used by free feed if needed
    "split_paid_title": split_paid_chapter_dragonholic,  # specifically for paid chapters
    "chapter_num": chapter_num_dragonholic,
    "clean_description": clean_description,
    "extract_pubdate": extract_pubdate_from_soup,
    "novel_has_paid_update_async": novel_has_paid_update_async,
    "scrape_paid_chapters_async": scrape_paid_chapters_async
}

def get_host_utils(host):
    """
    Returns a dictionary of utility functions for the given host.
    For now, only "Dragonholic" is supported, but you can add more as needed.
    """
    if host == "Dragonholic":
        return DRAGONHOLIC_UTILS
    # Extend for more hosts, e.g. "Foxaholic": FOXAHOLIC_UTILS, etc.
    return {}
