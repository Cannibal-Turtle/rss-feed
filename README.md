# Guide for Updating Novel/Translator Mappings and Host Utilities

This guide explains which elements need to be updated whenever a new novel, translator, or hosting site is added. Please update the following files accordingly.

---

## 1. `novel_mappings.py`

This file contains mapping data for each hosting site. When adding a **new novel** or **new hosting site**, you will update:

- **`HOSTING_SITE_DATA`**  
  - `feed_url`: The URL for the feed (e.g., free chapters)
  - `paid_feed_url`: If site has URL for paid feed
  - `translator`: Your username on that site  
  - `host_logo`: The URL for the hosting site's logo  
  - `novels`: A dictionary that maps each novel title to:
    - `discord_role_id`: The Discord role ID  
    - `novel_url`: The manual URL for the novel’s main page  
    - `featured_image`: The URL for the novel’s featured image
    - `pub_date_override`: The override for the system's default time of scraping

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
                "featured_image": "https://dragonholic.com/wp-content/uploads/2024/08/177838.jpg",
                "pub_date_override": {"hour": 12, "minute": 0, "second": 0}

            },
            # Second novel here
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

## **2. `host_utils.py`**  

- Manages host-specific logic under one module.  
- Currently supports **Dragonholic**, but can be extended to other hosts.  

### **Dragonholic Functions**  
- **`split_title_dragonholic(full_title)`** → Splits a chapter title into `main_title`, `chaptername`, and `nameextend`.  
- **`chapter_num_dragonholic(chaptername)`** → Extracts numeric values from chapter names.  
- **`clean_description(raw_desc)`** → Cleans raw HTML descriptions by removing unnecessary elements.  
- **`extract_pubdate_from_soup(chap)`** → Parses chapter publication dates, handling absolute and relative dates.  
- **`novel_has_paid_update_async(session, novel_url)`** → Checks if a novel has a premium (paid) update within the last 7 days.  

### **Host Utility Dispatcher**  
To get the appropriate utility functions for a specific host, use:  
```python
get_host_utils("Dragonholic")

---
```
## Summary Checklist

1. **Add a New Novel on an Existing Host:**
   - In `novel_mappings.py`, add or update the `novels` dictionary under the appropriate host in `HOSTING_SITE_DATA`.
   - If the novel is NSFW, also add it to `get_nsfw_novels()`.

2. **Add a New Hosting Site:**
   - In `novel_mappings.py`, create a new entry in `HOSTING_SITE_DATA` with:
     - `feed_url`, `translator`, `host_logo`, and a `novels` dictionary.
   - In `host_utils.py`, create new site‑specific functions and group them in a new dictionary. Update `get_host_utils(host)` to return that dictionary.

Following these steps keeps your feed generator modular and easy to update.
