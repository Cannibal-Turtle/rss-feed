# Guide for Updating Novel/Translator Mappings and Host Utilities

This guide explains which elements need to be updated whenever a new novel, translator, or hosting site is added. Please update the following files accordingly.

---

## 1. `novel_mappings.py`

This file contains mapping data for each hosting site. When adding a **new novel** or **new hosting site**, you will update:

- **`HOSTING_SITE_DATA`**  
  - `feed_url`: The URL for the feed (e.g., free chapters)  
  - `translator`: Your username on that site  
  - `host_logo`: The URL for the hosting site's logo  
  - `novels`: A dictionary that maps each novel title to:
    - `discord_role_id`: The Discord role ID  
    - `novel_url`: The manual URL for the novel’s main page  
    - `featured_image`: The URL for the novel’s featured image

### Example

```python
HOSTING_SITE_DATA = {
    "Dragonholic": {
        "feed_url": "https://dragonholic.com/feed/manga-chapters/",
        "translator": "Cannibal Turtle",
        "host_logo": "https://dragonholic.com/wp-content/uploads/2025/01/Web-Logo-White.png",
        "novels": {
            "Quick Transmigration: The Villain Is Too Pampered and Alluring": {
                "discord_role_id": "<@&1329391480435114005>",
                "novel_url": "https://dragonholic.com/novel/quick-transmigration-the-villain-is-too-pampered-and-alluring/",
                "featured_image": "https://dragonholic.com/wp-content/uploads/2024/08/177838.jpg"
            },
            "Second Novel Title Example": {
                "discord_role_id": "<@&123456789012345678>",
                "novel_url": "https://dragonholic.com/second-novel",
                "featured_image": "https://dragonholic.com/wp-content/uploads/2024/08/second-novel.jpg"
            },
            # Add more novels as needed.
        }
    },
    # Add additional hosting sites here.
}
```

- **`get_nsfw_novels()`**  
  If you have **NSFW** novel titles, add them to this list so that the feed generator can mark them accordingly.

```python
def get_nsfw_novels():
    return [
        # List NSFW novel titles here, e.g.:
        "Some NSFW Novel Title"
    ]
```

---

## 2. `host_utils.py`

This module groups all host‑specific logic under an umbrella for each hosting site. Currently, all functions here are tailored for Dragonholic, but you can add new hosts similarly by creating additional dictionaries and updating the dispatcher.

### Dragonholic Example

```python
import re
import datetime
import asyncio
import aiohttp
from bs4 import BeautifulSoup

# ---------------- Dragonholic-Specific Functions ----------------

def split_title_dragonholic(full_title):
    # Splits a Dragonholic chapter title into (main_title, chaptername, nameextend)
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

def chapter_num_dragonholic(chaptername):
    # Extracts numeric sequences from a Dragonholic chapter name.
    numbers = re.findall(r'\d+(?:\.\d+)?', chaptername)
    if not numbers:
        return (0,)
    return tuple(float(n) if '.' in n else int(n) for n in numbers)

def clean_description(raw_desc):
    # Cleans the raw HTML description by removing <div class="c-content-readmore">, etc.
    soup = BeautifulSoup(raw_desc, "html.parser")
    for div in soup.find_all("div", class_="c-content-readmore"):
        div.decompose()
    cleaned = soup.decode_contents()
    return re.sub(r'\s+', ' ', cleaned).strip()

def extract_pubdate_from_soup(chap):
    # Extracts the publication date from a chapter element.
    release_span = chap.find("span", class_="chapter-release-date")
    if release_span:
        i_tag = release_span.find("i")
        if i_tag:
            date_str = i_tag.get_text(strip=True)
            try:
                pub_dt = datetime.datetime.strptime(date_str, "%B %d, %Y")
                return pub_dt.replace(tzinfo=datetime.timezone.utc)
            except Exception:
                # Handle relative dates like "2 days ago"
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
    # Asynchronously fetches a URL using aiohttp and returns the response text.
    async with session.get(url) as response:
        return await response.text()

async def novel_has_paid_update_async(session, novel_url):
    # Checks if the novel page has a recent premium (paid) update within the last 7 days.
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
    # Scrapes the Dragonholic novel page for paid chapters.
    # Returns a tuple: (list_of_chapters, main_description)
    try:
        async with session.get(novel_url) as response:
            html = await response.text()
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
        main_title, chaptername, nameextend = split_title_dragonholic(raw_title)
        href = a_tag.get("href")
        if href and href.strip() != "#":
            chapter_link = href.strip()
        else:
            parts = chaptername.split()
            chapter_num_str = parts[-1] if parts else "unknown"
            chapter_link = f"{novel_url}chapter-{chapter_num_str}/"
        guid = None
        for cls in chap.get("class", []):
            if cls.startswith("data-chapter-"):
                guid = cls.replace("data-chapter-", "")
                break
        if not guid:
            parts = chaptername.split()
            guid = parts[-1] if parts else "unknown"
        coin_span = chap.find("span", class_="coin")
        coin_value = coin_span.get_text(strip=True) if coin_span else ""
        paid_chapters.append({
            "chaptername": chaptername,
            "nameextend": nameextend,
            "link": chapter_link,
            "description": main_desc,
            "pubDate": pub_dt,
            "guid": guid,
            "coin": coin_value
        })
    print(f"Total paid chapters processed from {novel_url}: {len(paid_chapters)}")
    return paid_chapters, main_desc

# Dispatcher Dictionary
DRAGONHOLIC_UTILS = {
    "split_title": split_title_dragonholic,
    "chapter_num": chapter_num_dragonholic,
    "clean_description": clean_description,
    "extract_pubdate": extract_pubdate_from_soup,
    "novel_has_paid_update_async": novel_has_paid_update_async,
    "scrape_paid_chapters_async": scrape_paid_chapters_async,
}

def get_host_utils(host):
    """
    Returns the utilities dictionary for the given host.
    For now, only "Dragonholic" is supported.
    If adding new hosts, add a similar dictionary (e.g. FOXAHOLIC_UTILS)
    and extend the logic here.
    """
    if host == "Dragonholic":
        return DRAGONHOLIC_UTILS
    return {}
```

---

## Summary Checklist

1. **Add a New Novel on an Existing Host:**
   - In `novel_mappings.py`, add or update the `novels` dictionary under the appropriate host in `HOSTING_SITE_DATA`.
   - If the novel is NSFW, also add it to `get_nsfw_novels()`.

2. **Add a New Hosting Site:**
   - In `novel_mappings.py`, create a new entry in `HOSTING_SITE_DATA` with:
     - `feed_url`, `translator`, `host_logo`, and a `novels` dictionary.
   - In `host_utils.py`, create new site‑specific functions and group them in a new dictionary. Update `get_host_utils(host)` to return that dictionary.

Following these steps keeps your feed generator modular and easy to update.
