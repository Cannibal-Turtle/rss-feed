"""
host_utils.py

This module groups all host‑specific logic under an umbrella for each hosting site.
Currently, all functions here are tailored for Dragonholic. They include functions for:
  - Splitting chapter titles into (main_title, chaptername, nameextend)
  - Extracting chapter numbers from chapter names
  - Cleaning HTML descriptions
  - Extracting publication dates from chapter elements
  - Checking for recent premium (paid) updates
  - Scraping paid chapters from a Dragonholic novel page
  - Fetching pages asynchronously

When adding a new hosting site (e.g. "Foxaholic"), you can write its own functions
and add them to a new dictionary, then update get_host_utils() accordingly.
"""

import re
import datetime
import asyncio
import aiohttp
from bs4 import BeautifulSoup

# ---------------- Dragonholic-Specific Functions ----------------

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

def split_paid_chapter_dragonholic(raw_title):
    """
    This function specifically handles a raw title like:
        "Chapter 633 <i class=\"fas fa-lock\"></i> - The Abandoned Supporting Female Role 015"
    1. Removes any <i>...</i> tags.
    2. Splits on ' - ' (the first occurrence) to separate 'Chapter 633' from 'The Abandoned Supporting Female Role 015'.
    Returns a tuple: (chaptername, nameextend).
    """
    # Remove <i ...>...</i> using a regex
    cleaned = re.sub(r'<i[^>]*>.*?</i>', '', raw_title).strip()
    # After removal, cleaned might look like: "Chapter 633  - The Abandoned Supporting Female Role 015"

    # Split on ' - ' (only once) to separate the left (chapter) from the right (extension)
    parts = cleaned.split(' - ', 1)
    if len(parts) == 2:
        chaptername = parts[0].strip()
        nameextend  = parts[1].strip()
    else:
        # If there's no ' - ', just assume there's only a chapter part
        chaptername = cleaned
        nameextend  = ""
    return chaptername, nameextend


def chapter_num_dragonholic(chaptername):
    """
    Extracts numeric sequences from a Dragonholic chapter name.
    Returns a tuple of numbers (ints or floats) found in the chapter name.
    """
    numbers = re.findall(r'\d+(?:\.\d+)?', chaptername)
    if not numbers:
        return (0,)
    return tuple(float(n) if '.' in n else int(n) for n in numbers)

def clean_description(raw_desc):
    """
    Cleans the raw HTML description by removing extra whitespace and unwanted elements.
    Specifically, it removes any <div> with the class "c-content-readmore".
    """
    soup = BeautifulSoup(raw_desc, "html.parser")
    for div in soup.find_all("div", class_="c-content-readmore"):
        div.decompose()
    cleaned = soup.decode_contents()
    return re.sub(r'\s+', ' ', cleaned).strip()

def extract_pubdate_from_soup(chap):
    """
    Extracts the publication date from a chapter element.
    Expects a <span class="chapter-release-date"> containing an <i> tag with a date
    in the format "%B %d, %Y" (or relative dates like "2 days ago").
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

async def fetch_page(session, url):
    """
    Asynchronously fetches a URL using aiohttp and returns the response text.
    """
    async with session.get(url) as response:
        return await response.text()

async def novel_has_paid_update_async(session, novel_url):
    """
    Checks if the Dragonholic novel page has a recent premium (paid) update.
    Loads the page, finds the first chapter element with class "wp-manga-chapter",
    and if it has the 'premium' class (and not 'free-chap') with a release date within
    the last 7 days, returns True.
    """
    try:
        async with session.get(novel_url) as response:
            html_text = await response.text()
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
                return True
    return False

async def scrape_paid_chapters_async(session, novel_url):
    # ...
    for chap in chapters:
        if "free-chap" in chap.get("class", []):
            continue
        pub_dt = extract_pubdate_from_soup(chap)
        if pub_dt < now - datetime.timedelta(days=7):
            break

        a_tag = chap.find("a")
        if not a_tag:
            continue

        raw_title = a_tag.get_text(" ", strip=True)
        print(f"Processing chapter: {raw_title}")

        # Instead of split_title_dragonholic, call the new function
        chaptername, nameextend = split_paid_chapter_dragonholic(raw_title)

        href = a_tag.get("href") or ""
        if not href.strip() or href.strip() == "#":
            # fallback logic
            parts = chaptername.split()
            chapter_num_str = parts[-1] if parts else "unknown"
            href = f"{novel_url}chapter-{chapter_num_str}/"

        # 'guid' logic remains the same
        guid = None
        for cls in chap.get("class", []):
            if cls.startswith("data-chapter-"):
                guid = cls.replace("data-chapter-", "")
                break
        if not guid:
            # fallback if no data-chapter- is found
            parts = chaptername.split()
            guid = parts[-1] if parts else "unknown"

        coin_span = chap.find("span", class_="coin")
        coin_value = coin_span.get_text(strip=True) if coin_span else ""

        paid_chapters.append({
            "chaptername": chaptername,    # e.g. "Chapter 633"
            "nameextend": nameextend,      # e.g. "The Abandoned Supporting Female Role 015"
            "link": href.strip(),
            "description": main_desc,
            "pubDate": pub_dt,
            "guid": guid,
            "coin": coin_value
        })
    # ...
    return paid_chapters, main_desc


# ---------------- Dispatcher for Dragonholic ----------------

DRAGONHOLIC_UTILS = {
    "split_title": split_title_dragonholic,
    "chapter_num": chapter_num_dragonholic,
    "clean_description": clean_description,
    "extract_pubdate": extract_pubdate_from_soup,
    "novel_has_paid_update_async": novel_has_paid_update_async,
    "scrape_paid_chapters_async": scrape_paid_chapters_async,
    # Note: fetch_page is used directly with an async session.
}

def get_host_utils(host):
    """
    Returns the utilities dictionary for the given host.
    For now, only "Dragonholic" is supported.
    """
    if host == "Dragonholic":
        return DRAGONHOLIC_UTILS
    # Extend here for additional hosts.
    return {}

