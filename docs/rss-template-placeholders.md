RSS Feed Template Placeholder Reference
======================================

Purpose
-------
Use this as the placeholder reference for future MonitoRSS-style TOML message templates.

Rule of thumb:
- XML tag text becomes {tag_name}.
- XML attribute URLs become friendly snake_case placeholders.
- Optional/missing fields should render as an empty string, not crash the bot.
- Discord-only values come from bot config, not directly from RSS.

Source feeds
------------
free_chapters_feed.xml
paid_chapters_feed.xml
aggregated_comments_feed.xml

Recommended renderer behavior
-----------------------------
If a placeholder is missing from a feed item, render it as "".
Example: {coin} exists in paid chapters only. In free/comments templates, it should become empty.

Common placeholders shared by all three feeds
---------------------------------------------
{title}
  From: <title>
  Meaning: novel title / series title.

{link}
  From: <link>
  Meaning: chapter URL or comment target URL.

{description}
  From: <description>
  Meaning:
    - Free/paid feeds: novel/chapter description text.
    - Comments feed: comment body.

{category}
  From: <category>
  Meaning: SFW / NSFW category.

{translator}
  From: <translator>
  Meaning: translator name.

{short_code}
  From: <short_code>
  Meaning: stable novel short code, e.g. AMLWC, HIAFLG, TDLBKGC.

{featured_image}
  From: <featuredImage url="..."/>
  Meaning: novel cover / featured image URL.

{featured_image_url}
  Alias for: {featured_image}

{host}
  From: <host>
  Meaning: source host, e.g. Mistmint Haven, Novel Updates, Dragonholic.

{host_logo}
  From: <hostLogo url="..."/>
  Meaning: source host logo URL.

{host_logo_url}
  Alias for: {host_logo}

{pub_date}
  From: <pubDate>
  Meaning: RSS publication date string.

{guid}
  From: <guid>
  Meaning: RSS item GUID.

{guid_is_permalink}
  From: <guid isPermaLink="...">
  Meaning: usually false.

Free chapter feed placeholders
------------------------------
Feed: free_chapters_feed.xml

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

Free-specific notes:
- {volume} comes from <volume>.
- {chapter} comes from <chapter>, e.g. Chapter 40.
- {chaptername} comes from <chaptername>, e.g. ***Peace Talk*** or ***15.3***.
- {chaptername} may already include Markdown styling.

Paid chapter feed placeholders
------------------------------
Feed: paid_chapters_feed.xml

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

Paid-specific notes:
- {coin} comes from <coin>, e.g. <:mistmint_currency:1433046707121422487> 5.
- {chaptername} may contain arc-local numbering, e.g. ***1.2***.
- {volume} is useful for arc display, e.g. Arc 1: The Charming Landlord Is Too Hard to Handle.

Comments feed placeholders
--------------------------
Feed: aggregated_comments_feed.xml

{title}
{chapter}
{link}
{creator}
{author}
{description}
{reply_chain}
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

Comments-specific notes:
- {creator} comes from <dc:creator>.
- {author} should be an alias for {creator}, because feed parsers may expose dc:creator as author/dc_creator.
- {description} is the comment text.
- {reply_chain} comes from <reply_chain> and is optional.
- Comments feed does not normally have {volume}, {chaptername}, or {coin}.

Discord-enriched placeholders
-----------------------------
These do not come directly from RSS. They should be added by the Discord bot renderer using config/novel_discord_map.toml and local config.

{role_id}
  From: config/novel_discord_map.toml -> role_id.

{role_mention}
  Derived from: {role_id}, formatted as <@&role_id>.

{custom_emoji}
  From: config/novel_discord_map.toml -> custom_emoji.

{discord_role_url}
  From: config/novel_discord_map.toml -> role_url.

{role_url}
  Alias for: {discord_role_url}.

{tags}
  From: mapping/config if available, not RSS.

{novel_url}
  From: mapping/config if available, not RSS.

{theme_color}
  Optional future alias for novel branding color / discord_color.

Suggested aliases
-----------------
These aliases make templates easier to read while preserving old feed tag names.

{chapter_name}
  Alias for: {chaptername}

{featured_image_url}
  Alias for: {featured_image}

{host_logo_url}
  Alias for: {host_logo}

{author}
  Alias for: {creator} in comments feed.

{role_url}
  Alias for: {discord_role_url}.

Example TOML template using these placeholders
----------------------------------------------
content = "{role_mention}"

[[embeds]]
title = "{custom_emoji} {title}"
url = "{link}"
description = """
## {chapter} {chaptername}

{volume}

{description}
"""
color = "paid_chapter"

[embeds.thumbnail]
url = "{featured_image}"

[embeds.footer]
text = "{host} · {translator}"
icon_url = "{host_logo}"

[[embeds.fields]]
name = "Novel"
value = "[{title}]({novel_url})"
inline = true

[[embeds.fields]]
name = "Short code"
value = "`{short_code}`"
inline = true

Implementation notes
--------------------
- The renderer should use a SafeDict-style formatter so missing placeholders render as empty strings.
- For image URLs, skip the whole image/thumbnail block if the rendered URL is empty.
- For embed fields, skip fields where both name and value render empty.
- For color, allow either:
    color = "paid_chapter"  # lookup from config/embeds.json
    color = "A87676"        # direct hex fallback
- Do not use eval for placeholders.
