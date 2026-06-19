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

NOVEL_META = {
    "TVITPA": {"forum_post_id": "1444214902322368675"},
    "TDLBKGC": {"forum_post_id": "1438462596381413417"},
    "ATVHE":  {"forum_post_id": "1462019944823656608"},
    "WSMSC":  {"forum_post_id": "1469896904761544845"},
    "HIAFLG": {"forum_post_id": "1471742754261438620"},
    "EC": {"forum_post_id": "1488217762231877743"},

    # If the novel has no forum post link, use:
    # "BOE": {"forum_post_id": "N/A"},
}

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
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m and not d: parts.append(f"{m}m")
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

# 🔑 target resolution
# Always post to your archive channel.
# If a second channel/thread ID is provided, also post there.
EXTRA_CHANNEL_ID = None

if len(sys.argv) >= 3 and sys.argv[2].strip():
    EXTRA_CHANNEL_ID = int(sys.argv[2])

TARGET_CHANNEL_IDS = [ARCHIVE_CHANNEL_ID]

# Avoid posting twice if you accidentally enter the archive channel as the extra ID.
if EXTRA_CHANNEL_ID and EXTRA_CHANNEL_ID != ARCHIVE_CHANNEL_ID:
    TARGET_CHANNEL_IDS.append(EXTRA_CHANNEL_ID)

if SHORT_CODE not in NOVEL_META:
    print(f"ERROR: {SHORT_CODE} is missing from NOVEL_META.")
    print('Add it with a forum_post_id, or use {"forum_post_id": "N/A"} if it has no forum link.')
    sys.exit(1)

meta = NOVEL_META[SHORT_CODE]

forum_post_id_for_link = str(meta.get("forum_post_id", "")).strip()

if not forum_post_id_for_link:
    print(f"ERROR: {SHORT_CODE} has empty forum_post_id in NOVEL_META.")
    print('Use {"forum_post_id": "N/A"} if this novel has no forum link.')
    sys.exit(1)

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

async def build_forum_post_url(meta):
    """
    Builds the Forum Post link using the correct server ID.

    NOVEL_META only needs forum_post_id.
    The bot fetches the channel/thread and reads the guild/server ID automatically.
    """
    forum_post_id = str(meta.get("forum_post_id", "")).strip()

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
    meta,
    completed,
    next_free_dt,
    last_free_dt,
    target_channel_id,
    forum_post_url,
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
    if target_channel_id == ARCHIVE_CHANNEL_ID:
        role = novel.get("discord_role_id")
        if role:
            embed.add_field(
                name=f"<:pastelflower:1365570061443530804> Role <:pastelflower:1365570061443530804>",
                value=role,
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
            
            forum_post_url = await build_forum_post_url(meta)
            
            state.setdefault(SHORT_CODE, [])

            for target_channel_id in TARGET_CHANNEL_IDS:
                try:
                    channel = await resolve_channel(target_channel_id)

                    embed = build_embed_for_channel(
                        title=title,
                        novel=novel,
                        host=host,
                        meta=meta,
                        completed=completed,
                        next_free_dt=next_free_dt,
                        last_free_dt=last_free_dt,
                        target_channel_id=int(channel.id),
                        forum_post_url=forum_post_url,
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
