# Guide for Updating Novel/Translator Mappings and Host Utilities

This guide explains which elements need to be updated whenever a new novel, translator, or hosting site is added. Please update the following files accordingly.

---

## 1. `novel_mappings.py`

This file contains mapping data for each hosting site. When adding a **new novel** or **new hosting site**, you will update:

- **`HOSTING_SITE_DATA`**  
  - `feed_url`: The URL for the feed (e.g., free chapters)
  - `paid_feed_url`: If site has URL for paid feed
  - `comments_feed_url`: If site has URL for comments.
  - `translator`: Your username on that site  
  - `host_logo`: The URL for the hosting site's logo
  - `coin_emoji`: currency used for paid chapters like 🔥 or 🪙
  - `novels`: A dictionary that maps each novel title to:
    - `discord_role_id`: The Discord role ID  
    - `novel_url`: The manual URL for the novel’s main page  
    - `featured_image`: The URL for the novel’s featured image
    - `pub_date_override`: The override for the system's default time of scraping
    - `webhook-only fields`: Contains information needed for [webhook-discord](https://github.com/Cannibal-Turtle/discord-webhook/tree/main) scripts.

> 📦 `pyproject.toml` lets other projects (like the Discord webhook script) install this repo as a package using pip. It tells Python where to find `novel_mappings.py` so the webhook scripts can always pull the latest novel data straight from here 🔄✨.

### Example

```python
HOSTING_SITE_DATA = {
    "Dragonholic": {
        "feed_url": "https://dragonholic.com/feed/manga-chapters/",
        "comments_feed_url": "https://dragonholic.com/comments/feed/",
        "translator": "Cannibal Turtle",
        "host_logo": "https://dragonholic.com/wp-content/uploads/2025/01/Web-Logo-White.png",
        "coin_emoji": "🔥",
        "novels": {
            "Quick Transmigration: The Villain Is Too Pampered and Alluring": {
                "discord_role_id": "<@&1329391480435114005>",
                "novel_url": "https://dragonholic.com/novel/quick-transmigration-the-villain-is-too-pampered-and-alluring/",
                "featured_image": "https://dragonholic.com/wp-content/uploads/2024/08/177838.jpg",
                "pub_date_override": {"hour": 12, "minute": 0, "second": 0}
                # ─── webhook-only fields ───
                "chapter_count": "1184 chapters + 8 extras",
                "last_chapter": "Extra 8",
                "start_date": "31/8/2024",
                "free_feed": "https://cannibal-turtle.github.io/rss-feed/free_chapters_feed.xml",
                "paid_feed": "https://cannibal-turtle.github.io/rss-feed/paid_chapters_feed.xml",
                "custom_emoji":   ":man_supervillain:",
                "discord_role_url":"https://discord.com/channels/1329384099609051136/1329419555600203776/1330466188349800458",
                "history_file":   "tvitpa_history.json"

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
- **`extract_pubdate_from_soup(chap)`** → Parses chapter `<li>` elements to extract absolute or relative publication dates.
- **`novel_has_paid_update_async(session, novel_url)`** → Checks if a novel has a premium (paid) update within the last 7 days.
- **`scrape_paid_chapters_async(session, novel_url, host)`** → Scrapes the paid chapter list from Dragonholic.
- **`format_volume_from_url(url, main_title)`** → Utility to infer volume names from URLs.
- **`split_comment_title_dragonholic(comment_title)`** → Extracts the novel title from the comment title string.
- **`extract_chapter_dragonholic(link)`** → Extracts a readable chapter label from a URL.
> 💡 Note: For Dragonholic paid chapters, volume names are scraped directly from the DOM (e.g., li.parent.has-child > a.has-child). No need to reconstruct them from URLs.
  
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

## 📄 Sample Output (What the Final RSS Feed Looks Like)
Each generated .xml feed (free or paid) will contain structured <item> entries enriched with metadata like volume, chapter name, link, description, translator, Discord role, hosting site, and more.

```
<item>
  <title>Quick Transmigration: The Villain Is Too Pampered and Alluring</title>
  <volume>【Arc 5】The Fake Daughter Will Not Be a Cannon Fodder</volume>
  <chaptername>Chapter 250</chaptername>
  <nameextend>***Uglier Than a Monkey***</nameextend>
  <link>https://dragonholic.com/novel/.../chapter-250/</link>
  <description><![CDATA[A deadly twist awaits in the mirror world...]]></description>
  <category>SFW</category>
  <translator>Cannibal Turtle</translator>
  <discord_role_id><![CDATA[<@&1329XXXXXX>]]></discord_role_id>
  <featuredImage url="https://dragonholic.com/.../cover.jpg"/>
  <coin>🔥 10</coin>
  <pubDate>Fri, 18 Apr 2025 12:00:00 +0000</pubDate>
  <host>Dragonholic</host>
  <hostLogo url="https://dragonholic.com/.../logo.png"/>
  <guid isPermaLink="false">chapter-250-guid</guid>
</item>
```

## NEW: mistmint_state.json & paid_history.json

- `mistmint_state` is a file to manually update all premium chapters of the novels in Mistmint Haven, as the site cannot be scraped nor does it have a paid feed.
- `paid_history.json` is a premature file that keeps track of the last 7-day feed before it merges with the final feed. Necessary due to mistmint's volatile feed log.




