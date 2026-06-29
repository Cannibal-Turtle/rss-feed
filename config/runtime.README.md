# Runtime Config

This file explains `config/runtime.json`.

`runtime.json` contains safe runtime knobs for how hard the repo should fetch/process things.  
It should not contain host URLs, Discord routes, novel metadata, or secrets.

Current example:

```json
{
  "fetch": {
    "chapter_fetch_concurrency": 6,
    "free_fetch_concurrency": 6,
    "paid_fetch_concurrency": 6,
    "max_chapter_fetch_concurrency": 10
  }
}
```

## `fetch`

The `fetch` section controls async chapter-fetch concurrency.

```json
"fetch": {
  "chapter_fetch_concurrency": 6,
  "free_fetch_concurrency": 6,
  "paid_fetch_concurrency": 6,
  "max_chapter_fetch_concurrency": 10
}
```

| Key | Meaning |
| --- | --- |
| `chapter_fetch_concurrency` | Default number of novel/chapter fetches allowed at the same time. |
| `free_fetch_concurrency` | Free-chapter-specific concurrency override. |
| `paid_fetch_concurrency` | Paid-chapter-specific concurrency override. |
| `max_chapter_fetch_concurrency` | Safety cap so a bad override cannot run too many fetches at once. |

## Priority order

Fetch concurrency is resolved in this order:

```text
1. FREE_FETCH_CONCURRENCY / PAID_FETCH_CONCURRENCY environment variable
2. CHAPTER_FETCH_CONCURRENCY environment variable
3. config/runtime.json free_fetch_concurrency / paid_fetch_concurrency
4. config/runtime.json chapter_fetch_concurrency
5. hardcoded script default
6. max_chapter_fetch_concurrency safety cap
```

So this:

```json
{
  "fetch": {
    "chapter_fetch_concurrency": 6,
    "free_fetch_concurrency": 6,
    "paid_fetch_concurrency": 6,
    "max_chapter_fetch_concurrency": 10
  }
}
```

means:

```text
free generator uses 6
paid generator uses 6
anything above 10 is capped back down
```

## Environment variable overrides

These are useful for temporary workflow/manual runs.

| Environment variable | Meaning |
| --- | --- |
| `FREE_FETCH_CONCURRENCY` | Overrides free chapter fetch concurrency. |
| `PAID_FETCH_CONCURRENCY` | Overrides paid chapter fetch concurrency. |
| `CHAPTER_FETCH_CONCURRENCY` | Generic override for both free/paid if the specific one is not set. |

Example:

```powershell
$env:FREE_FETCH_CONCURRENCY = "3"
python free_feed_generator.py
```

or in GitHub Actions:

```yaml
env:
  FREE_FETCH_CONCURRENCY: "3"
```

## Supported optional max keys

The current config uses:

```json
"max_chapter_fetch_concurrency": 10
```

The helper also supports more specific caps if needed later:

```json
"max_free_fetch_concurrency": 10,
"max_paid_fetch_concurrency": 10
```

If no specific max exists, `max_chapter_fetch_concurrency` is used.

## Recommended values

| Situation | Suggested value |
| --- | --- |
| Normal Mistmint runs | `6` |
| Host/API feels slow or rate-limited | `3` or `4` |
| Fast test run, low risk | `8` |
| Hard upper safety cap | `10` |

Avoid setting very high numbers. More concurrency does not always mean faster results; it can cause API failures, timeouts, or temporary blocking.

## What goes here vs elsewhere

Put this in `runtime.json`:

```text
safe numeric runtime knobs
concurrency limits
timeouts if they are generic repo runtime settings
```

Do **not** put this in `runtime.json`:

```text
source modes
host URLs
Discord channel IDs
role IDs
novel mappings
secrets
```

Those belong elsewhere:

| File | Belongs there |
| --- | --- |
| `config/source_modes.json` | `free_chapters_source`, `paid_chapters_source`, `chapter_mode`, `comments_source`. |
| `config/integrations.json` | External repo routes, Discord route keys, optional integration feature switches. |
| `mappings/hosts/<host>.toml` | Host facts like feed URLs and API endpoints. |
| GitHub Secrets | Real tokens, cookies, bot tokens, PATs. |

## Fork-safe behavior

`runtime.json` should be safe for public forks.  
It should only contain harmless tuning values.

A fork can use:

```json
{
  "fetch": {
    "chapter_fetch_concurrency": 4,
    "max_chapter_fetch_concurrency": 8
  }
}
```

and ignore the rest if it only wants basic RSS generation.
