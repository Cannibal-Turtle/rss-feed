#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import os
import json
import re
import requests
from datetime import datetime, timezone
from dateutil import parser as dateparser

import discord
from discord import Embed

from novel_mappings import HOSTING_SITE_DATA

TOKEN = os.environ["DISCORD_BOT_TOKEN"]
STATE_FILE = "novel_status_targets.json"

ARCHIVE_CHANNEL_ID = 1463476725253144751

# ---------------- utils ----------------

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def fetch_api(url, cookie_env):
    headers = {}
    cookie = os.environ.get(cookie_env)
    if cookie:
        headers["Cookie"] = cookie
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()

_THREAD_ID_MAP_CACHE = {}

_NOVEL_ROLE_ID_MAP_CACHE = {}

def normalize_role_id(value):
    m = re.search(r"\d{5,}", str(value or ""))
    return m.group(0) if m else ""

def fetch_novel_role_id_map(hostdata):
    """
    Fetches short_code -> novel role ID from hostdata["novel_role_id_map_url"].
    Values may be raw IDs or <@&...>; this normalizes to raw IDs.
    """
    url = (hostdata.get("novel_role_id_map_url") or "").strip()

    if not url:
        return {}

    if url in _NOVEL_ROLE_ID_MAP_CACHE:
        return _NOVEL_ROLE_ID_MAP_CACHE[url]

    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()

    if not isinstance(data, dict):
        raise RuntimeError(f"novel_role_id_map_url did not return a JSON object: {url}")

    normalized = {
        str(k).upper(): normalize_role_id(v)
        for k, v in data.items()
        if normalize_role_id(v)
    }

    _NOVEL_ROLE_ID_MAP_CACHE[url] = normalized
    return normalized

def resolve_novel_role_mention(hostdata, short_code):
    role_map = fetch_novel_role_id_map(hostdata)
    role_id = role_map.get(short_code.upper())
    return f"<@&{role_id}>" if role_id else ""
    
def fetch_thread_id_map(hostdata):
    """
    Fetches the host's thread_id_map_url from novel_mappings.py.

    Expected JSON format:
    {
      "TVITPA": "1444214902322368675",
      "TDLBKGC": "1438462596381413417"
    }
    """
    url = (hostdata.get("thread_id_map_url") or "").strip()

    if not url:
        return {}

    if url in _THREAD_ID_MAP_CACHE:
        return _THREAD_ID_MAP_CACHE[url]

    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()

    if not isinstance(data, dict):
        raise RuntimeError(f"thread_id_map_url did not return a JSON object: {url}")

    normalized = {
        str(k).upper(): str(v).strip()
        for k, v in data.items()
        if str(v).strip()
    }

    _THREAD_ID_MAP_CACHE[url] = normalized
    return normalized

def resolve_forum_post_id(hostdata, short_code):
    """
    Gets the forum/thread ID for this novel from the host's thread_id_map_url.
    """
    thread_map = fetch_thread_id_map(hostdata)
    return thread_map.get(short_code.upper())

def normalize_api(api):
    if not api:
        return []
    if isinstance(api, dict):
        return api.get("data", [])
    if isinstance(api, list):
        return api
    return []

def flatten_chapters(api):
    volumes = normalize_api(api)
    out = []

    for vol in volumes:
        if not isinstance(vol, dict):
            continue
        for ch in vol.get("chapters", []):
            if not ch.get("isHidden"):
                out.append(ch)

    # order is safer than createdAt when present
    out.sort(key=lambda c: (
        c.get("order", 0),
        c.get("createdAt", "")
    ))
    return out

def human_delta(dt):
    if not dt:
        return "Unknown"
    now = datetime.now(timezone.utc)
    delta = dt - now
    if delta.total_seconds() <= 0:
        return "Available now"
    d, s = delta.days, delta.seconds
    h = s // 3600
    m = (s % 3600) // 60
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m and not d:
        parts.append(f"{m}m")
    return " ".join(parts)

def text_match(needle: str, haystack: str) -> bool:
    if not needle or not haystack:
        return False
    return re.search(
        rf"\b{re.escape(needle)}\b",
        haystack,
        flags=re.IGNORECASE
    ) is not None

def compute_status(chapters, last_chapter_text):
    completed = False
    next_free_dt = None
    last_free_dt = None

    last_chapter_text = (last_chapter_text or "").strip()

    # ── Case 1: Chapter N
    m = re.match(
        r"chapter\s+(\d+(\.\d+)?)(?:\b|[^0-9])",
        last_chapter_text,
        re.IGNORECASE
    )
    if m:
        target_num = m.group(1)
        for c in chapters:
            if str(c.get("chapterNumber", "")).strip() == target_num:
                completed = True
                break

    # ── Case 2: Extras / side stories / named chapters
    else:
        needle = last_chapter_text
        if needle:
            for c in chapters:
                if (
                    text_match(needle, c.get("chapterNumber") or "") or
                    text_match(needle, c.get("title") or "")
                ):
                    completed = True
                    break

    # ── Next free chapter logic
    now = datetime.now(timezone.utc)

    for c in chapters:
        free_at = c.get("freeAt")
        if not free_at:
            continue

        try:
            dt = dateparser.parse(free_at)
        except Exception:
            continue

        if dt > now:
            if not next_free_dt or dt < next_free_dt:
                next_free_dt = dt
        else:
            if not last_free_dt or dt > last_free_dt:
                last_free_dt = dt

    return completed, next_free_dt, last_free_dt

# ---------------- main ----------------

if len(sys.argv) < 2:
    print("Usage: python publish_single_novel.py <short_code> [channel_id]")
    sys.exit(1)

SHORT_CODE = sys.argv[1].upper()

# If a second channel/thread ID is provided, post there instead of auto-posting to mapped forum thread.
# It will still always post to the archive channel too.
EXTRA_CHANNEL_ID = None

if len(sys.argv) >= 3 and sys.argv[2].strip():
    EXTRA_CHANNEL_ID = int(sys.argv[2])

intents = discord.Intents.default()
bot = discord.Client(intents=intents)

async def resolve_channel(channel_id: int):
    """
    bot.get_channel can fail for some threads if they are not cached.
    fetch_channel is safer.
    """
    channel = bot.get_channel(channel_id)
    if channel is None:
        channel = await bot.fetch_channel(channel_id)
    return channel

async def build_forum_post_url(forum_post_id):
    """
    Builds the Forum Post link using the correct server ID.

    forum_post_id now comes from the host's thread_id_map_url.
    The bot fetches the channel/thread and reads the guild/server ID automatically.
    """
    forum_post_id = str(forum_post_id or "").strip()

    if not forum_post_id or forum_post_id.upper() == "N/A":
        return None

    try:
        forum_channel = await resolve_channel(int(forum_post_id))

        guild_id = None

        if getattr(forum_channel, "guild", None):
            guild_id = forum_channel.guild.id

        if not guild_id:
            guild_id = getattr(forum_channel, "guild_id", None)

        if not guild_id:
            print(f"Warning: could not find guild/server ID for forum_post_id {forum_post_id}")
            return None

        return f"https://discord.com/channels/{guild_id}/{forum_post_id}"

    except Exception as e:
        print(f"Warning: could not resolve forum post link for {forum_post_id}: {e}")
        return None

def build_embed_for_channel(
    *,
    title,
    novel,
    host,
    completed,
    next_free_dt,
    last_free_dt,
    target_channel_id,
    forum_post_url,
    novel_role_mention,
):
    status_lines = []

    status_lines.append("*Completed*" if completed else "*Ongoing*")

    if next_free_dt:
        unix_ts = int(next_free_dt.timestamp())
        status_lines.append(f"Next free chapter live **<t:{unix_ts}:R>**")

    elif last_free_dt:
        unix_ts = int(last_free_dt.timestamp())
        abs_time = last_free_dt.strftime("%A, %d %B %Y")
        status_lines.append(
            f"Last free chapter live **<t:{unix_ts}:R>** ({abs_time})"
        )

    else:
        status_lines.append("_No free chapter timing available_")

    # get color from mappings
    color_hex = novel.get("discord_color", "#ffffff")

    embed = Embed(
        title=f"<a:4751fluffybunnii:1368138331652755537><:pastelsparkles:1365569995794288680> **{title}**",
        color=int(color_hex.lstrip("#"), 16),
    )

    # Only show Role field in your archive channel.
    # This keeps formatting based on WHERE the message is posted.
    if target_channel_id == ARCHIVE_CHANNEL_ID and novel_role_mention:
        embed.add_field(
            name=f"<:pastelflower:1365570061443530804> Role <:pastelflower:1365570061443530804>",
            value=novel_role_mention,
            inline=True,
        )

    embed.add_field(
        name=f"<:pastelflower:1365570061443530804> Status <:pastelflower:1365570061443530804>",
        value="\n".join(status_lines),
        inline=False,
    )

    links = []

    # Host link
    host_url = novel.get("novel_url")
    if host_url:
        links.append(f"[{host}]({host_url})")

    # NovelUpdates link
    nu_feed = novel.get("novelupdates_feed_url")
    if nu_feed:
        nu = nu_feed.rstrip("/").replace("/feed", "")
        links.append(f"[NU]({nu})")

    # Forum post
    if forum_post_url:
        links.append(f"[Forum Post]({forum_post_url})")

    if links:
        embed.add_field(
            name=f"<:pastelflower:1365570061443530804> Links <:pastelflower:1365570061443530804>",
            value=" • ".join(links),
            inline=False,
        )

    embed.set_thumbnail(url=novel.get("featured_image"))

    return embed


@bot.event
async def on_ready():
    state = load_state()

    for host, hostdata in HOSTING_SITE_DATA.items():
        for title, novel in hostdata["novels"].items():
            print("Checking:", novel.get("short_code"))

            if novel.get("short_code", "").upper() != SHORT_CODE:
                continue

            api = fetch_api(novel["paid_feed_url"], hostdata["token_secret"])
            chapters = flatten_chapters(api)

            completed, next_free_dt, last_free_dt = compute_status(
                chapters,
                novel.get("last_chapter"),
            )

            # Get the forum/thread ID from the host's thread_id_map_url
            forum_post_id = resolve_forum_post_id(hostdata, SHORT_CODE)

            if not forum_post_id:
                print(f"Warning: no forum/thread ID found for {SHORT_CODE} in {host}'s thread_id_map_url.")

            forum_post_url = await build_forum_post_url(forum_post_id)

            novel_role_mention = resolve_novel_role_mention(hostdata, SHORT_CODE)

            # Always post to archive.
            # Only post to another channel/thread if you pass it as the second argument.
            # The mapped forum_post_id is ONLY used for the Forum Post link, not as a posting target.
            target_channel_ids = [ARCHIVE_CHANNEL_ID]
            
            if EXTRA_CHANNEL_ID and EXTRA_CHANNEL_ID != ARCHIVE_CHANNEL_ID:
                target_channel_ids.append(EXTRA_CHANNEL_ID)
            
            # Avoid duplicate posts
            target_channel_ids = list(dict.fromkeys(target_channel_ids))

            state.setdefault(SHORT_CODE, [])

            for target_channel_id in target_channel_ids:
                try:
                    channel = await resolve_channel(target_channel_id)

                    embed = build_embed_for_channel(
                        title=title,
                        novel=novel,
                        host=host,
                        completed=completed,
                        next_free_dt=next_free_dt,
                        last_free_dt=last_free_dt,
                        target_channel_id=int(channel.id),
                        forum_post_url=forum_post_url,
                        novel_role_mention=novel_role_mention,
                    )

                    msg = await channel.send(embed=embed)

                    entry = {
                        "channel_id": str(channel.id),
                        "message_id": str(msg.id),
                    }

                    if entry not in state[SHORT_CODE]:
                        state[SHORT_CODE].append(entry)
                        save_state(state)

                    print(f"Posted novel card for {SHORT_CODE} to {channel.id}")

                except Exception as e:
                    print(f"Failed to post novel card for {SHORT_CODE} to {target_channel_id}: {e}")

            await bot.close()
            return

    print("Novel not found in mappings.")
    await bot.close()


bot.run(TOKEN)
