# RSS Feed Aggregator

This project aggregates RSS feeds for novels from various hosting sites into a single feed. The project is split into two main configuration modules:

- **novel_mappings.py** – Contains the mappings for each hosting site, including details for each novel.
- **host_utils.py** – Contains host‑specific utility functions (such as parsing chapter titles, extracting chapter numbers, cleaning HTML descriptions, and scraping chapters).

## novel_mappings.py

This file defines a dictionary called `HOSTING_SITE_DATA` that maps each host to its details. For each hosting site you support (e.g. Dragonholic), you should provide:

- **feed_url:** The URL of the feed for free chapters.
- **translator:** Your username on that site.
- **host_logo:** The URL for the hosting site's logo.
- **novels:** A dictionary mapping each novel title to its details:
  - **discord_role_id:** Your Discord role ID for the novel.
  - **novel_url:** The manual URL for the novel’s main page.
  - **featured_image:** The URL for the novel's featured image.

### Updating Mappings

- To add a **new novel** from an existing host (e.g. Dragonholic), add an entry in the `novels` dictionary under that host.
- To add a **new hosting site**, create a new entry in `HOSTING_SITE_DATA` with its `feed_url`, `translator`, `host_logo`, and `novels`. You will also need to add corresponding host‑specific functions in **host_utils.py** (see below).

## host_utils.py

This module groups all host‑specific logic under an “umbrella” for each hosting site. Currently, all functions are tailored for Dragonholic. They include functions for:

- **Title Splitting:**  
  `split_title_dragonholic(full_title)` splits a Dragonholic chapter title into a tuple: `(main_title, chaptername, nameextend)`.

- **Chapter Number Extraction:**  
  `chapter_num_dragonholic(chaptername)` extracts numeric values from the chapter name.

- **HTML Description Cleaning:**  
  `clean_description(raw_desc)` cleans the raw HTML description by removing unwanted elements and extra whitespace.

- **Publication Date Extraction:**  
  `extract_pubdate_from_soup(chap)` extracts the publication date from a chapter element using expected HTML classes.

- **Asynchronous Page Fetching & Scraping:**  
  `fetch_page(session, url)`, `novel_has_paid_update_async(session, novel_url)`, and `scrape_paid_chapters_async(session, novel_url)` are used to fetch the page, check for recent premium updates, and scrape chapter data respectively.

All Dragonholic‑specific functions are grouped in the `DRAGONHOLIC_UTILS` dictionary. The function `get_host_utils(host)` returns the corresponding dictionary based on the host name.

### Updating Host Utilities

- To **update Dragonholic functions**, modify the functions inside the `DRAGONHOLIC_UTILS` dictionary.
- To add a **new hosting site** (e.g. Foxaholic):
  1. Write Foxaholic‑specific functions (e.g. `split_title_foxaholic`, `chapter_num_foxaholic`, etc.).
  2. Create a new dictionary (e.g. `FOXAHOLIC_UTILS`) with those functions.
  3. Update `get_host_utils(host)` to return `FOXAHOLIC_UTILS` when the host is "Foxaholic".

## How It Works

1. **Mappings:**  
   The aggregator reads `HOSTING_SITE_DATA` from **novel_mappings.py** to know which hosts and novels to process.

2. **Host Utilities:**  
   When processing a novel, the aggregator calls `get_host_utils(host)` to obtain the host‑specific functions. These functions are then used to parse chapter titles, extract chapter numbers, clean descriptions, and scrape the chapters.

3. **Feed Generation:**  
   The main generator scripts (e.g., `free_feed_generator.py` or `paid_feed_generator.py`) use the mappings and host utilities to build an aggregated RSS feed.

## Adding New Content

- **New Novel on an Existing Host:**  
  Simply add the novel's details to the `novels` dictionary under that host in **novel_mappings.py**.

- **New Hosting Site:**  
  1. Update **novel_mappings.py** by adding a new entry for the hosting site.
  2. Create new host‑specific parsing/scraping functions for that site.
  3. Add these functions to a new dictionary (e.g. `FOXAHOLIC_UTILS`) in **host_utils.py**.
  4. Update the `get_host_utils(host)` function to return the new dictionary when appropriate.

## Example

### novel_mappings.py

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
        }
    },
    # Add other hosting sites here.
}

def get_host_translator(host):
    return HOSTING_SITE_DATA.get(host, {}).get("translator", "")

def get_host_logo(host):
    return HOSTING_SITE_DATA.get(host, {}).get("host_logo", "")

def get_novel_details(host, novel_title):
    return HOSTING_SITE_DATA.get(host, {}).get("novels", {}).get(novel_title, {})

def get_novel_discord_role(novel_title, host="Dragonholic"):
    details = get_novel_details(host, novel_title)
    return details.get("discord_role_id", "")

def get_novel_url(novel_title, host="Dragonholic"):
    details = get_novel_details(host, novel_title)
    return details.get("novel_url", "")

def get_featured_image(novel_title, host="Dragonholic"):
    details = get_novel_details(host, novel_title)
    return details.get("featured_image", "")

def get_nsfw_novels():
    return [
        # List NSFW novel titles here.
    ]
