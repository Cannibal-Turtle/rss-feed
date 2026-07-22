# GitHub Actions Guide

This folder contains the repository's automated and manually triggered workflows. Use this guide when running an action from **GitHub → Actions**, especially when adding a novel or publishing Discord cards and announcements.

For lower-level configuration details, see:

- [`../../README.md`](../../README.md) — full repository guide
- [`../../config/integrations.README.md`](../../config/integrations.README.md) — Discord repositories, routes, channels, and downstream dispatch
- [`../../config/runtime.README.md`](../../config/runtime.README.md) — runtime switches
- [`../../config/source_modes.README.md`](../../config/source_modes.README.md) — feed source modes
- [`../../docs/rss-template-placeholders.md`](../../docs/rss-template-placeholders.md) — message-template placeholders

## Running a manual workflow

1. Open the repository on GitHub.
2. Select **Actions**.
3. Select the workflow in the left sidebar.
4. Select **Run workflow**.
5. Keep the correct branch selected, fill in the inputs, and run it.
6. Open the run and check every step before assuming the action completed successfully.

GitHub does not support real section headings inside a `workflow_dispatch` form. In **Create Novel TOML**, the text `--- INTEGRATIONS ---` is therefore placed at the start of the first integration field's description.

## Workflow overview

| Workflow | Trigger | Purpose |
| --- | --- | --- |
| **Create Novel TOML** | Manual | Creates `mappings/novels/<short_code>.toml` from a supported host API and can update related Discord repositories. |
| **Publish Novel Card** | Manual | Publishes the novel's main Discord card to configured archive target(s) and records the message target. |
| **Update Novel Status Embeds** | Manual or repository dispatch | Edits previously published novel cards in place when status information changes. |
| **Publish Membership Update** | Manual | Previews or publishes a membership announcement with an optional cropped banner. |
| **Publish Special Announcement** | Manual | Previews or publishes a configurable special announcement with banner/card spoiler controls. |
| **Update Free Feed** | Daily at 13:00 MYT or manual | Regenerates and commits the free RSS feed, then triggers configured downstream Discord repos when needed. |
| **Update Paid Feed** | Hourly or manual | Regenerates and commits the paid RSS feed, then triggers configured downstream Discord repos when needed. |
| **Update Comments Feed** | Daily at 22:55 MYT or manual | Regenerates the aggregated comments feed and triggers configured downstream Discord repos when needed. |
| **Weekly NU Readers** | Sunday at 21:00 MYT or manual | Checks NovelUpdates reader counts, posts the report, and commits its state file. |
| **Monthly Revenue Report** | Last day of the month around 18:30 MYT or manual | Generates the monthly host revenue report and commits revenue state. |
| **Send Token Alert to Discord** | Repository dispatch or manual | Sends configured token-expiry or invalid-token alerts. |
| **Delete Discord Messages** | Manual | Deletes specified Discord message IDs/links across configured servers. |
| **Delete Today's Discord Messages (MYT)** | Manual | Deletes the bot's messages posted today in specified channels/threads, using Malaysia time. |
| **Healthcheck** | Push, pull request, or manual | Validates configuration and code assumptions and uploads `snapshots/diagnostics.json`. |

---

# Adding a novel

## Create Novel TOML

Workflow file: [`create_novel_toml.yml`](create_novel_toml.yml)

The workflow runs:

- [`../../tools/create_novel_toml.py`](../../tools/create_novel_toml.py)
- [`../../tools/update_novel_integrations.py`](../../tools/update_novel_integrations.py)

It can create the RSS mapping and update the personal Discord role map and host-specific per-novel destination map in one run.

### Recommended first run

Use:

```text
dry_run = true
overwrite = false
```

Check the generated TOML and downstream config diffs in the Actions log. Then rerun with `dry_run = false` after confirming the values.

### Core inputs

| Input | What to enter |
| --- | --- |
| `host` | Host name exactly as configured in `mappings/hosts/`, such as `Mistmint Haven`. |
| `title` | Novel title exactly as shown in the host dashboard/API. It is used to locate the correct host novel. |
| `short_code` | Stable unique code such as `AMLWC`. It becomes the mapping filename and downstream map key. |
| `chapter_count` | Optional display text such as `93 Chapters`. Blank writes an empty string. |
| `last_chapter` | Optional display text such as `Chapter 93`. Blank writes an empty string. |
| `discord_color` | Optional hexadecimal embed color such as `#c90016`. |
| `quick_transmigration` | Adds the `quick transmigration` Discord-supported tag. Do not select together with Infinite Flow. |
| `infinite_flow` | Adds the `infinite flow` Discord-supported tag. Do not select together with Quick Transmigration. |
| `has_arcs` | Creates `arc_history/<short_code-lowercase>_history.json` and writes its `history_file` path. |
| `dry_run` | Prints the generated TOML and downstream diffs without committing any changes. |
| `overwrite` | Allows replacement of conflicting existing novel/downstream entries. Leave false for normal creation. |

### Integration inputs

| Input | What it updates |
| --- | --- |
| `personal_role_id` | The novel role ID in the Discord server configured by `primary_discord.integration`. |
| `personal_custom_emoji` | The novel's custom emoji in that same Discord server, such as `<:name:123456789012345678>`. |
| `personal_role_url` | URL stored with the personal-server role. Blank reuses the latest non-empty URL in that server's novel map. |
| `host_destination_id` | Per-novel host Discord thread/channel ID. Leave blank for shared-channel hosts. |

`personal_role_id` and `personal_custom_emoji` must be supplied together. Supplying only one causes the workflow to fail instead of creating an incomplete map entry.

### Current Mistmint example

For a Mistmint novel that has a personal-server role and a Mistmint forum thread:

```text
personal_role_id       = personal server novel role ID
personal_custom_emoji  = personal server novel emoji
personal_role_url      = blank to inherit the existing personal-server URL
host_destination_id    = Mistmint novel forum thread ID
```

This normally updates:

```text
rss-feed/mappings/novels/<short_code>.toml
discord-webhook/config/novel_discord_map.toml
mistmint-discord/config/thread_id_map.json
```

The downstream repository and file are resolved through `config/integrations.json`; they are not hardwired into the workflow form.

### Values filled automatically

For supported hosts, the generator obtains host metadata from the API. New TOMLs automatically include values such as:

- host novel URL, slug/ID, featured image, and description
- source language and supported Discord tags
- full unfiltered host genres in `site_genres`
- `is_nsfw` from the host API's mature flag unless a script-level override is supplied
- `is_membership = false`
- translator name and translator/profile URL through the selected host configuration

If the host API omits the mature flag, automatic NSFW detection defaults to `false`.

### NSFW override support

The current GitHub Actions form does not expose an NSFW field, but [`../../tools/create_novel_toml.py`](../../tools/create_novel_toml.py) already accepts:

```text
--nsfw auto
--nsfw true
--nsfw false
```

| Value | Result |
| --- | --- |
| `auto` or blank | Uses the host API's `isMature` value; missing values fall back to `false`. |
| `true` | Forces `is_nsfw = true`. |
| `false` | Forces `is_nsfw = false`. |

This parser supports either a future GitHub Actions boolean checkbox or a `true`/`false`/`auto` dropdown. Exposing the control later only requires adding the workflow input and passing its value to `--nsfw`; the Python generator does not need another change.

A per-novel translator URL is not requested by this workflow. When a novel does not override translator information, [`../../novel_mappings.py`](../../novel_mappings.py) uses the selected host's translator name and URL.

### Role URL inheritance

Leaving `personal_role_url` blank does not write an empty URL. The updater scans that same Discord repository's existing `novel_discord_map.toml` and reuses its latest non-empty `role_url`.

Inheritance is scoped to the target server. A future host-server role map would inherit from its own map, not from the personal server.

### Host destinations

`host_destination_id` is interpreted through the selected host's `host_discord_targets` route:

- `thread_map` — writes a per-novel thread ID to the configured JSON map
- `channel_map` — writes a per-novel channel ID to the configured JSON map
- `channel` — uses a shared channel from the host Discord server config; leave the input blank

The current form intentionally hides separate host-server role/emoji/URL inputs because no current host requires them. The generic updater already supports those fields internally, so they can be exposed later by editing only this workflow when a host with its own novel roles is added.

### Dry run and overwrite

**Dry run** previews both local and remote changes and does not write them.

**Overwrite** is for an existing short code whose stored values must be replaced. It is not needed when:

- the entry does not exist yet, or
- the existing entry is already identical

Identical downstream entries are treated as successful, making reruns safe after a partially completed or interrupted run.

---

# Novel cards and status updates

## Publish Novel Card

Workflow file: [`publish_novel_card.yml`](publish_novel_card.yml)
Script: [`../../tools/publish_novel_card.py`](../../tools/publish_novel_card.py)
Template: [`../../message_templates/publish_novel_card.toml`](../../message_templates/publish_novel_card.toml)

Input:

```text
short_code
```

The workflow:

1. Loads the novel from `mappings/novels/`.
2. Resolves role, emoji, URL, channel, and host routing through integration config.
3. Publishes the card to configured novel-card archive target(s).
4. Saves the Discord message target in [`../../novel_card_targets.json`](../../novel_card_targets.json).
5. Commits the updated target state.

Use this after adding a novel when you want its persistent novel/status card published.

## Update Novel Status Embeds

Workflow file: [`update_novel_status.yml`](update_novel_status.yml)
Script: [`../../tools/update_novel_card.py`](../../tools/update_novel_card.py)

Manual input:

```text
short_code
```

It can also receive the `update-novel-status` repository-dispatch event.

The updater uses `novel_card_targets.json` to edit existing messages in place. It does not normally create a second card. Typical changes include ongoing/completed status and other metadata rendered by the card template.

If the workflow cannot find a target, check that **Publish Novel Card** succeeded and that the short code is present in `novel_card_targets.json`.

---

# Membership and special announcements

Both announcement workflows support three modes:

| Mode | Result |
| --- | --- |
| `crop preview` | Creates banner crop files and a contact sheet as a one-day Actions artifact. Sends no Discord message. |
| `preview` | Sends the finished announcement to the configured mod preview channel with mentions suppressed. |
| `publish` | Sends to configured live target(s) with normal mention behavior. |

## Shared banner inputs

| Input | Behavior |
| --- | --- |
| `short_code` | Selects the novel and its metadata. |
| `banner_url` | Optional finished banner. When supplied, it is downloaded and re-uploaded; crop position and ratio are ignored. |
| `banner_ratio` | Optional override such as `8:3` or `4:1`. Use `original` to preserve the image without crop/resize. Blank uses the message template setting. |
| `crop_position` | `auto`, `top`, `upper`, `upper center`, `center`, `lower center`, `lower`, or `bottom`. Used only for an auto-generated banner. |
| `mode` | `crop preview`, `preview`, or `publish`. |

With `crop_position = auto`, the cropper uses a lightweight heuristic to avoid cutting text near the top or bottom; unclear images use the configured upper-center fallback.

## Publish Membership Update

Workflow file: [`publish_membership_update.yml`](publish_membership_update.yml)
Script: [`../../tools/publish_membership_update.py`](../../tools/publish_membership_update.py)
Template: [`../../message_templates/membership_update.toml`](../../message_templates/membership_update.toml)

On `publish`, it:

- posts to the primary Discord target and any configured host-specific membership route
- resolves global, event, novel, status, and NSFW mentions from each target integration
- marks the novel's TOML with `is_membership = true`
- commits the changed novel TOML

`preview` does not change the TOML.

## Publish Special Announcement

Workflow file: [`publish_special_announcement.yml`](publish_special_announcement.yml)
Script: [`../../tools/publish_special_announcement.py`](../../tools/publish_special_announcement.py)
Template: [`../../message_templates/special_announcement.toml`](../../message_templates/special_announcement.toml)

Additional inputs:

| Input | Behavior |
| --- | --- |
| `blur_banner` | Spoilers the banner attachment manually. NSFW novel banners are spoilered automatically even when this is unchecked. |
| `blur_card` | Spoilers the entire announcement card/container. |

The title, announcement text, button label, and default button URL are controlled by `message_templates/special_announcement.toml`. The novel URL is used as a fallback when the template button URL is blank.

---

# Feed workflows

## Update Free Feed

Workflow file: [`update_free_feed.yml`](update_free_feed.yml)

- Scheduled daily at **13:00 Malaysia time**.
- Regenerates `free_chapters_feed.xml`.
- Compares GUIDs before and after generation.
- Commits only when the feed changes.
- Triggers configured downstream repositories only when new items exist, unless forced.

Manual option:

```text
force_downstream
```

Set it to true when the feed itself did not add a new GUID but downstream Discord processing must be rerun.

## Update Paid Feed

Workflow file: [`update_paid_feed.yml`](update_paid_feed.yml)

- Scheduled at the start of every hour.
- Regenerates `paid_chapters_feed.xml`.
- Uses the same new-GUID gate and downstream dispatch logic as the free feed.
- Shares the `feeds-main` concurrency group with the free workflow so both do not push at the same time.

Manual option:

```text
force_downstream
```

## Update Comments Feed

Workflow file: [`update_comments.yml`](update_comments.yml)

- Scheduled daily at **22:55 Malaysia time**.
- Regenerates `aggregated_comments_feed.xml`.
- Merges NovelUpdates comments after the host comments run.
- Updates `token/token_alert_state.json`.
- Dispatches configured downstream comment workflows when new GUIDs are found or forcing is enabled.

Manual option:

```text
force_downstream
```

## Feed API fallback alert

When enabled in `config/integrations.json`, free/paid feed generation can send a Discord alert if it had to use the configured API fallback. This alert is separate from normal downstream chapter notifications.

---

# Reports and maintenance

## Weekly NU Readers

Workflow file: [`nu_weekly_readers.yml`](nu_weekly_readers.yml)

Runs every Sunday at **21:00 Malaysia time**. It posts the configured NovelUpdates reader-count report and commits changes to:

```text
novelupdates/nu_readers.json
```

## Monthly Revenue Report

Workflow file: [`monthly_revenue.yml`](monthly_revenue.yml)

The cron checks days 28–31, while an internal Malaysia-time guard allows only the actual last-day evening run. A manual run bypasses that date guard.

It commits:

```text
revenue/state.json
```

## Send Token Alert to Discord

Workflow file: [`send_token_alert.yml`](send_token_alert.yml)

Normally triggered by these repository-dispatch events:

```text
token-expiring
token-invalid
```

A manual run is available mainly for testing the configured alert path.

## Healthcheck

Workflow file: [`healthcheck.yml`](healthcheck.yml)

Runs on relevant pushes, pull requests, and manually. It validates mappings, config, templates, tools, and related Python files. The diagnostics artifact is uploaded even if the validation step fails:

```text
snapshots/diagnostics.json
```

Run Healthcheck after changing integration routes, host mappings, templates, or workflow files.

---

# Discord cleanup workflows

## Delete Discord Messages (All Configured Servers)

Workflow file: [`delete-discord-message.yml`](delete-discord-message.yml)

Input:

```text
message_ids
```

Accepts Discord message IDs or message links. Separate multiple entries with commas, spaces, or new lines. The script searches configured/local target information rather than requiring one fixed channel ID for every deletion.

## Delete Today's Discord Messages (MYT)

Workflow file: [`delete_discord_today.yml`](delete_discord_today.yml)

Input:

```text
channel_ids
```

Accepts channel or thread IDs separated by commas, spaces, or new lines. It deletes matching bot messages from the current Malaysia calendar day.

Deletion is irreversible. Verify the IDs before starting either workflow.

---

# Required secrets

| Secret | Used for |
| --- | --- |
| `DISCORD_BOT_TOKEN` | Publishing/editing/deleting Discord messages, reports, alerts, and previews. |
| `PAT_GITHUB` | Cross-repository config writes and downstream repository dispatches. |
| `MISTMINT_COOKIE` | Authenticated Mistmint API calls, including novel creation, comments, and revenue where required. |
| `MISTMINT_TOKEN` | Optional bearer-token alternative/addition used by the novel generator when available. |
| `GITHUB_TOKEN` | Built-in Actions token used for commits inside this repository and some same-repository dispatch/state operations. |

For novel onboarding, `PAT_GITHUB` needs read/write access to the downstream config repositories it may update. With a fine-grained token, grant **Contents: Read and write** for those repositories.

Never put tokens, cookies, or PAT values directly into workflow YAML, repository files, or Actions inputs.

---

# Configuration ownership

The workflows intentionally read destinations from configuration instead of hardwiring one host or Discord server.

| Concern | Source of truth |
| --- | --- |
| Host metadata/default translator | `mappings/hosts/<host>.toml` |
| Novel metadata | `mappings/novels/<short_code>.toml` |
| Primary Discord integration | `config/integrations.json → primary_discord` |
| Host-specific Discord integration/routes | `config/integrations.json → host_discord_targets` |
| Remote config file paths | Each integration's `paths` object |
| Discord channels/global mention | Target Discord repo's `config/server.json` |
| Named roles | Target Discord repo's `config/roles.json` |
| Novel role/emoji/role URL | Target Discord repo's `config/novel_discord_map.toml` |
| Per-novel host thread/channel | Target host Discord repo's configured ID map |
| Card text/layout | `message_templates/publish_novel_card.toml` |
| Membership text/layout | `message_templates/membership_update.toml` |
| Special announcement text/layout | `message_templates/special_announcement.toml` |

The integration `raw_base` URL supplies the GitHub owner, repository, and branch for remote reads/writes. Separate duplicated `repo` and `branch` fields are not required for standard `raw.githubusercontent.com/<owner>/<repo>/<branch>` URLs.

---

# Common problems

## Create Novel TOML cannot find the title

Use the title exactly as shown in the host dashboard. Check spelling, apostrophes, punctuation, and whether the authenticated account can see that novel.

## Host authentication error

Refresh the relevant cookie/token secret. Do not paste the secret into the workflow input or logs.

## Personal role mapping fails

Make sure both `personal_role_id` and `personal_custom_emoji` are filled. Check that the custom emoji uses a complete Discord form such as:

```text
<:name:123456789012345678>
```

## Role URL is unexpected

A blank URL inherits the latest non-empty URL from that target server's map. Enter an explicit URL only when the server's role/join URL has changed.

## Host destination fails

Check the selected host's `host_discord_targets.<host>.routes.forum_post` configuration. A per-novel ID requires `thread_map` or `channel_map`. A shared `channel` route should leave `host_destination_id` blank.

## Card published but future updates cannot find it

Check that `novel_card_targets.json` was changed and committed by **Publish Novel Card**.

## Banner crop looks wrong

Run the announcement in `crop preview` mode, download the one-day artifact, inspect `contact_sheet.png`, and rerun with a manual crop position. A supplied `banner_url` is treated as a finished banner and is not cropped.

## Preview pinged users

The preview tools are designed to suppress mentions. Confirm the run used `mode = preview`, not `publish`, and check the target integration's mention configuration.

## Feed changed but downstream Discord did not run

Check whether a genuinely new GUID was added. When intentionally reprocessing existing feed items, rerun manually with `force_downstream = true`.

## A workflow changed config but another step failed

Review each repository involved. Cross-repository writes are idempotent when the stored value is identical, so correct the failure and rerun with the same values. Use `overwrite = true` only when replacing a conflicting value.
