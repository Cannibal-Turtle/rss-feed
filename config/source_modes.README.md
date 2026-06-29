# Source Modes Config

This file explains `config/source_modes.json`.

`source_modes.json` controls how each host should fetch chapters and comments at runtime.
Host mapping files should keep host facts such as URLs, API endpoints, and auth secret names.
This config file should keep the choices for how the bot runs today.

## Current example

```json
{
  "mistmint_haven": {
    "free_chapters_source": "feed_api",
    "paid_chapters_source": "api",
    "chapter_mode": "auto",
    "comments_source": "auto"
  }
}
```

## Chapter source modes

These apply to:

```json
"free_chapters_source": "..."
"paid_chapters_source": "..."
```

| Mode       | Meaning                                                                                                      |
| ---------- | ------------------------------------------------------------------------------------------------------------ |
| `feed`     | Use the host-provided feed/RSS-style source only.                                                            |
| `api`      | Use the host API/chapter data source only.                                                                   |
| `feed_api` | Use the feed first, then scan mapped novels through API only if the host feed looks capped or overflow-risk. |

## Chapter mode

| Mode     | Meaning                                                                                   |
| -------- | ----------------------------------------------------------------------------------------- |
| `auto`   | Use real API/chapter data when available. This is the safest/default mode.                |
| `manual` | Use `mistmint_state.json` or manual chapter fallback when API/cookie data is unavailable. |

## Comment source modes

| Mode     | Meaning                                                                                                      |
| -------- | ------------------------------------------------------------------------------------------------------------ |
| `trans`  | Use the tokened author/dashboard comments endpoint. Best metadata and reply tracking, but token is required. |
| `public` | Use no-token public `/comments/novel/{identifier}` APIs. This is a novel-page comments fallback only; it does not resolve `chapterId` or fetch chapter comment threads. |
| `auto`   | Try `trans` first. If token is missing, expired, or unusable, fall back to `public`.                         |

Important: `public` mode is not a full replacement for `trans` comments. It does not call `/comments/chapter/{chapterId}` and should not be expected to fill a complete chapter-comments RSS feed. Use `trans` mode when chapter comments and richer reply tracking matter.

## Why this is in `config/`, not `mappings/hosts/`

`mappings/hosts/<host>.toml` should describe what the host is and what it supports.

Examples:

```text
base_url
free_feed_url
paid_feed_url
chapters_api_url
comments_api_url
token_secret
cookie_secret
```

`config/source_modes.json` should describe how this repo chooses to run right now.

Examples:

```text
free_chapters_source
paid_chapters_source
chapter_mode
comments_source
```

This keeps host facts separate from runtime choices.
::: 
