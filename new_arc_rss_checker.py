import requests
import feedparser
import os
import json

# === CONFIGURATION ===
FREE_FEED_URL = "https://cannibal-turtle.github.io/rss-feed/free_chapters_feed.xml"
PAID_FEED_URL = "https://cannibal-turtle.github.io/rss-feed/paid_chapters_feed.xml"
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
if not DISCORD_WEBHOOK:
    raise ValueError("❌ DISCORD_WEBHOOK environment variable is not set! Add it as a GitHub Secret.")

# File for persistent storage of arc history
HISTORY_FILE = "arc_history.json"
# File to store last announced locked arc (to avoid duplicate messages)
LAST_ARC_FILE = "last_arc.txt"

# === HELPER FUNCTIONS ===
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    else:
        # Initialize with empty lists
        return {"unlocked": [], "locked": []}

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)

# === FETCH FEEDS ===
free_feed = feedparser.parse(FREE_FEED_URL)
paid_feed = feedparser.parse(PAID_FEED_URL)

# Extract arc titles from feeds based on first chapter (" 001")
# They are expected to be in the format: ***【Arc X】Arc Title 001***
free_arcs_feed = [entry.get("nameextend", "").split(" 001")[0].strip() 
                   for entry in free_feed.entries if " 001" in entry.get("nameextend", "")]
paid_arcs_feed = [entry.get("nameextend", "").split(" 001")[0].strip() 
                   for entry in paid_feed.entries if " 001" in entry.get("nameextend", "")]

# === LOAD PERSISTENT HISTORY ===
history = load_history()

# Update unlocked arcs: for every arc from free feed, if not already marked unlocked,
# add it to history and remove from locked if present.
for arc in free_arcs_feed:
    if arc not in history["unlocked"]:
        history["unlocked"].append(arc)
    if arc in history["locked"]:
        history["locked"].remove(arc)

# Update locked arcs: for every arc in the paid feed that is not already unlocked and not in locked,
# add it to the locked list.
for arc in paid_arcs_feed:
    if (arc not in history["unlocked"]) and (arc not in history["locked"]):
        history["locked"].append(arc)

# Save the updated history
save_history(history)

# Determine the new locked arc candidate (the first locked arc that is not yet announced)
new_locked_arc = history["locked"][0] if history["locked"] else None

# Read last announced locked arc
if os.path.exists(LAST_ARC_FILE):
    with open(LAST_ARC_FILE, "r") as f:
        last_announced = f.read().strip()
else:
    last_announced = ""

# If the new locked arc is the same as last announced, exit without sending a duplicate announcement.
if new_locked_arc == last_announced:
    print(f"✅ No new arc detected. Last announced locked arc: {last_announced}")
    exit(0)

# Update last announced arc file with the new locked arc
with open(LAST_ARC_FILE, "w") as f:
    f.write(new_locked_arc if new_locked_arc else "")

# === BUILD THE DISCORD MESSAGE ===

# Total arc numbering: first unlocked arcs then locked arcs
# (For example, if there are 5 unlocked arcs and 10 locked arcs, the new arc number is 5+10+1 = 16.)
total_unlocked = len(history["unlocked"])
total_locked = len(history["locked"])
new_arc_number = total_unlocked + total_locked + 1  # new arc becomes next number

# Build the sections
unlocked_section = "\n".join([f"**【Arc {i+1}】** {title}" for i, title in enumerate(history["unlocked"])])
locked_section = "\n".join(
    [f"**【Arc {i+total_unlocked+1}】** {title}" for i, title in enumerate(history["locked"])]
)

# To highlight the new locked arc, place the ☛ emoji in front of it.
# We'll assume the new locked arc is the first in the locked list.
if history["locked"]:
    locked_lines = locked_section.split("\n")
    # Find the line corresponding to history["locked"][0]
    locked_lines[0] = f"☛{locked_lines[0]}"
    locked_section = "\n".join(locked_lines)

# Construct message text
message = (
    f"<@&1329391480435114005> <@&1329502951764525187>\n"
    "## :loudspeaker: NEW ARC ALERT˚ · .˚ ༘:butterfly:⋆｡˚\n"
    f"***《World {new_arc_number}》is Live for***\n"
    "### [Quick Transmigration: The Villain Is Too Pampered and Alluring]"
    "(https://dragonholic.com/novel/quick-transmigration-the-villain-is-too-pampered-and-alluring/) :dracthyrhehe:\n\n"
    "❀° ┄───────────────────────╮\n"
    "**`Unlocked 🔓`**\n"
    f"||\n{unlocked_section}\n||\n\n"
    "**`Locked 🔐`**\n"
    f"||\n{locked_section}\n||\n"
    "╰───────────────────────┄ °❀\n"
    "> *Advance access is ready for you on Dragonholic! :rose:*\n"
    "✎﹏﹏﹏﹏﹏﹏﹏﹏\n"
    "-# React to the :man_supervillain: @ https://discord.com/channels/1329384099609051136/1329419555600203776/1330466188349800458 "
    "to get notified on updates and announcements~"
)

# Optionally disable embeds by setting flags (if desired)
data = {
    "content": message,
    "allowed_mentions": {"parse": []},
    "flags": 4
}

response = requests.post(DISCORD_WEBHOOK, json=data)
if response.status_code == 204:
    print(f"✅ Sent notification for new arc: {new_locked_arc}")
else:
    print(f"❌ Failed to send notification. Status Code: {response.status_code}")
