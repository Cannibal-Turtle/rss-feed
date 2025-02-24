import requests
import feedparser
import os
import json
import re

# === CONFIGURATION ===
FREE_FEED_URL = "https://cannibal-turtle.github.io/rss-feed/free_chapters_feed.xml"
PAID_FEED_URL = "https://cannibal-turtle.github.io/rss-feed/paid_chapters_feed.xml"
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
if not DISCORD_WEBHOOK:
    raise ValueError("❌ DISCORD_WEBHOOK environment variable is not set! Make sure to add it as a GitHub Secret.")

# Files for persistent storage
HISTORY_FILE = "arc_history.json"  # JSON file for arc history
LAST_ARC_FILE = "last_arc.txt"       # To record the last announced locked arc

# === HELPER FUNCTIONS ===
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    else:
        return {"unlocked": [], "locked": []}

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)

def clean_feed_title(raw_title):
    """Clean the raw title from the feed by removing asterisks and extra whitespace."""
    return raw_title.replace("*", "").strip()

def format_stored_title(title):
    """
    Format the stored title.
    Expected format in storage: "【Arc 16】 The Abandoned Supporting Female Role"
    This function ensures there's exactly one space after the closing bracket
    and wraps the whole thing in bold markers.
    """
    # Use regex to reformat the title.
    match = re.match(r"(【Arc\s+\d+】)\s*(.*)", title)
    if match:
        return f"**{match.group(1)}** {match.group(2)}"
    return f"**{title}**"

def extract_arc_number_from_stored(title):
    """Extract the arc number from a stored title using the fullwidth brackets."""
    match = re.search(r"【Arc\s*(\d+)】", title)
    if match:
        return int(match.group(1))
    return None

# === FETCH FEEDS ===
free_feed = feedparser.parse(FREE_FEED_URL)
paid_feed = feedparser.parse(PAID_FEED_URL)

# Extract arc titles from feed entries that have " 001" in nameextend.
free_arcs_feed = [clean_feed_title(entry.get("nameextend", "").split(" 001")[0])
                   for entry in free_feed.entries if " 001" in entry.get("nameextend", "")]
paid_arcs_feed = [clean_feed_title(entry.get("nameextend", "").split(" 001")[0])
                   for entry in paid_feed.entries if " 001" in entry.get("nameextend", "")]

# === LOAD PERSISTENT HISTORY ===
history = load_history()

# === UPDATE HISTORY BASED ON FEEDS ===
# Any arc in the free feed is considered unlocked.
for arc in free_arcs_feed:
    if arc not in history["unlocked"]:
        history["unlocked"].append(arc)
    if arc in history["locked"]:
        history["locked"].remove(arc)

# Any new arc in the paid feed (not in unlocked or locked) gets added to locked.
for arc in paid_arcs_feed:
    if arc not in history["unlocked"] and arc not in history["locked"]:
        history["locked"].append(arc)

# Save updated history.
save_history(history)

# === DETERMINE NEW LOCKED ARC TO ANNOUNCE ===
new_locked_arc = history["locked"][0] if history["locked"] else None

# Read last announced locked arc to avoid duplicates.
if os.path.exists(LAST_ARC_FILE):
    with open(LAST_ARC_FILE, "r") as f:
        last_announced = f.read().strip()
else:
    last_announced = ""

if new_locked_arc == last_announced:
    print(f"✅ No new arc detected. Last announced locked arc: {last_announced}")
    exit(0)

with open(LAST_ARC_FILE, "w") as f:
    f.write(new_locked_arc)

# === BUILD THE DISCORD MESSAGE ===
# Use the extracted arc number from the new locked arc for the header.
world_number = extract_arc_number_from_stored(new_locked_arc)
if world_number is None:
    # Fallback to computed number if extraction fails.
    world_number = len(history["unlocked"]) + len(history["locked"]) + 1

# Build unlocked section using stored titles.
unlocked_section = "\n".join([format_stored_title(title) for title in history["unlocked"]])
# Build locked section.
locked_section_lines = [format_stored_title(title) for title in history["locked"]]
if locked_section_lines:
    # Prefix the first (new) locked arc with the arrow.
    locked_section_lines[0] = f"☛{locked_section_lines[0]}"
locked_section = "\n".join(locked_section_lines)

message = (
    f"<@&1329391480435114005> <@&1329502951764525187>\n"
    "## :loudspeaker: NEW ARC ALERT˚ · .˚ ༘:butterfly:⋆｡˚\n"
    f"***《World {world_number}》is Live for***\n"
    "### [Quick Transmigration: The Villain Is Too Pampered and Alluring]"
    "(https://dragonholic.com/novel/quick-transmigration-the-villain-is-too-pampered-and-alluring/) :Hehe:\n\n"
    "❀° ┄───────────────────────╮\n"
    "**`Unlocked 🔓`**\n"
    f"||\n{unlocked_section}\n||\n\n"
    "**`Locked 🔐`**\n"
    f"||\n{locked_section}\n||\n"
    "╰───────────────────────┄ °❀\n"
    "> *Advance access is ready for you on Dragonholic! :rose:*\n"
    "✎﹏﹏﹏﹏﹏﹏﹏﹏\n"
    "-# React to the :man_supervillain: @ https://discord.com/channels/1329384099609051136/1329419555600203776/1330466188349800458 to get notified on updates and announcements~"
)

data = {
    "content": message,
    "allowed_mentions": {"parse": []},
    "flags": 4  # Disable embeds
}

response = requests.post(DISCORD_WEBHOOK, json=data)
if response.status_code == 204:
    print(f"✅ Sent notification for new arc: {new_locked_arc}")
else:
    print(f"❌ Failed to send notification. Status Code: {response.status_code}")
