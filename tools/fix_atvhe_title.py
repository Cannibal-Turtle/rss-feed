#!/usr/bin/env python3
import os
import json
import discord

TOKEN = os.environ["DISCORD_BOT_TOKEN"]
STATE_FILE = "novel_status_targets.json"

SHORT_CODE = "ATVHE"

NEW_TITLE = (
    "<a:4751fluffybunnii:1368138331652755537>"
    "<:pastelsparkles:1365569995794288680> "
    "**After Transmigrating into the Villain, "
    "I Got a HE with the Female Lead's Older Brother**"
)

intents = discord.Intents.default()
bot = discord.Client(intents=intents)


def load_state():
    with open(STATE_FILE, encoding="utf-8") as f:
        return json.load(f)


@bot.event
async def on_ready():
    state = load_state()

    targets = state.get(SHORT_CODE, [])
    if not targets:
        print("No targets found.")
        await bot.close()
        return

    for entry in targets:
        channel_id = int(entry["channel_id"])
        message_id = int(entry["message_id"])

        channel = bot.get_channel(channel_id)
        if not channel:
            print("Channel not found:", channel_id)
            continue

        try:
            msg = await channel.fetch_message(message_id)
        except Exception as e:
            print("Failed to fetch message:", e)
            continue

        embed = msg.embeds[0]
        embed.title = NEW_TITLE

        await msg.edit(embed=embed)
        print("Updated title in channel", channel_id)

    await bot.close()


bot.run(TOKEN)
