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
- **`split_title_dragonholic(full_title)`** → Splits a chapter title into `main_title`, `chapter`, and `chaptername`.  
- **`chapter_num_dragonholic(chapter)`** → Extracts numeric values from chapter names.  
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
  <chapter>Chapter 250</chapter>
  <chaptername>***Uglier Than a Monkey***</chaptername>
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

## 🆕 Mistmint Haven (Quick Setup) [UPDATE 4.0]

### Modes
- **API mode** when `MISTMINT_FORCE_STATE="0"`. Runs on schedule
- **STATE mode** when `MISTMINT_FORCE_STATE="1"` **or** no cookie. Accepts manual paid chapter entry via `manual_scripts/mistmint_state.json` and updates `manual_scripts/paid_history.json`. If mode is switched, clear `paid_history.json` and update `mistmint_state.json`.

### Mapping (`novel_mappings.py`)
Add:
```python
HOSTING_SITE_DATA["Mistmint Haven"] = {
  "token_secret": "MISTMINT_COOKIE",   # name of the repo secret to read at runtime
}
```

### Required repo secrets
- `MISTMINT_COOKIE` – logged-in cookie string  
- `PAT_GITHUB` – for repo dispatch to other bots  
- `DISCORD_BOT_TOKEN`, `DISCORD_MOD_CHANNEL_ID` – for alert posts

---

## Token-Expiry Alerts

1. Hourly job runs `comments.py` → calls `maybe_dispatch_token_alerts` if token is expiring → `send_token_alert.yml` → `send_token_alert.py`.
2. For each host with `token_secret`, it reads that env var, decodes JWT `exp`, and if `≤ 1 day`, fires:
   `repository_dispatch` → `event_type: token-expiring`.
3. `.token_alert_state.json` stores the last `exp` per `(host, token_secret)` so you aren’t spammed hourly.

---

## NSFW Catch Update

Now also updates `<category>` if `<chapter>` and `<chaptername>` has these keywords:

### Will match (✅) - Not case sensitive

- (NSFW) , (nsfw scene) , (extended nsfw)
- (R-18) , (r18) , (ver. R-18+ patch) , (R-18+)
- (18+)
- (H) , (HH) , (HHH) , (bonus H chapter)

---

## 🆕 Automatic Novel Status Updater (Cross-Bot Integration)

This system keeps **existing Discord novel cards up-to-date** whenever new free chapters are announced, without reposting or changing formatting.

It is designed to work **across repositories and servers**.

---

## 🔁 Overview: How Status Auto-Updates Work

When a **new free chapter** is detected and posted:

1. **Free Chapters Bot** (discord-webhook repo)  
   - Posts the chapter announcement to Discord  
   - Collects:
     - Novel **title**
     - **Host** (e.g. Mistmint Haven, Dragonholic)
   - Fires a `repository_dispatch` event to the **rss-feed repo**

2. **rss-feed Repo**  
   - Receives the dispatch
   - Runs the **status updater script**
   - Resolves:
     ```
     title + host → short_code (via HOSTING_SITE_DATA)
     ```
   - Updates only the **Status field** of existing embeds

3. **Target Discord Messages**  
   - Are edited in-place
   - Formatting, emojis, and layout are preserved
   - No reposts, no duplication

---

## 📍 Where the Mapping Happens (Important)

> 🔑 **Short codes are NOT passed between repos**

Resolution happens **only inside the updater Python script**, using mappings.

```text
Title + Host
   ↓
HOSTING_SITE_DATA
   ↓
short_code
```

---

## 📄 Status Target Mapping

The updater uses a static map of **existing Discord messages** that should be updated.

Example (`novel_status_targets.json`):

```json
{
  "TVITPA": [
    {
      "channel_id": "123456789",
      "message_id": "123456789"
    }
  ],
  "TDLBKGC": [
    {
      "channel_id": "123456789",
      "message_id": "123456789"
    }
  ],
  "ATVHE": [
    {
      "channel_id": "123456789",
      "message_id": "123456789"
    }
  ]
}
```

### Notes
- A **single novel can have multiple targets**  
  (e.g. different servers, channels, or forum posts)
- Forum thread messages are supported  
  (threads are just channels internally)

---

## ✏️ What the Updater Changes (and What It Doesn’t)

### ✅ Updated
- **Status field value only**
  - `*Ongoing*` / `*Completed*`
  - `Next free chapter live <t:UNIX:R>`
  - `All chapters are now free`

### ❌ Not touched
- Title
- Emojis
- Role field (if present)
- Links
- Thumbnail
- Embed color
- Any other formatting

> If a server’s embed **does not have a Role field**, the updater skips it safely.

---

## 🧠 How Status Is Calculated

The updater:
1. Fetches the **paid/free chapter API**
2. Determines:
   - Whether **all paid chapters are released**
   - Whether **future free chapters exist**
3. Produces one of:
   - `*Completed*`
   - `*Ongoing*`
   - `Next free chapter live <t:…:R>`
   - `All chapters are now free`
   - `_Free release schedule not available_`

---

## 🔐 Required Secrets (Cross-Repo)

Because this system triggers **across repositories**, a PAT is required.

### Required Secrets
| Secret | Repo | Purpose |
|---|---|---|
| `PAT_GITHUB` | **Source repo (in this case discord-webhook)** | Dispatch events to rss-feed |
| `DISCORD_BOT_TOKEN` | rss-feed | Edit existing Discord messages |
| `MISTMINT_COOKIE` | rss-feed | Paid/free API access (if applicable) |

> ⚠️ `GITHUB_TOKEN` is **not sufficient** for cross-repo dispatch.

---

## 🧩 Adding a New Novel (With Auto-Updates)

To enable automatic status updates for a new novel:

1. Add the novel to `HOSTING_SITE_DATA`
2. Assign it a unique `short_code`
3. Add its Discord message(s) to `novel_status_targets.json`

---

## 🆕 Manual Novel Card + Membership Update Tools

These tools are used when manually publishing Discord announcement cards for novels.

They work together with `novel_mappings.py`, `NOVEL_META`, and `novel_status_targets.json`.

---

## 📌 `tools/publish_single_novel.py`

This script manually publishes a normal novel status embed.

It is usually used for the first-time setup of a novel card, so that future status updates know which Discord message to edit.

### What it does

- Takes a novel `short_code`
- Finds the novel in `HOSTING_SITE_DATA`
- Posts a novel status embed to:
  - the private/archive channel
  - the novel forum/thread, if one exists
- Registers the posted message ID in `novel_status_targets.json`

### Important channel behavior

The script uses:

```python
ARCHIVE_CHANNEL_ID = 1463476725253144751
```

as the private/archive channel.

It also checks `NOVEL_META`:

```python
NOVEL_META = {
    "TVITPA": {"forum_post_id": "1444214902322368675"},
    "TDLBKGC": {"forum_post_id": "1438462596381413417"},
    "BOE": {"forum_post_id": "N/A"},
}
```

### `NOVEL_META` rules

| Value | Meaning |
|---|---|
| Numeric `forum_post_id` | Post to private/archive channel + that thread |
| `"N/A"` | Post only to the private/archive channel |
| Missing short code | Stop with error, because the mapping may have been forgotten |
| Empty `forum_post_id` | Stop with error |

Use `"N/A"` intentionally when a novel has no Mistmint Haven forum/thread.

Example:

```python
"BOE": {"forum_post_id": "N/A"},
```

This prevents accidental silent private-only posting when a thread ID was simply forgotten.

---

## 🎟 `tools/publish_membership_update.py`

This script manually publishes a Discord Components V2 membership announcement.

It is used when a novel becomes available for membership.

### What it does

- Takes a novel `short_code`
- Takes a required membership `banner_url`
- Finds the novel in `HOSTING_SITE_DATA`
- Reads `NOVEL_META` from `tools/publish_single_novel.py`
- Posts the membership announcement to:
  - the private/news channel
  - the novel forum/thread, if one exists
- Adds the novel title to `get_membership_novels()` in `novel_mappings.py`

### Required workflow inputs

The GitHub workflow requires:

```yaml
short_code:
  description: "Novel short code, e.g. TVITPA, TDLBKGC, ATVHE"
  required: true
  type: string

banner_url:
  description: "Membership banner image URL"
  required: true
  type: string
```

There is no default banner image. A banner URL must be entered every time.

### Posting behavior

The script always posts first to:

```python
NEWS_CHANNEL_ID = 1330049962129489930
```

Then it checks `NOVEL_META`.

| Value | Meaning |
|---|---|
| Numeric `forum_post_id` | Post to private/news channel + that thread |
| `"N/A"` | Post only to the private/news channel |
| Missing short code | Stop with error |
| Empty `forum_post_id` | Stop with error |

Example:

```python
"BOE": {"forum_post_id": "N/A"},
```

means the membership update will only post to the private/news channel.

---

## 🧾 Membership Tracking in `novel_mappings.py`

When `publish_membership_update.py` runs successfully, it automatically updates `novel_mappings.py`.

It adds or updates:

```python
def get_membership_novels():
    """Returns the list of novels currently available for membership."""
    return [
        "Novel Title Here",
    ]
```

This works like `get_nsfw_novels()`, but for membership novels.

Do not manually add this function unless needed. The membership publish script can create it automatically.

---

## 🔁 Related Workflows

### `publish_single_novel.yml`

Used to publish normal novel status cards.

Input:

```yaml
short_code
```

Result:

- Posts the novel card
- Updates `novel_status_targets.json`
- Commits the updated target mapping

### `publish_membership_update.yml`

Used to publish membership announcements.

Inputs:

```yaml
short_code
banner_url
```

Result:

- Posts the membership update
- Updates `novel_mappings.py`
- Commits the updated membership list

---

## ✅ Manual Publishing Checklist

When adding a new novel:

1. Add the novel to `HOSTING_SITE_DATA`
2. Add a unique `short_code`
3. Add the short code to `NOVEL_META`
   - use a real thread ID if the novel has one
   - use `"N/A"` if it has no thread
4. Run `publish_single_novel.yml` to create/register the normal novel card
5. If the novel enters membership, run `publish_membership_update.yml` with:
   - `short_code`
   - membership banner URL

---

## ✅ Design Guarantees

- `tools/publish_single_novel.py` can serve as template for first run.
- `Update `NOVEL_META` in `tools/publish_single_novel.py` for every new novel; Color = embed color; Omit forum_post_id if it doesn't belong to any forum. Example:
```
  NOVEL_META = {
    "TVITPA": {"color": "#f8d8c9", "forum_post_id": "1444214902322368675"},
```
- `update_novel_status.py` looks for the `status` field for updates.
- `Role` field only shows for `ARCHIVE_CHANNEL_ID` listed and is omitted unless message is sent to that channel.
- env needed:
> ⚠️ Cookie must be available as the environment variable named MISTMINT_COOKIE (or whatever name you put in `token_secret` under `HOSTING_SITE_DATA`)

- Run the `publish_single_novel.yml` script with a shortcode and channel ID for the first run, and it will update `novel_status_targets.json` automatically.
- `update_novel_status.py` trigerred automatically by `update_novel_status.yml` everytime **new free chapter** is announced, will use the shortcode, channel, and message ID stored in `novel_status_targets.json`.
- Workflow:
  
```
Discord free chapter announcement
   ↓
Trigger GitHub event
   ↓
Recompute novel status
   ↓
Edit existing embeds
```

---

Result:

<img width="441" height="197" alt="image" src="https://github.com/user-attachments/assets/36e3c6e0-5dfd-4960-921f-e9c1cf3dd96c" />
