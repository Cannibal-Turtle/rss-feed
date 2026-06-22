# RSS Template Placeholders

This document lists placeholders that can be used when building Discord message templates from the generated RSS feeds.

These placeholders are intended for future TOML-based Discord message templates.

Example:

```toml
content = "{role_mention}"

[[embeds]]
title = "{custom_emoji} {title}"
url = "{link}"
description = """
## {chapter} — {chaptername}

{volume}

{description}
"""
color = "paid_chapter"
```

---

# Common item placeholders

These are shared or commonly useful across the generated RSS feeds.

| Placeholder            | Meaning                                                     |
| ---------------------- | ----------------------------------------------------------- |
| `{title}`              | Feed item title. Usually the novel title for chapter feeds. |
| `{volume}`             | Arc or volume label, if present.                            |
| `{chapter}`            | Chapter label, e.g. `Chapter 2`.                            |
| `{chaptername}`        | Chapter display name, e.g. `***1.2***`.                     |
| `{link}`               | Main link for the item. Usually chapter URL or comment URL. |
| `{description}`        | RSS item description.                                       |
| `{category}`           | Category such as `SFW` or `NSFW`, if present.               |
| `{translator}`         | Translator name.                                            |
| `{short_code}`         | Stable novel short code, e.g. `AMLWC`, `TDLBKGC`, `EC`.     |
| `{featured_image}`     | Featured image URL.                                         |
| `{featured_image_url}` | Alias for `{featured_image}`.                               |
| `{pub_date}`           | RSS publication date.                                       |
| `{host}`               | Hosting site name, e.g. `Mistmint Haven`.                   |
| `{host_logo}`          | Host logo URL.                                              |
| `{host_logo_url}`      | Alias for `{host_logo}`.                                    |
| `{guid}`               | RSS item GUID.                                              |
| `{guid_is_permalink}`  | Whether the GUID is marked as a permalink.                  |

---

# Free chapter feed placeholders

Source feed:

```text
free_chapters_feed.xml
```

Expected item fields:

| Placeholder            | RSS source                  |
| ---------------------- | --------------------------- |
| `{title}`              | `<title>`                   |
| `{volume}`             | `<volume>`                  |
| `{chapter}`            | `<chapter>`                 |
| `{chaptername}`        | `<chaptername>`             |
| `{link}`               | `<link>`                    |
| `{description}`        | `<description>`             |
| `{category}`           | `<category>`                |
| `{translator}`         | `<translator>`              |
| `{short_code}`         | `<short_code>`              |
| `{featured_image}`     | `<featuredImage url="...">` |
| `{featured_image_url}` | `<featuredImage url="...">` |
| `{pub_date}`           | `<pubDate>`                 |
| `{host}`               | `<host>`                    |
| `{host_logo}`          | `<hostLogo url="...">`      |
| `{host_logo_url}`      | `<hostLogo url="...">`      |
| `{guid}`               | `<guid>`                    |
| `{guid_is_permalink}`  | `<guid isPermaLink="...">`  |

Useful free chapter template fields:

```text
{title}
{volume}
{chapter}
{chaptername}
{link}
{description}
{category}
{translator}
{short_code}
{featured_image}
{featured_image_url}
{pub_date}
{host}
{host_logo}
{host_logo_url}
{guid}
{guid_is_permalink}
```

Example:

```toml
content = "{role_mention}"

[[embeds]]
title = "{custom_emoji} {title}"
url = "{link}"
description = """
## {chapter}

{chaptername}

{description}
"""
color = "free_chapter"

[embeds.thumbnail]
url = "{featured_image}"

[embeds.footer]
text = "{host} · {translator}"
icon_url = "{host_logo}"
```

---

# Paid chapter feed placeholders

Source feed:

```text
paid_chapters_feed.xml
```

Expected item fields:

| Placeholder            | RSS source                  |
| ---------------------- | --------------------------- |
| `{title}`              | `<title>`                   |
| `{volume}`             | `<volume>`                  |
| `{chapter}`            | `<chapter>`                 |
| `{chaptername}`        | `<chaptername>`             |
| `{link}`               | `<link>`                    |
| `{description}`        | `<description>`             |
| `{category}`           | `<category>`                |
| `{translator}`         | `<translator>`              |
| `{short_code}`         | `<short_code>`              |
| `{featured_image}`     | `<featuredImage url="...">` |
| `{featured_image_url}` | `<featuredImage url="...">` |
| `{coin}`               | `<coin>`                    |
| `{pub_date}`           | `<pubDate>`                 |
| `{host}`               | `<host>`                    |
| `{host_logo}`          | `<hostLogo url="...">`      |
| `{host_logo_url}`      | `<hostLogo url="...">`      |
| `{guid}`               | `<guid>`                    |
| `{guid_is_permalink}`  | `<guid isPermaLink="...">`  |

Useful paid chapter template fields:

```text
{title}
{volume}
{chapter}
{chaptername}
{link}
{description}
{category}
{translator}
{short_code}
{featured_image}
{featured_image_url}
{coin}
{pub_date}
{host}
{host_logo}
{host_logo_url}
{guid}
{guid_is_permalink}
```

Example:

```toml
content = "{role_mention}"

[[embeds]]
title = "{custom_emoji} {title}"
url = "{link}"
description = """
## {chapter} — {chaptername}

{volume}

{coin}

{description}
"""
color = "paid_chapter"

[embeds.thumbnail]
url = "{featured_image}"

[embeds.footer]
text = "{host} · {translator}"
icon_url = "{host_logo}"
```

---

# Comments feed placeholders

Source feed:

```text
aggregated_comments_feed.xml
```

Expected item fields may vary depending on comment source.

| Placeholder           | RSS source                                   |
| --------------------- | -------------------------------------------- |
| `{title}`             | `<title>`                                    |
| `{link}`              | `<link>`                                     |
| `{description}`       | `<description>`                              |
| `{creator}`           | `<dc:creator>` or equivalent creator field   |
| `{author}`            | `<author>` or equivalent author field        |
| `{pub_date}`          | `<pubDate>`                                  |
| `{host}`              | `<host>`                                     |
| `{short_code}`        | `<short_code>`, if present                   |
| `{reply_chain}`       | Reply-chain/custom comment field, if present |
| `{guid}`              | `<guid>`                                     |
| `{guid_is_permalink}` | `<guid isPermaLink="...">`                   |

Useful comments template fields:

```text
{title}
{link}
{description}
{creator}
{author}
{pub_date}
{host}
{short_code}
{reply_chain}
{guid}
{guid_is_permalink}
```

Example:

```toml
content = ""

[[embeds]]
title = "{title}"
url = "{link}"
description = """
{description}

{reply_chain}
"""
color = "comments"

[embeds.footer]
text = "{host} · {creator}"
```

---

# Discord-enriched placeholders

These are not directly from RSS. They are added by the Discord bot using local config or mapping data.

| Placeholder          | Source                                                    |
| -------------------- | --------------------------------------------------------- |
| `{role_mention}`     | Discord role mention from novel short code.               |
| `{role_id}`          | Discord role ID from novel short code.                    |
| `{custom_emoji}`     | Novel custom emoji from Discord config.                   |
| `{discord_role_url}` | Novel role selection URL from Discord config.             |
| `{tags}`             | Novel tags from mapping metadata.                         |
| `{novel_url}`        | Novel page URL from mapping metadata.                     |
| `{theme_color}`      | Novel theme color, if later renamed from `discord_color`. |
| `{discord_color}`    | Novel branding color from mapping metadata, if exposed.   |

Useful Discord-enriched fields:

```text
{role_mention}
{role_id}
{custom_emoji}
{discord_role_url}
{tags}
{novel_url}
{theme_color}
{discord_color}
```

---

# Suggested aliases

These aliases make templates easier to write and reduce confusion.

| Alias                  | Same as            |
| ---------------------- | ------------------ |
| `{featured_image_url}` | `{featured_image}` |
| `{host_logo_url}`      | `{host_logo}`      |

---

# Suggested raw placeholders for later

If the renderer later supports raw RSS access, use this style:

```text
{raw:title}
{raw:link}
{raw:description}
{raw:volume}
{raw:chapter}
{raw:chaptername}
{raw:short_code}
{raw:featuredImage}
{raw:hostLogo}
```

These are optional future placeholders. They are useful if a template needs direct access to an RSS element before the bot normalizes it.

---

# Suggested TOML message-builder format

A flexible template should support message content plus one or more embeds.

```toml
content = "{role_mention}"

[[embeds]]
title = "{custom_emoji} {title}"
url = "{link}"
description = """
## {chapter} — {chaptername}

{volume}

{description}
"""
color = "paid_chapter"

[embeds.author]
name = "{translator}"
icon_url = "{host_logo}"

[embeds.thumbnail]
url = "{featured_image}"

[embeds.footer]
text = "{host}"
icon_url = "{host_logo}"

[[embeds.fields]]
name = "Novel"
value = "[{title}]({novel_url})"
inline = true

[[embeds.fields]]
name = "Chapter"
value = "[{chapter}]({link})"
inline = true

[[embeds.fields]]
name = "Short code"
value = "`{short_code}`"
inline = true
```

---

# Minimum renderer behavior

The template renderer should replace unknown placeholders with an empty string instead of crashing.

Example:

```text
{missing_field}
```

should render as:

```text
```

This makes templates safer to edit directly in GitHub.
