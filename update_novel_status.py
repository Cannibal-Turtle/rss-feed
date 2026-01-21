#!/usr/bin/env python3
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

# ─── CONFIG ────────────────────────────────────────────────────────────────────
TOKEN = os.environ["DISCORD_BOT_TOKEN"]
TARGETS_FILE = "novel_status_targets.json"
# ────────────────────────────────────────────────────────────────────────────────


# ─── Helpers ────────────────────────────────────────────────────────────────────

def load_targets():
    with open(TARGETS_FILE, encoding="utf-8") as f:
        return json.load(f)

def resolve_short_code(title: str, host: str) -> str | None:
    title = title.strip().lower()
    host  = host.strip().lower()

    for h, data in HOSTING_SITE_DATA.items():
        if h.lower() != host:
            continue
        for novel_title, novel in data["novels"].items():
            if novel_title.strip().lower() == title:
                return novel.get("short_code")
    return None

def fetch_api(url, cookie_env):
    headers = {}
    cookie = os.environ.get(cookie_env)
    if cookie:
        headers["Cookie"] = cookie
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()

def flatten_chapters(api):
    vols = api.get("data", []) if isinstance(api, dict) else api or []
    out = []
    for v in vols:
        for c in v.get("chapters", []):
            if not c.get("isHidden"):
                out.append(c)
    out.sort(key=lambda c: (c.get("order", 0), c.get("createdAt", "")))
    return out

def compute_status(chapters, last_chapter_text):
    completed = False
    num = None
    m = re.search(r"(\d+(\.\d+)?)", last_chapter_text or "")
    if m:
        num = float(m.group(1))

    nums = []
    for c in chapters:
        try:
            nums.append(float(c["chapterNumber"]))
        except:
            pass

    if num and nums and max(nums) >= num:
        completed = True

    now = datetime.now(timezone.utc)
    next_free = None
    for c in chapters:
        if not c.get("isFree") and c.get("freeAt"):
            try:
                dt = dateparser.parse(c["freeAt"])
                if dt > now and (not next_free or dt < next_free):
                    next_free = dt
            except:
                pass

    return completed, next_free

def build_status_value(completed, next_free_dt):
    lines = []
    lines.append("*Completed*" if completed else "*Ongoing*")

    if next_free_dt:
        ts = int(next_free_dt.timestamp())
        lines.append(f"Next free chapter live **<t:{ts}:R>**")
    elif completed:
        lines.append("**All chapters are now free**")
    else:
        lines.append("_Free release schedule not available_")

    return "\n".join(lines)

def update_status_field(embed: Embed, new_value: str) -> Embed:
    """
    Finds the field whose name contains 'status' (case-insensitive)
    and replaces only its value.
    """
    found = False
    new_fields = []

    for f in embed.fields:
        if "status" in f.name.lower():
            new_fields.append(
                Embed.Field(name=f.name, value=new_value, inline=f.inline)
            )
            found = True
        else:
            new_fields.append(f)

    if not found:
        raise RuntimeError("No Status field found in embed")

    embed.clear_fields()
    for f in new_fields:
        embed.add_field(name=f.name, value=f.value, inline=f.inline)

    return embed


# ─── Main ───────────────────────────────────────────────────────────────────────

if len(sys.argv) != 3:
    print("Usage: python update_novel_status.py <title> <host>")
    sys.exit(1)

TITLE = sys.argv[1]
HOST  = sys.argv[2]

short_code = resolve_short_code(TITLE, HOST)
if not short_code:
    raise SystemExit(f"❌ Cannot resolve short_code for {TITLE} ({HOST})")

targets = load_targets().get(short_code, [])
if not targets:
    raise SystemExit(f"⚠️ No targets configured for {short_code}")

intents = discord.Intents.default()
bot = discord.Client(intents=intents)

@bot.event
async def on_ready():
    print(f"🔄 Updating status for {short_code}")

    for host_name, data in HOSTING_SITE_DATA.items():
        for novel_title, novel in data["novels"].items():
            if novel.get("short_code") != short_code:
                continue

            api = fetch_api(novel["paid_feed_url"], data["token_secret"])
            chapters = flatten_chapters(api)
            completed, next_free = compute_status(chapters, novel.get("last_chapter"))
            status_value = build_status_value(completed, next_free)

            for t in targets:
                ch = bot.get_channel(int(t["channel_id"]))
                if not ch:
                    print("❌ Channel not found:", t["channel_id"])
                    continue

                msg = await ch.fetch_message(int(t["message_id"]))
                if not msg.embeds:
                    print("❌ No embed on message", msg.id)
                    continue

                embed = msg.embeds[0]
                embed = update_status_field(embed, status_value)

                await msg.edit(embed=embed)
                print(f"✅ Updated {short_code} → {msg.id}")

    await bot.close()

bot.run(TOKEN)
