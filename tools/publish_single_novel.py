#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import os
import sys
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
    "TVITPA": {"color": "#f8d8c9", "forum_post_id": "1444214902322368675"},
    "TDLBKGC": {"color": "#90c3f2", "forum_post_id": "1438462596381413417"},
    "ATVHE":  {"color": "#9c8bb5", "forum_post_id": "1462019944823656608"},
    "WSMSC":  {"color": "#8a95a7", "forum_post_id": "1469896904761544845"},
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

# 🔑 channel resolution (THIS is the part you asked about)
if len(sys.argv) >= 3:
    CHANNEL_ID = int(sys.argv[2])
else:
    CHANNEL_ID = ARCHIVE_CHANNEL_ID

if SHORT_CODE not in NOVEL_META:
    print("Unknown short_code:", SHORT_CODE)
    sys.exit(1)

meta = NOVEL_META[SHORT_CODE]

intents = discord.Intents.default()
bot = discord.Client(intents=intents)

@bot.event
async def on_ready():
    state = load_state()
    channel = bot.get_channel(CHANNEL_ID)

    for host, hostdata in HOSTING_SITE_DATA.items():
        for title, novel in hostdata["novels"].items():
            print("Checking:", novel.get("short_code"))
            if novel.get("short_code", "").upper() != SHORT_CODE:
                continue

            api = fetch_api(novel["paid_feed_url"], hostdata["token_secret"])
            chapters = flatten_chapters(api)

            completed, next_free_dt, last_free_dt = compute_status(
                chapters, novel.get("last_chapter")
            )

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

            embed = Embed(
                title=f"<a:4751fluffybunnii:1368138331652755537><:pastelsparkles:1365569995794288680> **{title}**",
                color=int(meta["color"].lstrip("#"), 16)
            )

            # Only show Role field in the archive channel
            if channel.id == ARCHIVE_CHANNEL_ID:
                role = novel.get("discord_role_id")
                if role:
                    embed.add_field(
                        name=f"<:pastelflower:1365570061443530804> Role <:pastelflower:1365570061443530804>",
                        value=role,
                        inline=True
                    )

            embed.add_field(
                name=f"<:pastelflower:1365570061443530804> Status <:pastelflower:1365570061443530804>",
                value="\n".join(status_lines),
                inline=False
            )
            
            links = []
            
            # Host link (usually always present, but still safe)
            host_url = novel.get("novel_url")
            if host_url:
                links.append(f"[{host}]({host_url})")
            
            # NovelUpdates link (optional)
            nu_feed = novel.get("novelupdates_feed_url")
            if nu_feed:
                nu = nu_feed.rstrip("/").replace("/feed", "")
                links.append(f"[NU]({nu})")
            
            # Forum post (optional)
            forum_post_id = meta.get("forum_post_id")
            if forum_post_id:
                forum = f"https://discord.com/channels/1379303379221614702/{forum_post_id}"
                links.append(f"[Forum Post]({forum})")
            
            # Only add the field if at least one link exists
            if links:
                embed.add_field(
                    name=f"<:pastelflower:1365570061443530804> Links <:pastelflower:1365570061443530804>",
                    value=" • ".join(links),
                    inline=False
                )

            embed.set_thumbnail(url=novel.get("featured_image"))

            msg = await channel.send(embed=embed)
            channel_id = str(channel.id)
            message_id = str(msg.id)
            
            state.setdefault(SHORT_CODE, [])
            
            # avoid duplicates if script is re-run
            entry = {
                "channel_id": channel_id,
                "message_id": message_id,
            }
            
            if entry not in state[SHORT_CODE]:
                state[SHORT_CODE].append(entry)
                save_state(state)

            print("Posted novel card for", SHORT_CODE)
            await bot.close()
            return

    print("Novel not found in mappings.")
    await bot.close()

bot.run(TOKEN)
