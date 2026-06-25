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
│  ├─ create_novel_toml.yml
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
├─ feed_common.py
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
│  ├─ create_novel_toml.py
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

[completion_state_url]
discord_webhook = "https://raw.githubusercontent.com/Cannibal-Turtle/discord-webhook/main/state.json"
```

`completion_state_url.discord_webhook` points to the canonical Discord announcement state. The feed generators use it only for **novel-scoped fetching** so completed novels can be skipped before an API/novel-feed request. Host/global feeds are still scanned normally.

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

free_feed_url = "https://example.com/feed/"
chapters_api_url = "https://api.example.com/api/novels/slug/{slug}/chapters"

free_chapters_source = "feed"
paid_chapters_source = "api"
chapter_mode = "auto"
comments_api_url = "https://api.example.com/..."
novels_api_url = "https://api.example.com/api/my-novels"

# Comment source modes:
# "trans"  = use tokened author dashboard endpoint; best metadata/reply tracking, token required
# "public" = use no-token public novel comment APIs; less reply tracking, but no token needed
# "auto"   = try "trans" first; if token is missing/expired, fall back to "public"
comments_source = "auto"

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
- host/global feed URLs, such as `free_feed_url`
- API URL templates, such as `chapters_api_url = ".../{slug}/..."`
- feed/API mode settings
- `comments_api_url`
- `comments_source`
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
title = "After the Male Leads Went Crazy, They All Turned into Male Ghosts"
short_code = "AMLWC"

novelupdates_url = "https://www.novelupdates.com/series/after-the-male-leads-went-crazy-they-all-turned-into-male-ghosts"
novel_url = "https://www.mistminthaven.com/novels/after-the-male-leads-went-crazy-they-all-turned-into-male-ghosts"
featured_image = "https://web-novel-mistmint.s3.ap-southeast-1.amazonaws.com/novels/example-cover.jpg"
novel_id = "4221504f-49cd-4c8b-9c98-89e8b67705df"

chapter_count = "93 Chapters"
last_chapter = "Chapter 93"
start_date = "20/6/2026"
has_free = true
has_paid = true
is_nsfw = false
is_membership = false

discord_color = "#c90016"

tags = ["chinese", "quick transmigration", "supernatural"]
site_genres = ["Horror", "Supernatural", "Transmigration"]
history_file = "arc_history/amlwc_history.json"

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
| `novel_id` | Host/API novel ID when available; important for Mistmint API/comment tools |
| `has_free` | Whether this novel appears in the free feed |
| `has_paid` | Whether this novel appears in the paid feed |
| `is_nsfw` | Whether this novel should be categorized as NSFW |
| `is_membership` | Whether this novel is currently membership-only/available for membership |

### Optional Fields

| Field | Purpose |
| --- | --- |
| `novelupdates_url` | Novel Updates page URL |
| `chapter_count` | Display text for completion/status cards |
| `last_chapter` | Completion checker target |
| `start_date` | Used to calculate “After X of updates...” in completion messages |
| `has_comments` | Comments feed flag; defaults to true unless explicitly set to false |
| `tags` | Discord-supported genre tags, such as `chinese`, `modern`, `romance`, `bl`; downstream Discord repos use this for role mentions |
| `site_genres` | Full original Mistmint Haven genre names from the API, kept for reference even if some are not Discord-supported tags |
| `history_file` | Arc checker history file |
| `discord_color` | Novel-specific embed color for Discord repos |
| `theme_color` | Optional alternate novel color field |
| `custom_description` | Multiline description for manual publishing/status cards |

---

## Empty Optional Fields

Use empty strings instead of deleting optional fields when you want scripts to safely skip related behavior.

```toml
start_date = ""
discord_color = ""
site_genres = []
history_file = ""
```

Meaning:

| Field | Empty Behavior |
| --- | --- |
| `start_date = ""` | Completion announcement omits the duration phrase |
| `discord_color = ""` | Discord repos use their normal/default color logic |
| `site_genres = []` | No Mistmint host genres are stored |
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

The chapter generators are separated by **chapter type**, not by source method:

```text
free_feed_generator.py
→ builds free_chapters_feed.xml
→ formats free/public chapter items

paid_feed_generator.py
→ builds paid_chapters_feed.xml
→ formats paid/premium chapter items, including paid history and coin/price fields
```

Shared generator rules live in:

```text
feed_common.py
```

`feed_common.py` owns shared helpers such as:

- reading the canonical completion state URL from `mappings/output_feeds.toml`
- loading `discord-webhook/state.json`
- resolving completion keys:
  - `paid` → `paid_completion`
  - `free` + novel has paid feed → `free_completion`
  - `free` + novel has no paid feed → `only_free_completion`
- detecting whether a source is host/global or novel-scoped from mapping shape
- shared sorting and NSFW marker helpers

### Source Scope Rule

The generators treat **scope** separately from **chapter type**.

```text
host/global feed
→ fetch once
→ scan entries
→ match entry title to mapped novel
→ no completion gate

novel-level feed
→ loop novels
→ check completion state before fetching that novel feed
→ parse entries for that novel

novel-level API
→ loop novels
→ check completion state before API request
→ fetch chapter data
→ filter by chapter type
```

This keeps host/global feeds simple: if the feed has an entry, the generator includes it. Completion state is only a fetch-saving gate for novel-scoped sources.

### Source Config

Host TOML controls which source method each chapter type uses:

```toml
free_chapters_source = "feed"
paid_chapters_source = "api"
```

The source method is not the same as chapter type.

For example, Mistmint's chapter API returns all chapters. The free and paid logic filter the same chapter data differently:

```text
free API logic
→ keep chapters where isFree is true

paid API logic
→ keep chapters where isFree is false and the chapter is not hidden
```

A host/global feed is recognized when a feed URL is defined in `mappings/hosts/*.toml`, such as:

```toml
free_feed_url = "https://www.mistminthaven.com/feed/"
```

A novel-level feed is recognized when a feed URL is defined in a specific `mappings/novels/*.toml` file.

A URL template like this is stored at host level but fetched per novel because it needs the novel slug:

```toml
chapters_api_url = "https://api.mistminthaven.com/api/novels/slug/{slug}/chapters"
```

### `free_feed_generator.py`

Builds:

```text
free_chapters_feed.xml
```

Uses novel TOML entries with:

```toml
has_free = true
```

Supports:

```text
host/global free feed
novel-level free feed
host utility/API loader, such as Mistmint free API mode
```

The XML item structure is kept inside this generator so the free RSS output format stays stable.

### `paid_feed_generator.py`

Builds:

```text
paid_chapters_feed.xml
```

Uses novel TOML entries with:

```toml
has_paid = true
```

Supports:

```text
host/global paid feed
novel-level paid feed
novel-level paid API/scraper logic
manual/state fallback when a host uses it
```

Paid-only behavior stays inside this generator, including:

```text
paid_history.json
coin/price fields
paid GUID handling
paid-specific item formatting
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

The comments generator already asks `novel_mappings.py` for comment source URLs with novel fallback, so it can use host-level or novel-level comment API/feed config depending on the mapping.

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
# Chapter source modes:
# "feed" = use a host-provided feed/RSS-style source for this chapter type
# "api"  = use the host chapter API/data source, then filter by chapter type
free_chapters_source = "feed"
paid_chapters_source = "api"

# Paid chapter fallback mode:
# "auto"   = try API/chapter data first; cookie is optional if the endpoint allows it
# "manual" = force mistmint_state.json/manual paid chapter fallback instead of API
chapter_mode = "auto"

# Comment source modes:
# "trans"  = use tokened author dashboard endpoint; best metadata/reply tracking, token required
# "public" = use no-token public novel comment APIs; less reply tracking, but no token needed
# "auto"   = try "trans" first; if token is missing/expired, fall back to "public"
comments_source = "auto"
```

Typical meaning:

| Setting | Purpose |
| --- | --- |
| `free_chapters_source` | Whether free chapters come from a feed-style source or the chapter API/data source |
| `paid_chapters_source` | Whether paid chapters come from a feed-style source or the chapter API/data source |
| `chapter_mode` | Mistmint paid fallback mode; `auto` tries API/chapter data, `manual` forces manual/state fallback |
| `comments_source = "trans"` | Uses `comments_api_url` / `comments/trans/all-comments`; best metadata and reply tracking, but token/cookie is required |
| `comments_source = "public"` | Uses public no-token novel comment APIs; less complete reply tracking, but avoids monthly token refresh |
| `comments_source = "auto"` | Tries `trans` first, then falls back to public mode if the token is missing/expired |

The public Mistmint comments endpoint is internal host logic, not user-facing repo config. The code builds it from `BASE_API` as `/comments/novel/{identifier}` and tries the mapped `novel_id` first, then the novel slug. Keep this in Python unless Mistmint changes endpoint structure often enough that it becomes worth exposing a separate URL template.

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

`tools/create_novel_toml.py` uses the host config's `token_secret` first. For Mistmint, that normally means `MISTMINT_COOKIE`. It can also use `MISTMINT_TOKEN` if you provide bearer-token auth instead.

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

Mistmint token alerts are skipped only when comments are intentionally public-only:

```toml
comments_source = "public"
```

In `comments_source = "auto"`, token alerts still run, but comment generation can fall back to public comments instead of fully failing when the token expires.

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


## Create Novel TOML Tool

Script:

```text
tools/create_novel_toml.py
```

Workflow:

```text
.github/workflows/create_novel_toml.yml
```

Purpose:

- fetch an existing dashboard novel from a configured host API
- create `mappings/novels/<short_code>.toml`
- fill host-provided fields automatically, including title, slug URL, novel ID, description, start date, NSFW flag, and Mistmint cover image
- guess the Novel Updates URL from the title
- keep only Discord-supported mention tags from `discord-webhook/config/tag_roles.json` in `tags`
- preserve the full Mistmint Haven API genre list in `site_genres`
- optionally create `arc_history/<short_code>_history.json`

For Mistmint Haven, the host file must include:

```toml
novels_api_url = "https://api.mistminthaven.com/api/my-novels"
token_secret = "MISTMINT_COOKIE"
```

Workflow inputs:

| Input | Required? | Purpose |
| --- | --- | --- |
| `host` | Yes | Hosting site, e.g. `Mistmint Haven` |
| `title` | Yes | Novel title exactly/as shown in the host dashboard |
| `short_code` | Yes | New short code, e.g. `AMLWC` |
| `chapter_count` | No | Optional display text, e.g. `93 Chapters`; blank writes `""` |
| `last_chapter` | No | Optional target text, e.g. `Chapter 93`; blank writes `""` |
| `discord_color` | No | Optional hex color, e.g. `#c90016`; blank writes `""` |
| `quick_transmigration` | No | Checkbox. Tick this only when the novel is quick transmigration; adds `quick transmigration` to `tags`. |
| `infinite_flow` | No | Checkbox. Tick this only when the novel is infinite flow; adds `infinite flow` to `tags`. |
| `has_arcs` | Yes | If true, creates `arc_history/<short_code>_history.json` and sets `history_file` |
| `dry_run` | Yes | If true, previews the TOML in the Actions log without committing |
| `overwrite` | Yes | If true, allows replacing an existing `mappings/novels/<short_code>.toml` |

Recommended first run:

```text
dry_run = true
overwrite = false
```

Then rerun with:

```text
dry_run = false
```

once the generated TOML looks right.

### Tags and Mistmint genres

`tags` should only contain tags that exist in the Discord repo's `config/tag_roles.json`, because downstream Discord repos use `tags` for role mentions.

`site_genres` stores the full original genre names from the Mistmint API. It does not need to match Discord role tags and is kept as a reference copy of what Mistmint lists on the novel.

World-hopping uses two Actions checkboxes. Leave both unchecked when the novel is not quick transmigration or infinite flow. If it is world-hopping, tick exactly one checkbox.

When a world-hopping checkbox is ticked, the selected tag is written directly into `tags`:

```toml
tags = ["chinese", "quick transmigration", "modern", "romance", "bl"]
site_genres = ["Modern", "Romance", "Yaoi", "Transmigration"]
```

If `quick transmigration` or `infinite flow` is selected, the tool removes plain `transmigration` from `tags` automatically. This keeps a world-hopping novel from ending up with both the broad transmigration role and the specific world-hopping role.

Leaving both world-hopping checkboxes unchecked writes normal tags only:

```toml
tags = ["chinese", "transmigration", "modern", "romance", "bl"]
site_genres = ["Modern", "Romance", "Yaoi", "Transmigration"]
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

## Workflow Inputs

### `create_novel_toml.yml`

| Input | Purpose |
| --- | --- |
| `host` | Hosting site, e.g. `Mistmint Haven` |
| `title` | Novel title exactly/as shown in host dashboard |
| `short_code` | Novel short code, e.g. `AMLWC` |
| `chapter_count` | Optional chapter count text |
| `last_chapter` | Optional last-chapter text |
| `discord_color` | Optional novel embed color |
| `quick_transmigration` | Whether to add `quick transmigration` to `tags` |
| `infinite_flow` | Whether to add `infinite flow` to `tags` |
| `has_arcs` | Whether to create an arc history file |
| `dry_run` | Preview without committing |
| `overwrite` | Allow replacing an existing mapping file |

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
| `create_novel_toml.yml` | Creates a new novel TOML from a configured host API |
| `update_novel_status.yml` | Edits existing Discord novel status cards |
| `publish_single_novel.yml` | Manually posts a novel/status card |
| `publish_membership_update.yml` | Manually posts membership announcement |
| `monthly_revenue.yml` | Posts monthly revenue report |
| `nu_weekly_readers.yml` | Posts weekly NU reader-count report |
| `send_token_alert.yml` | Sends token warning/error alerts |

---

## Adding a New Novel on an Existing Host

Preferred method for a configured API host:

1. Run:

   ```text
   create_novel_toml.yml
   ```

2. Start with:

   ```text
   dry_run = true
   overwrite = false
   ```

3. Check the generated TOML in the Actions log.

4. Rerun with:

   ```text
   dry_run = false
   ```

5. Confirm the new file exists in:

   ```text
   mappings/novels/<short_code>.toml
   ```

Manual fallback:

1. Create a novel TOML file in:

   ```text
   mappings/novels/
   ```

2. Add the core fields:

   ```toml
   host = "Mistmint Haven"
   title = "Novel Title"
   short_code = "CODE"

   novelupdates_url = "https://www.novelupdates.com/series/novel-title"
   novel_url = "https://www.mistminthaven.com/novels/novel-title"
   featured_image = "https://..."
   novel_id = ""

   chapter_count = ""
   last_chapter = ""
   start_date = ""
   has_free = true
   has_paid = true
   is_nsfw = false
   is_membership = false

   discord_color = ""

   tags = ["chinese"]
   site_genres = []
   history_file = ""

   custom_description = """
   Description here.
   """
   ```

3. If the novel has arcs, set:

   ```toml
   history_file = "arc_history/code_history.json"
   ```

   and create the matching JSON file with:

   ```json
   {}
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

3. Decide the source scope/method for free and paid chapters.

   Host/global feed example:

   ```toml
   # mappings/hosts/new_host.toml
   free_chapters_source = "feed"
   free_feed_url = "https://example.com/feed/"
   ```

   Novel-level feed example:

   ```toml
   # mappings/novels/code.toml
   free_feed_url = "https://example.com/novel/code/feed/"
   ```

   Novel-level API example:

   ```toml
   # mappings/hosts/new_host.toml
   paid_chapters_source = "api"
   chapters_api_url = "https://api.example.com/novels/{slug}/chapters"
   ```

4. Add or update host utilities in:

   ```text
   host_utils/
   ```

5. Register the host in:

   ```text
   host_utils/__init__.py
   ```

6. Make sure feed generators can load the host utils.

7. Add any required token/cookie secret name in the host TOML.

8. Add Discord-side config in the Discord repos only if that host needs announcements.

---

## Manual Publishing Checklist

When adding a new novel:

1. Run `create_novel_toml.yml`, or manually create a novel TOML file in `mappings/novels/`.
2. Add a unique `short_code`.
3. Check `tags`, `site_genres`, `chapter_count`, `last_chapter`, and `discord_color` before publishing. For world-hopping, tick exactly one world-hopping checkbox so the matching role tag appears inside `tags`.
4. Add Discord role/emoji/role URL data in the Discord repo.
5. Run `publish_single_novel.yml`.
6. Confirm `novel_status_targets.json` was updated.
7. If the novel enters membership, run `publish_membership_update.yml` with:
   - `short_code`
   - `banner_url`
8. Confirm the novel TOML now has:

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

### Completion state URL is missing

`feed_common.py` expects the canonical Discord completion state URL in:

```toml
[completion_state_url]
discord_webhook = "https://raw.githubusercontent.com/Cannibal-Turtle/discord-webhook/main/state.json"
```

If this URL is missing or unreachable, generators continue without completion skipping instead of failing the whole feed run.

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
- Output feed URLs and the canonical Discord completion state URL are centralized in `mappings/output_feeds.toml`.
- `feed_common.py` owns shared generator helpers; free/paid XML item formatting stays in the individual generator files.
- Completion state is a fetch-saving gate for novel-scoped sources, not a filter for host/global feeds.
- Paid/free feed sorting should not depend on mapping insertion order.
- `history_file = ""` safely means no arc tracking.
- `start_date = ""` safely means no duration phrase in completion messages.
- `site_genres` is the full Mistmint API genre list; `tags` is the Discord-supported mention list.
- Leaving both world-hopping checkboxes unchecked adds no world-hopping tag to `tags`.
- `update_novel_status.py` edits existing Discord messages instead of reposting.
- `novel_status_targets.json` stores message targets by short code.
- Discord role IDs, custom emojis, and role URLs belong in Discord bot repos, not in `rss-feed` mappings.
- Direct-report template settings belong in `message_templates/*.toml`, not hardcoded Python.
- Mistmint comments can run in `trans`, `public`, or `auto` mode via `comments_source`.
- Public Mistmint comment fallback is best-effort; tokened `trans` mode remains the most complete source for author-wide comments and reply tracking.

---

## System Overview

```text
Host sites / APIs
   ↓
rss-feed host utils + feed_common.py
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
