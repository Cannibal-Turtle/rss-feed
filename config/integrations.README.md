# Integrations Config

This file explains `config/integrations.json`.

`integrations.json` controls how this repo talks to other repos and optional Discord-facing tools.  
It should contain routing information, remote config locations, and optional feature switches.

It should **not** contain Discord bot tokens, Mistmint cookies, or other secrets. Secrets stay in GitHub Actions secrets.

## Current shape

```json
{
  "downstream_dispatch": {
    "repos": [
      "Cannibal-Turtle/discord-webhook",
      "Cannibal-Turtle/mistmint-discord"
    ],
    "events": {
      "chapters": "trigger-discord-notify",
      "comments": "trigger-discord-comments"
    }
  },
  "primary_discord": {
    "integration": "discord_webhook",
    "always_post": true
  },
  "discord_webhook": {
    "raw_base": "https://raw.githubusercontent.com/Cannibal-Turtle/discord-webhook/main",
    "paths": {
      "server_json": "config/server.json",
      "roles_json": "config/roles.json",
      "tag_roles": "config/tag_roles.json",
      "novel_discord_map": "config/novel_discord_map.toml",
      "state": "state.json"
    }
  },
  "mistmint_discord": {
    "raw_base": "https://raw.githubusercontent.com/Cannibal-Turtle/mistmint-discord/main",
    "paths": {
      "server_json": "config/server.json",
      "thread_id_map": "config/thread_id_map.json"
    }
  }
}
```

## `downstream_dispatch`

This tells `rss-feed` which downstream repos should be triggered after feeds/comments are updated.

```json
"downstream_dispatch": {
  "repos": [
    "Cannibal-Turtle/discord-webhook",
    "Cannibal-Turtle/mistmint-discord"
  ],
  "events": {
    "chapters": "trigger-discord-notify",
    "comments": "trigger-discord-comments"
  }
}
```

| Key | Meaning |
| --- | --- |
| `repos` | GitHub repositories that receive `repository_dispatch` events. |
| `events.chapters` | Event type sent after chapter feeds update. |
| `events.comments` | Event type sent after comments update. |

This is for GitHub workflow-to-workflow routing, not direct Discord posting.

## `primary_discord`

This is the default Discord integration used by direct posting tools.

```json
"primary_discord": {
  "integration": "discord_webhook",
  "always_post": true
}
```

| Key | Meaning |
| --- | --- |
| `integration` | Which integration block to use, usually `discord_webhook`. |
| `always_post` | Whether direct tools should keep posting to the primary Discord even when host-specific routes also exist. |

The primary Discord is your main/private/default server route.

## Integration blocks

Integration blocks describe where this repo can find config from another repo.

Example:

```json
"discord_webhook": {
  "raw_base": "https://raw.githubusercontent.com/Cannibal-Turtle/discord-webhook/main",
  "paths": {
    "server_json": "config/server.json",
    "roles_json": "config/roles.json"
  }
}
```

| Key | Meaning |
| --- | --- |
| `raw_base` | Raw GitHub base URL for the target repo/branch. |
| `paths` | Named config files inside that target repo. |

Common path keys:

| Path key | Usually points to | Used for |
| --- | --- | --- |
| `server_json` | `config/server.json` | Channel IDs, guild IDs, global mentions, server-level values. |
| `roles_json` | `config/roles.json` | Role IDs such as `admin`, novel roles, or staff roles. |
| `tag_roles` | `config/tag_roles.json` | Tag/category role mappings. |
| `novel_discord_map` | `config/novel_discord_map.toml` | Novel-specific Discord role/emoji/card config. |
| `thread_id_map` | `config/thread_id_map.json` | Short-code to forum/thread/channel mapping. |
| `state` | `state.json` | Downstream bot state file, when needed. |

## `host_discord_targets`

This section adds optional host-specific Discord destinations.

Example:

```json
"host_discord_targets": {
  "mistmint_haven": {
    "integration": "mistmint_discord",
    "routes": {
      "membership_update": {
        "type": "thread_map",
        "map_key": "thread_id_map",
        "default_path": "config/thread_id_map.json"
      },
      "special_announcement": {
        "type": "thread_map",
        "map_key": "thread_id_map",
        "default_path": "config/thread_id_map.json"
      },
      "publish_novel_card": {
        "type": "channel",
        "channel_key": "novel_cards_archive",
        "server_key": "server_json",
        "default_path": "config/server.json"
      }
    }
  }
}
```

This is an **extra** host route. It does not replace `primary_discord` unless the tool specifically chooses to only use the host route.

### Route types

| Type | Meaning |
| --- | --- |
| `thread_map` | Look up a novel/thread destination from a map file such as `thread_id_map.json`. |
| `channel` | Look up a fixed channel from `server.json` using `channel_key`. |

### Route examples

| Route name | Intended use |
| --- | --- |
| `membership_update` | Membership/premium update posts for a host/novel. |
| `special_announcement` | Special announcement posts for a host/novel. |
| `publish_novel_card` | Novel card archive/channel publishing. |

## `card_status_update`

This controls whether novel-card status changes can trigger a status update workflow.

```json
"card_status_update": {
  "enabled": true,
  "repo": "Cannibal-Turtle/rss-feed",
  "event_type": "update-novel-status"
}
```

| Key | Meaning |
| --- | --- |
| `enabled` | Turns the status update dispatch helper on/off. |
| `repo` | Repo that receives the update event. |
| `event_type` | GitHub `repository_dispatch` event type. |

## `feed_api_alerts`

This controls the optional alert for `feed_api` fallback.

```json
"feed_api_alerts": {
  "enabled": false,
  "integration": "discord_webhook",
  "channel_key": "mod",
  "mention_role_key": "admin",
  "mode_label": "api fallback",
  "max_items": 10
}
```

Default should stay `false` for fork-friendliness.

| Key | Meaning |
| --- | --- |
| `enabled` | If `false`, no alert is sent. Feed generation still works normally. |
| `integration` | Which integration block to use for channel/role lookup. |
| `channel_key` | Channel ID key to read from the target repo's `server.json`. |
| `mention_role_key` | Role ID key to read from the target repo's `roles.json`. |
| `mode_label` | Text shown in the alert, usually `api fallback`. |
| `max_items` | Maximum number of missing chapters shown in one Discord alert. |

With this config:

```json
"channel_key": "mod",
"mention_role_key": "admin"
```

the alert sends to:

```text
discord-webhook/config/server.json → "mod"
```

and pings:

```text
discord-webhook/config/roles.json → "admin"
```

If `DISCORD_BOT_TOKEN` is missing, the alert should skip cleanly. It should not break RSS generation.

The alert template is:

```text
message_templates/feed_api_alert.toml
```

## `comments`

This section stores comment-related runtime/integration settings.

Example:

```json
"comments": {
  "novelupdates": {
    "enabled": true,
    "host": {
      "name": "Novel Updates",
      "logo": "https://www.novelupdates.com/appicon.png"
    },
    "fetch_concurrency_default": 6,
    "fetch_concurrency_max": 10,
    "fetch_timeout_seconds": 20
  },
  "mistmint_haven": {
    "dashboard_comments_limit_default": 10,
    "dashboard_comments_page_scan_default": 1,
    "novel_comments_limit_default": 50,
    "novel_comments_page_scan_default": 1,
    "chapter_comments_limit_default": 100,
    "chapter_comments_page_scan_default": 3,
    "public_concurrency_default": 6,
    "public_concurrency_max": 10,
    "public_fetch_timeout_seconds": 20
  }
}
```

| Section | Meaning |
| --- | --- |
| `comments.novelupdates` | Novel Updates comment/readers settings. |
| `comments.mistmint_haven` | Mistmint dashboard/novel/chapter comment API runtime settings. |

Mistmint comment limit settings:

| Key | Meaning |
| --- | --- |
| `dashboard_comments_limit_default` | Page size for `/comments/trans/all-comments`; keep this small because each dashboard row may need slow chapter/reply enrichment. |
| `dashboard_comments_page_scan_default` | Number of dashboard pages to fetch. `1` means only `skipPage=0`. |
| `novel_comments_limit_default` | Page size for public `/comments/novel/{identifier}` novel-page comments. |
| `novel_comments_page_scan_default` | Maximum public novel-comment pages allowed. `1` means only `skipPage=0`; higher values stop early when the current page is empty or already reaches the existing XML cutoff. |
| `chapter_comments_limit_default` | Page size for `/comments/chapter/{chapterId}` lookups during enrichment/reply resolution. |
| `chapter_comments_page_scan_default` | Maximum chapter-thread pages allowed during enrichment/reply resolution. The scan stops early when the target comment is found, the page is empty, or the current page already reaches the target timestamp. |

The Python code clamps these values internally, so accidental huge numbers will not hammer Mistmint.

## What goes here vs elsewhere

Put this in `integrations.json`:

```text
downstream repo names
repository_dispatch event names
raw GitHub config locations
Discord route keys
optional integration feature switches
comment integration settings
```

Do **not** put this in `integrations.json`:

```text
Mistmint feed URLs
Mistmint API URLs
novel metadata
chapter source modes
fetch concurrency knobs
secrets/tokens/cookies
```

Those belong elsewhere:

| File | Belongs there |
| --- | --- |
| `mappings/hosts/<host>.toml` | Host facts: base URL, feed URL, API URL, token secret names. |
| `config/source_modes.json` | Runtime source choices: `feed`, `api`, `feed_api`, comments mode. |
| `config/runtime.json` | Runtime knobs such as fetch concurrency. |
| GitHub Secrets | Actual tokens, cookies, bot tokens, PATs. |

## Fork-safe behavior

A fork should be able to run basic RSS generation without Discord alerts or private Discord config.

For optional tools:

```text
missing config = skip optional feature
disabled config = skip optional feature
missing secret = warn or skip, not fail feed generation
```

Keep optional features disabled by default unless this repo specifically needs them.
