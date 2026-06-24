# RSS Feed Mapping, Scraper, and Publishing Tools

This repo owns the **source/data layer** for the novel announcement system.

It stores novel and host metadata, generates RSS feeds, checks host updates, sends a few direct Discord reports/tools, and provides the installable mapping package used by the Discord announcement repos.

The repo now uses **split TOML mapping files** instead of keeping all novel data directly inside `novel_mappings.py`.

---

## Repository Structure

Important files and folders:

```text
rss-feed/
├─ .github/workflows/
│  ├─ update_free_feed.yml
│  ├─ update_paid_feed.yml
│  ├─ update_comments.yml
│  ├─ update_novel_status.yml
│  ├─ publish_single_novel.yml
│  ├─ publish_membership_update.yml
│  ├─ monthly_revenue.yml
│  ├─ nu_weekly_readers.yml
│  └─ send_token_alert.yml
├─ novel_mappings.py
├─ mappings/
│  ├─ __init__.py
│  ├─ output_feeds.toml
│  ├─ hosts/
│  │  └─ mistmint_haven.toml
│  └─ novels/
│     ├─ amlwc.toml
│     ├─ atvhe.toml
│     ├─ ec.toml
│     ├─ hiaflg.toml
│     ├─ tdlbkgc.toml
│     ├─ tvitpa.toml
│     └─ wsmsc.toml
├─ host_utils/
│  ├─ __init__.py
│  ├─ host_dragonholic.py
│  ├─ host_nu_comments.py
│  ├─ host_titv.py
│  └─ mistmint_haven/
│     ├─ __init__.py
│     ├─ common.py
│     ├─ client.py
│     ├─ free_chapters.py
│     ├─ paid_chapters.py
│     └─ comments.py
├─ free_feed_generator.py
├─ paid_feed_generator.py
├─ comments.py
├─ message_renderer.py
├─ message_templates/
│  ├─ membership_update.toml
│  ├─ nu_weekly_readers.toml
│  ├─ publish_single_novel.toml
│  ├─ revenue_report.toml
│  └─ token_alert.toml
├─ novelupdates/
│  ├─ nu_weekly_readers.py
│  └─ nu_readers.json
├─ revenue/
│  ├─ report.py
│  ├─ state.json
│  └─ hosts/
├─ token/
│  ├─ send_token_alert.py
│  └─ token_alert_state.json
├─ tools/
│  ├─ audit_dead_host_utils.py
│  ├─ publish_membership_update.py
│  ├─ publish_single_novel.py
│  └─ update_novel_status.py
├─ free_chapters_feed.xml
├─ paid_chapters_feed.xml
├─ aggregated_comments_feed.xml
├─ novel_status_targets.json
├─ requirements.txt
├─ pyproject.toml
└─ README.md
```

---

## What This Repo Produces

Generated RSS files:

```text
free_chapters_feed.xml
paid_chapters_feed.xml
aggregated_comments_feed.xml
```

These are read by:

```text
discord-webhook
mistmint-discord
```

The RSS files are the bridge between scraping/API logic and Discord announcements.

---

## Mapping Files

### `novel_mappings.py`

`novel_mappings.py` is the **loader/front door**.

Other scripts and repos can still import:

```python
from novel_mappings import HOSTING_SITE_DATA
```

This keeps dependent scripts working while the actual editable data lives under:

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

## Output Feed Config

### `mappings/output_feeds.toml`

This file stores generated RSS feed URLs.

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

## Host Mapping Files

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
ticket_emoji = "🎟️"

free_chapters_source = "feed"
paid_chapters_source = "api"
chapter_mode = "auto"
comments_api_url = "https://api.example.com/..."

# Name of the GitHub secret that stores this host's login token/cookie.
token_secret = "MISTMINT_COOKIE"
```

Host files should contain data shared by all novels on that host.

Examples:

- `host`
- `translator`
- `host_logo`
- `coin_emoji`
- `ticket_emoji`
- feed/API mode settings
- `comments_api_url`
- `token_secret`

Do **not** put per-novel data here.

---

## Novel Mapping Files

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

chapter_count = "93 Chapters"
last_chapter = "Chapter 93"
start_date = ""

# Used only by arc checker novels.
# Leave empty if this novel does not use arc tracking.
history_file = ""

# Optional novel-specific embed color for Discord repos.
discord_color = "#c90016"

custom_description = """
Optional multiline description here.

TOML supports triple-quoted multiline strings, so summaries are easier to paste and edit than JSON.
"""
```

---

## Important Novel Fields

### Required Fields

| Field | Purpose |
| --- | --- |
| `host` | Must match a host file, e.g. `"Mistmint Haven"` |
| `title` | Novel title used in feeds and status matching |
| `short_code` | Stable short code used across bots and workflows |
| `novel_url` | Main novel page |
| `featured_image` | Cover image URL |
| `has_free` | Whether this novel appears in the free feed |
| `has_paid` | Whether this novel appears in the paid feed |
| `has_comments` | Whether this novel appears in the comments feed |
| `is_nsfw` | Whether this novel should be categorized as NSFW |
| `is_membership` | Whether this novel is currently membership-only/available for membership |

### Optional Fields

| Field | Purpose |
| --- | --- |
| `novelupdates_url` | Novel Updates page URL |
| `chapter_count` | Display text for completion/status cards |
| `last_chapter` | Completion checker target |
| `start_date` | Used to calculate “After X of updates...” in completion messages |
| `history_file` | Arc checker history file |
| `discord_color` | Novel-specific embed color for Discord repos |
| `theme_color` | Optional alternate novel color field |
| `custom_description` | Multiline description for manual publishing/status cards |

---

## Empty Optional Fields

Use empty strings instead of deleting optional fields when you want scripts to safely skip related behavior.

```toml
start_date = ""
history_file = ""
```

Meaning:

| Field | Empty Behavior |
| --- | --- |
| `start_date = ""` | Completion announcement omits the duration phrase |
| `history_file = ""` | Arc checker skips arc tracking for the novel |

---

## NSFW and Membership Tracking

### NSFW

NSFW is controlled in the novel TOML:

```toml
is_nsfw = true
```

This can flow into RSS categories and Discord announcements.

### Membership

Membership status is controlled in the novel TOML:

```toml
is_membership = true
```

The manual membership tool can update this automatically when a novel is announced as membership-available.

---

## Helper Functions from `novel_mappings.py`

Downstream repos can use:

```python
from novel_mappings import HOSTING_SITE_DATA
```

and helpers such as:

```python
get_novel_details_by_short_code(short_code)
find_novel_by_short_code(short_code)
short_code_has_free_chapters(short_code)
short_code_has_paid_chapters(short_code)
short_code_has_comments_feed(short_code)
resolve_short_code(title, host)
```

Short codes are the stable bridge between this repo and the Discord repos.

---

## Installable Package

`pyproject.toml` makes this repo installable as:

```text
cannibal-turtle-rss-feed
```

Install from GitHub:

```bash
pip install --upgrade git+https://github.com/Cannibal-Turtle/rss-feed.git@main
```

The package currently installs:

```text
novel_mappings.py
mappings/
```

including:

```text
mappings/hosts/*.toml
mappings/novels/*.toml
mappings/output_feeds.toml
```

It is mainly a **shared mapping package** for the Discord repos.

The scraper/feed engine files such as `host_utils/`, `tools/`, and feed generator scripts are part of the repo, but are not currently packaged by `pyproject.toml` unless packaging is expanded.

---

## Requirements

Install local script dependencies with:

```bash
pip install -r requirements.txt
```

Current main dependencies:

```text
feedparser
PyRSS2Gen
aiohttp
beautifulsoup4
requests
```

Some workflows/scripts may also install:

```text
discord.py
python-dateutil
tomli
```

`tomli` is only needed below Python 3.11.

---

## Host Utilities

Host-specific scraper/API logic lives in:

```text
host_utils/
```

Current shape:

```text
host_utils/
├─ __init__.py
├─ host_dragonholic.py
├─ host_nu_comments.py
├─ host_titv.py
└─ mistmint_haven/
   ├─ __init__.py
   ├─ common.py
   ├─ client.py
   ├─ free_chapters.py
   ├─ paid_chapters.py
   └─ comments.py
```

`host_utils/__init__.py` is the host registry/dispatcher.

Use:

```python
from host_utils import get_host_utils

utils = get_host_utils("Mistmint Haven")
```

The Mistmint implementation is split into:

| File | Purpose |
| --- | --- |
| `common.py` | Shared helpers, parsing, diagnostics, settings, state helpers |
| `client.py` | Mistmint API/client helpers |
| `free_chapters.py` | Free chapter feed/API logic |
| `paid_chapters.py` | Paid chapter scraping/API/update logic |
| `comments.py` | Comments, replies, sticker/comment link logic |
| `__init__.py` | Assembles `MISTMINT_UTILS` |

The host registry should lazy-load hosts so one host does not require another host’s dependencies at import time.

---

## RSS Feed Generators

### `free_feed_generator.py`

Builds:

```text
free_chapters_feed.xml
```

Uses novel TOML entries with:

```toml
has_free = true
```

### `paid_feed_generator.py`

Builds:

```text
paid_chapters_feed.xml
```

Uses novel TOML entries with:

```toml
has_paid = true
```

### `comments.py`

Builds:

```text
aggregated_comments_feed.xml
```

Uses novel TOML entries with:

```toml
has_comments = true
```

---

## Sample RSS Item Fields

Generated RSS items may include:

```text
title
volume
chapter
chaptername
link
description
category
translator
short_code
featured_image_url
pub_date
host
host_logo_url
guid
guid_is_permalink
```

These are consumed by the Discord repos.

---

## Feed Sorting

Paid/free feed sorting should not depend on TOML insertion order.

Where possible, sorting should use parsed dates, chapter numbers, and stable tie-breakers such as alphabetical title/short code.

---

## Mistmint Haven Quick Setup

### Modes

Mistmint host config can control source modes:

```toml
free_chapters_source = "feed"
paid_chapters_source = "api"
chapter_mode = "auto"
```

Typical meaning:

| Setting | Purpose |
| --- | --- |
| `free_chapters_source` | Whether free chapters come from feed/API |
| `paid_chapters_source` | Whether paid chapters come from feed/API |
| `chapter_mode` | How chapter parsing/resolution behaves |

### Mapping

For each Mistmint novel, the novel TOML should include:

```toml
host = "Mistmint Haven"
short_code = "CODE"
novel_url = "https://www.mistminthaven.com/..."
has_free = true
has_paid = true
has_comments = true
```

### Required Repo Secrets

Mistmint API/private data may need:

| Secret | Purpose |
| --- | --- |
| `MISTMINT_COOKIE` | Mistmint login/session cookie or token, depending on script |
| `DISCORD_BOT_TOKEN` | Required for direct Discord tools/reports |
| `GH_PAT` | Used when dispatching workflows or editing external repo files where needed |

---

## Token-Expiry Alerts

Token alert logic lives in:

```text
token/send_token_alert.py
token/token_alert_state.json
message_templates/token_alert.toml
```

Template-specific user settings live in:

```toml
[settings]
global_mention = "||<@&1329392448798982214>||"
```

The workflow:

```text
.github/workflows/send_token_alert.yml
```

can be triggered by dispatch or manually.

---

## Message Templates in `rss-feed`

This repo has direct Discord tools/reports, so it also has templates:

```text
message_templates/membership_update.toml
message_templates/nu_weekly_readers.toml
message_templates/publish_single_novel.toml
message_templates/revenue_report.toml
message_templates/token_alert.toml
```

Unlike `discord-webhook`, this repo does not use `config/embeds.json`.

Template-specific user/repo settings should live in each TOML file under:

```toml
[settings]
```

Examples:

```toml
[settings]
global_mention = "||<@&1329392448798982214>||"
embed_color = "2D3F51"
novel_discord_map_url = "https://raw.githubusercontent.com/Cannibal-Turtle/discord-webhook/main/config/novel_discord_map.toml"
```

Python should read these settings with:

```python
load_template_settings("template_name")
```

This keeps fork-specific IDs, colors, and URLs out of Python.

---

## Novel Updates Weekly Readers

Script:

```text
novelupdates/nu_weekly_readers.py
```

Template:

```text
message_templates/nu_weekly_readers.toml
```

State:

```text
novelupdates/nu_readers.json
```

Workflow:

```text
.github/workflows/nu_weekly_readers.yml
```

Purpose:

- fetch Novel Updates reading-list counts
- compare with saved state
- generate weekly deltas
- post a Discord report
- save updated counts

Template settings include:

```toml
[settings]
global_mention = "||<@&1329392448798982214>||"
embed_color = "2D3F51"
novel_discord_map_url = "https://raw.githubusercontent.com/Cannibal-Turtle/discord-webhook/main/config/novel_discord_map.toml"
allow_role_pings = true
no_data_text = "_No data this week (no NU counts retrieved)._"
```

The `novel_discord_map_url` lets this repo resolve novel short codes to Discord role mentions without storing Discord role data inside `rss-feed` mappings.

---

## Monthly Revenue Report

Script:

```text
revenue/report.py
```

Template:

```text
message_templates/revenue_report.toml
```

State:

```text
revenue/state.json
```

Workflow:

```text
.github/workflows/monthly_revenue.yml
```

Purpose:

- collect host revenue data
- calculate monthly deltas
- post a Discord report
- save baseline/state data

Template settings include:

```toml
[settings]
global_mention = "||<@&1329392448798982214>||"
embed_color = "C9D3FF"
novel_discord_map_url = "https://raw.githubusercontent.com/Cannibal-Turtle/discord-webhook/main/config/novel_discord_map.toml"
```

Revenue rows are controlled by template blocks such as:

```toml
[row_basic]
[row_membership]
[first_run]
[month_header]
[monthly_total]
[empty_report]
```

---

## Automatic Novel Status Updater

Script:

```text
tools/update_novel_status.py
```

State/targets:

```text
novel_status_targets.json
```

Workflow:

```text
.github/workflows/update_novel_status.yml
```

Purpose:

- resolve `title + host` to `short_code`
- calculate current novel status
- edit existing Discord status cards in place
- avoid reposting duplicate novel cards

Workflow inputs:

```yaml
title: "Novel title"
host: "Mistmint Haven"
```

`novel_status_targets.json` stores Discord message targets by short code.

---

## Manual Novel Card Tool

Script:

```text
tools/publish_single_novel.py
```

Template:

```text
message_templates/publish_single_novel.toml
```

Workflow:

```text
.github/workflows/publish_single_novel.yml
```

Workflow inputs:

```yaml
short_code: "AMLWC"
channel_id: "optional extra Discord channel/thread ID"
```

What it does:

- resolves a novel by short code
- pulls novel metadata from `novel_mappings.py`
- pulls Discord role/emoji/role URL from `novel_discord_map_url`
- renders a manual novel card
- posts to the configured archive channel and/or optional extra channel
- records/updates the status target where relevant

Template settings include:

```toml
[settings]
archive_channel_id = "1463476725253144751"
novel_discord_map_url = "https://raw.githubusercontent.com/Cannibal-Turtle/discord-webhook/main/config/novel_discord_map.toml"
```

---

## Membership Update Tool

Script:

```text
tools/publish_membership_update.py
```

Template:

```text
message_templates/membership_update.toml
```

Workflow:

```text
.github/workflows/publish_membership_update.yml
```

Workflow inputs:

```yaml
short_code: "AMLWC"
banner_url: "https://..."
```

What it does:

- resolves a novel by short code
- posts a membership announcement
- uses Components V2 payloads
- can write membership state back to the novel TOML
- uses Discord role/news settings from template `[settings]`

Template settings include:

```toml
[settings]
novel_discord_map_url = "https://raw.githubusercontent.com/Cannibal-Turtle/discord-webhook/main/config/novel_discord_map.toml"
news_channel_id = "1330049962129489930"
private_guild_id = "1329384099609051136"
membership_role_id = "1329502951764525187"
public_global_mention = "||@everyone||"
```

---

## Required Workflow Inputs

### `publish_single_novel.yml`

| Input | Purpose |
| --- | --- |
| `short_code` | Novel short code, e.g. `AMLWC` |
| `channel_id` | Optional extra Discord channel/thread ID |

### `publish_membership_update.yml`

| Input | Purpose |
| --- | --- |
| `short_code` | Novel short code, e.g. `AMLWC` |
| `banner_url` | Membership banner image URL |

### `update_novel_status.yml`

| Input | Purpose |
| --- | --- |
| `title` | Novel title |
| `host` | Hosting site, e.g. `Mistmint Haven` |

---

## Workflows

| Workflow | Purpose |
| --- | --- |
| `update_free_feed.yml` | Regenerates free RSS feed, scheduled daily |
| `update_paid_feed.yml` | Regenerates paid RSS feed, scheduled hourly |
| `update_comments.yml` | Regenerates comments RSS feed, scheduled hourly |
| `update_novel_status.yml` | Edits existing Discord novel status cards |
| `publish_single_novel.yml` | Manually posts a novel/status card |
| `publish_membership_update.yml` | Manually posts membership announcement |
| `monthly_revenue.yml` | Posts monthly revenue report |
| `nu_weekly_readers.yml` | Posts weekly NU reader-count report |
| `send_token_alert.yml` | Sends token warning/error alerts |

---

## Adding a New Novel on an Existing Host

1. Create a novel TOML file in:

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

3. Add optional status/checker fields as needed:

   ```toml
   chapter_count = "93 Chapters"
   last_chapter = "Chapter 93"
   start_date = ""
   history_file = ""
   discord_color = "#c90016"
   ```

4. Add Discord role/emoji/role URL data in the Discord repo:

   ```text
   discord-webhook/config/novel_discord_map.toml
   ```

5. If Mistmint thread posting is needed, add the thread ID in:

   ```text
   mistmint-discord/config/thread_id_map.json
   ```

6. Run the relevant feed workflow.

7. Run `publish_single_novel.yml` if you need a manual card.

8. Confirm `novel_status_targets.json` updates if the novel has a status card.

---

## Adding a New Hosting Site

1. Add host config:

   ```text
   mappings/hosts/new_host.toml
   ```

2. Add novel configs:

   ```text
   mappings/novels/code.toml
   ```

3. Add or update host utilities in:

   ```text
   host_utils/
   ```

4. Register the host in:

   ```text
   host_utils/__init__.py
   ```

5. Make sure feed generators can load the host utils.

6. Add any required token/cookie secret name in the host TOML.

7. Add Discord-side config in the Discord repos only if that host needs announcements.

---

## Manual Publishing Checklist

When adding a new novel:

1. Create a novel TOML file in `mappings/novels/`.
2. Add a unique `short_code`.
3. Add Discord role/emoji/role URL data in the Discord repo.
4. Run `publish_single_novel.yml`.
5. Confirm `novel_status_targets.json` was updated.
6. If the novel enters membership, run `publish_membership_update.yml` with:
   - `short_code`
   - `banner_url`
7. Confirm the novel TOML now has:

   ```toml
   is_membership = true
   ```

---

## Troubleshooting

### `ModuleNotFoundError: feedparser`

Install requirements:

```bash
pip install -r requirements.txt
```

For workflows that import multiple scripts, also make sure the workflow installs needed dependencies before running Python.

### Host import breaks an unrelated script

`host_utils` should lazy-load host modules.

A script asking for Mistmint should not import Dragonholic/TITV dependencies unless it requests those hosts.

### TOML template placeholders render empty

A placeholder only works if Python passes the value in the render context.

Example:

```toml
color = "{embed_color}"
```

needs Python to pass:

```python
{"embed_color": 0x2D3F51}
```

Template-specific defaults should live under:

```toml
[settings]
```

and Python should read them with `load_template_settings(...)`.

### Discord role/config URL should not be hardcoded in Python

Repo/user-specific IDs and URLs should live in template `[settings]`, not in Python.

Good:

```toml
[settings]
global_mention = "||<@&1329392448798982214>||"
novel_discord_map_url = "https://raw.githubusercontent.com/Cannibal-Turtle/discord-webhook/main/config/novel_discord_map.toml"
```

### JSON state file crashed

Empty files are invalid JSON.

Use:

```json
{}
```

---

## Design Guarantees

- `novel_mappings.py` remains import-compatible for dependent scripts.
- Actual mapping data lives in TOML files.
- Host-level config lives in `mappings/hosts/`.
- Novel-level config lives in `mappings/novels/`.
- Novel descriptions can use TOML multiline strings.
- NSFW status comes from `is_nsfw`.
- Membership status comes from `is_membership`.
- Output feed URLs are centralized in `mappings/output_feeds.toml`.
- Paid/free feed sorting should not depend on mapping insertion order.
- `history_file = ""` safely means no arc tracking.
- `start_date = ""` safely means no duration phrase in completion messages.
- `update_novel_status.py` edits existing Discord messages instead of reposting.
- `novel_status_targets.json` stores message targets by short code.
- Discord role IDs, custom emojis, and role URLs belong in Discord bot repos, not in `rss-feed` mappings.
- Direct-report template settings belong in `message_templates/*.toml`, not hardcoded Python.

---

## System Overview

```text
Host sites / APIs
   ↓
rss-feed host utils
   ↓
free / paid / comments RSS XML
   ↓
discord-webhook + mistmint-discord
   ↓
Discord announcements
```

Manual tools and reports also live in `rss-feed`:

```text
NU weekly readers
monthly revenue
membership update
manual novel card
token alerts
status updater
```

---

## Example Result

The final Discord status card is created once, then updated automatically when new free chapters are posted.

The status updater preserves the existing card layout and only edits the status field.

<img width="441" height="197" alt="image" src="https://github.com/user-attachments/assets/36e3c6e0-5dfd-4960-921f-e9c1cf3dd96c" />
