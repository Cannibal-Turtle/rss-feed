# Guide for Updating Novel/Translator Mappings and Host Utilities

This guide explains which files need to be updated whenever a new novel, translator, hosting site, feed, or Discord publishing target is added.

The RSS repo now uses **split TOML mapping files** instead of keeping all novel data directly inside `novel_mappings.py`.

---

## Repository Structure

Important files and folders:

```text
rss-feed/
├─ novel_mappings.py
├─ host_utils.py
├─ free_feed_generator.py
├─ paid_feed_generator.py
├─ comments.py
├─ update_novel_status.py
├─ novel_status_targets.json
├─ mappings/
│  ├─ __init__.py
│  ├─ output_feeds.toml
│  ├─ hosts/
│  │  └─ mistmint_haven.toml
│  └─ novels/
│     ├─ tvitpa.toml
│     ├─ tdlbkgc.toml
│     ├─ hiaflg.toml
│     └─ ...
├─ tools/
│  ├─ publish_single_novel.py
│  └─ publish_membership_update.py
└─ pyproject.toml
```

---

## 1. Mapping Files

### `novel_mappings.py`

`novel_mappings.py` is now the **loader/front door**.

Other scripts and repos can still import:

```python
from novel_mappings import HOSTING_SITE_DATA
```

This keeps existing dependent scripts working, while the actual editable data lives in TOML files under:

```text
mappings/
```

`novel_mappings.py` loads:

```text
mappings/output_feeds.toml
mappings/hosts/*.toml
mappings/novels/*.toml
```

and builds `HOSTING_SITE_DATA` automatically.

---

## 2. Output Feed Config

### `mappings/output_feeds.toml`

This file stores the generated RSS feed URLs.

These are global repo-level feeds, not host-specific feeds.

```toml
free_feed = "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/free_chapters_feed.xml"
paid_feed = "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/paid_chapters_feed.xml"
comments_feed = "https://raw.githubusercontent.com/Cannibal-Turtle/rss-feed/main/aggregated_comments_feed.xml"
```

Novel TOML files use flags like:

```toml
has_free = true
has_paid = true
has_comments = true
```

Then `novel_mappings.py` injects the correct feed URLs automatically.

---

## 3. Host Mapping Files

Host-level data lives in:

```text
mappings/hosts/
```

Example:

```text
mappings/hosts/mistmint_haven.toml
```

Example structure:

```toml
host = "Mistmint Haven"

translator = "Cannibal Turtle"
host_logo = "https://example.com/logo.png"
coin_emoji = "🪙"

# Name of the GitHub secret that stores this host's login token/cookie.
token_secret = "MISTMINT_COOKIE"
```

Host files should contain data shared by all novels on that host.

Examples:

* `host`
* `translator`
* `host_logo`
* `coin_emoji`
* `token_secret`

Do **not** put per-novel data here.

---

## 4. Novel Mapping Files

Novel-level data lives in:

```text
mappings/novels/
```

Each novel gets its own TOML file.

Example:

```text
mappings/novels/amlwc.toml
```

Example:

```toml
host = "Mistmint Haven"

title = "After the Male Leads Went Crazy, They All Turned Into Male Ghosts"
short_code = "AMLWC"

novel_url = "https://mistminthaven.com/novel/after-the-male-leads-went-crazy-they-all-turned-into-male-ghosts/"
novelupdates_url = "https://www.novelupdates.com/series/after-the-male-leads-went-crazy-they-all-turned-into-male-ghosts/"
featured_image = "https://mistminthaven.com/wp-content/uploads/example-cover.jpg"

has_free = true
has_paid = true
has_comments = true

is_nsfw = false
is_membership = false

# Optional display/status fields.
chapter_count = "92 Chapters"
last_chapter = "Chapter 92"
start_date = ""

# Used only by arc checker novels.
# Leave empty if this novel does not use arc tracking.
history_file = ""

# Optional novel-specific embed color.
# Discord bots can use this when config/embeds.json says "paid_chapter": "novel".
discord_color = "#c90016"

custom_description = """
Optional multiline description here.

TOML supports triple-quoted multiline strings, so summaries are easier to paste and edit than JSON.
"""
```

---

## 5. Important Novel Fields

### Required Fields

| Field            | Purpose                                                                  |
| ---------------- | ------------------------------------------------------------------------ |
| `host`           | Must match a host file, e.g. `"Mistmint Haven"`                          |
| `title`          | Novel title used in feeds and status matching                            |
| `short_code`     | Stable short code used across bots and workflows                         |
| `novel_url`      | Main novel page                                                          |
| `featured_image` | Cover image URL                                                          |
| `has_free`       | Whether this novel appears in the free feed                              |
| `has_paid`       | Whether this novel appears in the paid feed                              |
| `has_comments`   | Whether this novel appears in the comments feed                          |
| `is_nsfw`        | Whether this novel should be categorized as NSFW                         |
| `is_membership`  | Whether this novel is currently membership-only/available for membership |

### Optional Fields

| Field                | Purpose                                                          |
| -------------------- | ---------------------------------------------------------------- |
| `novelupdates_url`   | NovelUpdates page URL                                            |
| `chapter_count`      | Display text for completion/status cards                         |
| `last_chapter`       | Completion checker target                                        |
| `start_date`         | Used to calculate “After X of updates...” in completion messages |
| `history_file`       | Arc checker history file                                         |
| `discord_color`      | Novel-specific embed color                                       |
| `theme_color`        | Future/alias field for novel-specific color                      |
| `custom_description` | Multiline manual description                                     |

---

## 6. Empty Optional Fields

These are safe to leave empty:

```toml
start_date = ""
history_file = ""
chapter_count = ""
```

Notes:

* `start_date = ""` means completion messages skip the “After X of updates...” phrase.
* `history_file = ""` means arc tracking should skip that novel.
* `last_chapter = ""` means completion checking should skip that novel.

For safety, scripts should read optional strings like:

```python
start_date = (details.get("start_date", "") or "").strip()
history_file = (details.get("history_file", "") or "").strip()
```

---

## 7. NSFW and Membership Tracking

NSFW and membership are now stored per novel in TOML.

### NSFW

Use:

```toml
is_nsfw = true
```

`get_nsfw_novels()` is now derived from TOML data.

Do **not** manually maintain a hardcoded title list unless absolutely needed.

### Membership

Use:

```toml
is_membership = true
```

`get_membership_novels()` is now derived from TOML data.

`tools/publish_membership_update.py` automatically updates the matching novel TOML file from:

```toml
is_membership = false
```

to:

```toml
is_membership = true
```

The workflow should commit:

```bash
git add mappings/novels/*.toml
```

not `novel_mappings.py`.

---

## 8. Helper Functions from `novel_mappings.py`

The loader exposes helper functions used by RSS scripts and Discord bots.

Useful helpers include:

```python
get_nsfw_novels()
get_membership_novels()

get_novel_details_by_short_code(short_code)
find_novel_by_short_code(short_code)

novel_has_free_chapters(host, novel_title)
novel_has_paid_chapters(host, novel_title)
novel_has_comments_feed(host, novel_title)

short_code_has_free_chapters(short_code)
short_code_has_paid_chapters(short_code)
short_code_has_comments_feed(short_code)
```

Short-code helpers are preferred for cross-repo workflows.

---

## 9. `pyproject.toml`

`pyproject.toml` lets other projects install this repo as a package.

This allows other repos, such as `discord-webhook` and `mistmint-discord`, to import:

```python
from novel_mappings import HOSTING_SITE_DATA
```

Make sure TOML mapping files are included as package data:

```toml
[tool.setuptools.package-data]
mappings = [
  "hosts/*.toml",
  "novels/*.toml",
  "output_feeds.toml",
]
```

If Python versions below 3.11 need support, include:

```toml
dependencies = [
  "tomli>=2.0.1; python_version < '3.11'",
]
```

---

## 10. `host_utils.py`

`host_utils.py` manages host-specific scraping and parsing logic.

It keeps each host’s weird chapter/title/date behavior separate from the main feed generators.

### Common Host Utility Functions

Host utility dictionaries may include functions like:

```python
split_title
chapter_num
clean_description
extract_pubdate_from_soup
novel_has_paid_update_async
scrape_paid_chapters_async
format_volume_from_url
split_comment_title
extract_chapter
```

### Dispatcher

Use:

```python
get_host_utils("Mistmint Haven")
```

or:

```python
get_host_utils(host)
```

The dispatcher returns the correct function set for that host.

When adding a new host, add that host’s functions and register them in `get_host_utils(host)`.

---

## Summary Checklist

### Add a New Novel on an Existing Host

1. Create a new TOML file in:

   ```text
   mappings/novels/
   ```

2. Add required fields:

   ```toml
   host = "Mistmint Haven"
   title = "Novel Title"
   short_code = "CODE"
   novel_url = "https://..."
   featured_image = "https://..."

   has_free = true
   has_paid = true
   has_comments = true

   is_nsfw = false
   is_membership = false
   ```

3. Fill optional fields when available:

   ```toml
   novelupdates_url = ""
   chapter_count = ""
   last_chapter = ""
   start_date = ""
   history_file = ""
   discord_color = ""
   custom_description = """
   """
   ```

4. If the novel is NSFW:

   ```toml
   is_nsfw = true
   ```

5. If the novel is membership:

   ```toml
   is_membership = true
   ```

6. Add Discord role/emoji/thread data in the Discord repo, not here.

---

### Add a New Hosting Site

1. Create a new TOML file in:

   ```text
   mappings/hosts/
   ```

2. Add host-level metadata:

   ```toml
   host = "Host Name"
   translator = "Translator Name"
   host_logo = "https://..."
   coin_emoji = "🪙"
   token_secret = ""
   ```

3. Add host-specific logic in `host_utils.py`.

4. Update `get_host_utils(host)` to return the new host’s utility dictionary.

5. Add novel TOML files under `mappings/novels/`.

---

## 📄 Sample Output: RSS Feed Item

Each generated `.xml` feed contains structured `<item>` entries enriched with metadata like title, volume, chapter, chapter name, link, description, translator, hosting site, short code, cover image, and more.

Example:

```xml
<item>
  <title>After the Male Leads Went Crazy, They All Turned Into Male Ghosts</title>
  <volume>Arc 1: The Charming Landlord Is Too Hard to Handle</volume>
  <chapter>Chapter 2</chapter>
  <chaptername>***1.2***</chaptername>
  <link>https://mistminthaven.com/novel/.../chapter-2/</link>
  <description><![CDATA[A short chapter summary or excerpt...]]></description>
  <category>SFW</category>
  <translator>Cannibal Turtle</translator>
  <short_code>AMLWC</short_code>
  <featuredImage url="https://mistminthaven.com/.../cover.jpg"/>
  <coin>🪙 5</coin>
  <pubDate>Fri, 18 Apr 2025 12:00:00 +0000</pubDate>
  <host>Mistmint Haven</host>
  <hostLogo url="https://mistminthaven.com/.../logo.png"/>
  <guid isPermaLink="false">amlwc-chapter-2</guid>
</item>
```

---

## Feed Sorting

Feed items are sorted newest first by `pubDate`.

When multiple items have the same timestamp, the tie-breaker is alphabetical instead of mapping insertion order.

Tie-breakers:

```text
1. pubDate newest first
2. host/title alphabetical
3. chapter number newest first within the same novel/date
```

This avoids depending on the order of novels inside mapping files.

---

## 🆕 Mistmint Haven Quick Setup

### Modes

* **API mode** when `MISTMINT_FORCE_STATE="0"`.
* **STATE mode** when `MISTMINT_FORCE_STATE="1"` or no cookie is available.

STATE mode accepts manual paid chapter entry via:

```text
manual_scripts/mistmint_state.json
```

and updates:

```text
manual_scripts/paid_history.json
```

If mode is switched, clear `paid_history.json` and update `mistmint_state.json`.

---

### Mapping

Host-level data goes in:

```text
mappings/hosts/mistmint_haven.toml
```

Example:

```toml
host = "Mistmint Haven"
translator = "Cannibal Turtle"
host_logo = "https://..."
coin_emoji = "🪙"
token_secret = "MISTMINT_COOKIE"
```

Novel-level data goes in:

```text
mappings/novels/*.toml
```

Example:

```toml
host = "Mistmint Haven"
title = "Novel Title"
short_code = "CODE"
novel_url = "https://..."
featured_image = "https://..."

has_free = true
has_paid = true
has_comments = true

is_nsfw = false
is_membership = false
```

---

### Required Repo Secrets

| Secret                   | Purpose                           |
| ------------------------ | --------------------------------- |
| `MISTMINT_COOKIE`        | Logged-in cookie/token string     |
| `PAT_GITHUB`             | Cross-repo dispatch to other bots |
| `DISCORD_BOT_TOKEN`      | Discord bot authentication        |
| `DISCORD_MOD_CHANNEL_ID` | Alert/mod channel posts           |

---

## Token-Expiry Alerts

1. Hourly job runs `comments.py`.
2. If a host has `token_secret`, the script checks the matching environment variable.
3. If the token is expiring soon, it calls `maybe_dispatch_token_alerts`.
4. That triggers `send_token_alert.yml`.
5. `send_token_alert.py` posts the alert.
6. `.token_alert_state.json` stores the last `exp` per `(host, token_secret)` so alerts do not spam hourly.

Example host config:

```toml
token_secret = "MISTMINT_COOKIE"
```

The actual cookie/token must be available as an environment variable with that name.

---

## NSFW Catch Update

The feed generator can mark items as NSFW if `<chapter>` or `<chaptername>` contains NSFW keywords.

### Will match, not case-sensitive

* `(NSFW)`
* `(nsfw scene)`
* `(extended nsfw)`
* `(R-18)`
* `(r18)`
* `(ver. R-18+ patch)`
* `(R-18+)`
* `(18+)`
* `(H)`
* `(HH)`
* `(HHH)`
* `(bonus H chapter)`

Novel-wide NSFW status should still be set in the novel TOML:

```toml
is_nsfw = true
```

---

## 🆕 Automatic Novel Status Updater

This system keeps existing Discord novel cards up-to-date whenever new free chapters are announced.

It works across repositories and servers.

---

## 🔁 Overview: How Status Auto-Updates Work

When a new free chapter is detected and posted:

1. **Free Chapters Bot**
   Usually in `discord-webhook`.

   It posts the chapter announcement to Discord and collects:

   * Novel title
   * Host

2. **rss-feed Repo**
   Receives the dispatch and runs the status updater script.

   It resolves:

   ```text
   title + host
      ↓
   HOSTING_SITE_DATA
      ↓
   short_code
   ```

3. **Target Discord Messages**
   Are edited in-place.

   Formatting, emojis, and layout are preserved.

   No reposts. No duplication.

---

## 📍 Where the Mapping Happens

Short codes do not need to be passed between repos for status updates.

Resolution happens inside the updater Python script, using `HOSTING_SITE_DATA`.

```text
Title + Host
   ↓
HOSTING_SITE_DATA
   ↓
short_code
```

Because `HOSTING_SITE_DATA` is still exposed by `novel_mappings.py`, dependent scripts can keep importing it even though the source data is now TOML.

---

## 📄 Status Target Mapping

The updater uses:

```text
novel_status_targets.json
```

This file stores existing Discord messages that should be edited.

Example:

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
  "AMLWC": [
    {
      "channel_id": "123456789",
      "message_id": "123456789"
    }
  ]
}
```

### Notes

* A single novel can have multiple targets.
* Targets can be in different servers, channels, or threads.
* Forum threads are supported because Discord treats threads as channels internally.

---

## ✏️ What the Updater Changes

### Updated

Only the status field value is updated.

Examples:

```text
*Ongoing*
*Completed*
Next free chapter live <t:UNIX:R>
All chapters are now free
```

### Not Touched

The updater does not change:

* Title
* Emojis
* Role field
* Links
* Thumbnail
* Embed color
* Other formatting

If a target embed does not have the expected status field, the updater skips it safely.

---

## 🧠 How Status Is Calculated

The updater:

1. Fetches paid/free chapter data.
2. Determines whether all paid chapters are released.
3. Determines whether future free chapters exist.
4. Produces one of:

```text
*Completed*
*Ongoing*
Next free chapter live <t:…:R>
All chapters are now free
_Free release schedule not available_
```

---

## 🔐 Required Secrets for Cross-Repo Status Updates

Because this system triggers across repositories, a PAT is required.

| Secret              | Repo                                   | Purpose                             |
| ------------------- | -------------------------------------- | ----------------------------------- |
| `PAT_GITHUB`        | Source repo, usually `discord-webhook` | Dispatch events to `rss-feed`       |
| `DISCORD_BOT_TOKEN` | `rss-feed`                             | Edit existing Discord messages      |
| `MISTMINT_COOKIE`   | `rss-feed`                             | Paid/free API access, if applicable |

`GITHUB_TOKEN` is not sufficient for cross-repo dispatch.

---

## 🧩 Adding a New Novel With Auto-Updates

To enable automatic status updates:

1. Add the novel TOML file in:

   ```text
   mappings/novels/
   ```

2. Assign a unique:

   ```toml
   short_code = "CODE"
   ```

3. Run the manual publishing workflow to create/register the novel card.

4. Confirm the message was added to:

   ```text
   novel_status_targets.json
   ```

---

## 🆕 Manual Novel Card + Membership Update Tools

These tools are used when manually publishing Discord announcement cards for novels.

They use:

```text
mappings/novels/*.toml
novel_mappings.py
novel_status_targets.json
```

The Discord-specific role ID, custom emoji, and role URL should live in the Discord repo, not in `rss-feed`.

For example:

```text
discord-webhook/config/novel_discord_map.toml
```

---

## 📌 `tools/publish_single_novel.py`

This script manually publishes a normal novel status embed.

It is usually used for first-time setup of a novel card, so future status updates know which Discord message to edit.

### What it does

* Takes a novel `short_code`.
* Finds the novel through `novel_mappings.py`.
* Posts a novel status embed to the private/archive channel.
* Optionally posts to a forum/thread if a thread ID is provided.
* Registers the posted message ID in `novel_status_targets.json`.

### Channel Behavior

The private/archive channel is the default posting target.

If a forum/thread ID is provided:

```text
numeric thread ID
```

the script posts to both:

```text
private/archive channel
forum/thread
```

If the thread value is:

```text
N/A
```

the script posts only to the private/archive channel.

Use `N/A` intentionally when a novel has no forum/thread.

---

## 🎟 `tools/publish_membership_update.py`

This script manually publishes a membership announcement.

It is used when a novel becomes available for membership.

### What it does

* Takes a novel `short_code`.
* Takes a required membership `banner_url`.
* Finds the novel through `novel_mappings.py`.
* Posts the membership announcement to the private/news channel.
* Optionally posts to a forum/thread if a thread ID is provided.
* Marks the novel TOML as membership.

It changes:

```toml
is_membership = false
```

to:

```toml
is_membership = true
```

in the matching file under:

```text
mappings/novels/
```

It does **not** update a hardcoded `get_membership_novels()` list in `novel_mappings.py`.

---

## Required Workflow Inputs

### `publish_single_novel.yml`

```yaml
short_code:
  description: "Novel short code, e.g. TVITPA, TDLBKGC, AMLWC"
  required: true
  type: string

forum_post_id:
  description: "Optional Discord forum/thread ID. Use N/A if none."
  required: true
  type: string
```

### `publish_membership_update.yml`

```yaml
short_code:
  description: "Novel short code, e.g. TVITPA, TDLBKGC, AMLWC"
  required: true
  type: string

banner_url:
  description: "Membership banner image URL"
  required: true
  type: string

forum_post_id:
  description: "Optional Discord forum/thread ID. Use N/A if none."
  required: true
  type: string
```

There is no default membership banner image. A banner URL must be entered every time.

---

## Posting Behavior

| Thread Value       | Meaning                               |
| ------------------ | ------------------------------------- |
| Numeric thread ID  | Post to private channel + that thread |
| `"N/A"`            | Post only to private channel          |
| Empty value        | Stop with error                       |
| Missing short code | Stop with error                       |

This prevents accidental silent private-only posting when a thread ID was simply forgotten.

---

## 🧾 Membership Tracking

Membership is tracked in the matching novel TOML file:

```toml
is_membership = true
```

The helper:

```python
get_membership_novels()
```

returns membership novels dynamically from TOML.

Do not manually maintain a separate membership list.

---

## 🔁 Related Workflows

### `publish_single_novel.yml`

Used to publish normal novel status cards.

Input:

```yaml
short_code
forum_post_id
```

Result:

* Posts the novel card.
* Updates `novel_status_targets.json`.
* Commits the updated target mapping.

---

### `publish_membership_update.yml`

Used to publish membership announcements.

Inputs:

```yaml
short_code
banner_url
forum_post_id
```

Result:

* Posts the membership update.
* Updates the matching novel TOML file.
* Commits the changed TOML file.

Commit target should include:

```bash
git add mappings/novels/*.toml
```

---

## ✅ Manual Publishing Checklist

When adding a new novel:

1. Create a novel TOML file in:

   ```text
   mappings/novels/
   ```

2. Add a unique:

   ```toml
   short_code = "CODE"
   ```

3. Add Discord role/emoji/role URL data in the Discord repo:

   ```text
   discord-webhook/config/novel_discord_map.toml
   ```

4. Run `publish_single_novel.yml`.

5. Confirm `novel_status_targets.json` was updated.

6. If the novel enters membership, run `publish_membership_update.yml` with:

   * `short_code`
   * `banner_url`
   * `forum_post_id` or `N/A`

7. Confirm the novel TOML now has:

   ```toml
   is_membership = true
   ```

---

## ✅ Design Guarantees

* `novel_mappings.py` remains import-compatible for dependent scripts.
* Actual mapping data lives in TOML files.
* Novel descriptions can use TOML multiline strings.
* NSFW status comes from `is_nsfw`.
* Membership status comes from `is_membership`.
* Output feed URLs are centralized in `mappings/output_feeds.toml`.
* Paid/free feed sorting no longer depends on mapping insertion order.
* `history_file = ""` safely means no arc tracking.
* `start_date = ""` safely means no duration phrase in completion messages.
* `update_novel_status.py` edits existing Discord messages instead of reposting.
* `novel_status_targets.json` stores message targets by short code.
* Discord role IDs, custom emojis, and role URLs belong in Discord bot repos, not in `rss-feed`.

---

## Workflow Overview

```text
New free chapter announced
   ↓
Discord bot posts announcement
   ↓
Cross-repo dispatch to rss-feed
   ↓
rss-feed resolves title + host → short_code
   ↓
update_novel_status.py recalculates status
   ↓
Existing Discord novel cards are edited in-place
```

---

## Example Result

The final Discord status card is created once, then updated automatically when new free chapters are posted.

The status updater preserves the existing card layout and only edits the status field.

<img width="441" height="197" alt="image" src="https://github.com/user-attachments/assets/36e3c6e0-5dfd-4960-921f-e9c1cf3dd96c" />
