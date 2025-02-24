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
HISTORY_FILE = "arc_history.json"  # Persistent JSON file for all arc names
LAST_ARC_FILE = "last_arc.txt"       # To check if the new locked arc was already announced

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

def clean_title(raw_title):
    """
    Remove unwanted markdown and fullwidth bracket characters.
    Expected raw title example: "【Arc 16】The Abandoned Supporting Female Role"
    """
    title = raw_title.replace("*", "").strip()
    # Remove fullwidth brackets if present:
    title = title.replace("【", "").replace("】", "")
    return title

def format_title(arc_number, title):
    """
    Re-add standard formatting for display.
    """
    return f"**【Arc {arc_number}】** {title}"

def extract_arc_number(title):
    """
    Extracts the arc number from a title string.
    Assumes title (after cleaning) is in the format "Arc X ..." or starts with "Arc X".
    """
    # First, remove any extra characters by cleaning the title:
    cleaned = clean_title(title)
    match = re.search(r"Arc\s*(\d+)", cleaned, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None

# === FETCH FEEDS ===
free_feed = feedparser.parse(FREE_FEED_URL)
paid_feed = feedparser.parse(PAID_FEED_URL)

# Extract arc titles from feed entries that have " 001" (first chapter indicator)
# We'll clean them so that stored history is plain text.
free_arcs_feed = [clean_title(entry.get("nameextend", "").split(" 001")[0])
                   for entry in free_feed.entries if " 001" in entry.get("nameextend", "")]
paid_arcs_feed = [clean_title(entry.get("nameextend", "").split(" 001")[0])
                   for entry in paid_feed.entries if " 001" in entry.get("nameextend", "")]

# === LOAD PERSISTENT HISTORY ===
history = load_history()

# === UPDATE HISTORY BASED ON FEEDS ===
# Add any arc from the free feed into the unlocked list.
for arc in free_arcs_feed:
    if arc not in history["unlocked"]:
        history["unlocked"].append(arc)
    if arc in history["locked"]:
        history["locked"].remove(arc)

# Add any arc from the paid feed into the locked list if not already unlocked or stored.
for arc in paid_arcs_feed:
    if (arc not in history["unlocked"]) and (arc not in history["locked"]):
        history["locked"].append(arc)

# Save updated history.
save_history(history)

# --- Deduplicate unlocked list in case of duplicates ---
history["unlocked"] = list(dict.fromkeys(history["unlocked"]))

# === DETERMINE NEW LOCKED ARC TO ANNOUNCE ===
# We assume that the first element of the locked list is the next new arc.
new_locked_arc = history["locked"][0] if history["locked"] else None

# Read the last announced locked arc from file to avoid duplicates.
if os.path.exists(LAST_ARC_FILE):
    with open(LAST_ARC_FILE, "r") as f:
        last_announced = f.read().strip()
else:
    last_announced = ""

if new_locked_arc == last_announced:
    print(f"✅ No new arc detected. Last announced locked arc: {last_announced}")
    exit(0)

with open(LAST_ARC_FILE, "w") as f:
    f.write(new_locked_arc if new_locked_arc else "")

# === BUILD THE DISCORD MESSAGE ===

# Extract the arc number from the new locked arc.
extracted_num = extract_arc_number(new_locked_arc) if new_locked_arc else None
if extracted_num is not None:
    world_number = extracted_num
else:
    # Fallback: compute from counts (though ideally new_locked_arc includes its arc number)
    world_number = len(history["unlocked"]) + len(history["locked"]) + 1

# Build the unlocked section using stored titles.
# For display, we re-add standard formatting by extracting the arc number from each title.
unlocked_section_lines = []
for title in history["unlocked"]:
    num = extract_arc_number(title)
    if num is None:
        # Fallback: assign sequentially
        num = len(unlocked_section_lines) + 1
    # Use the stored title without extra formatting; our format_title function will re-add it.
    unlocked_section_lines.append(format_title(num, title))
unlocked_section = "\n".join(unlocked_section_lines)

# Build the locked section similarly.
locked_section_lines = []
# We want to display all locked arcs.
for title in history["locked"]:
    num = extract_arc_number(title)
    if num is None:
        num = len(history["unlocked"]) + len(locked_section_lines) + 1
    locked_section_lines.append(format_title(num, title))
# Mark the new locked arc (first in the list) with the ☛ emoji.
if locked_section_lines:
    locked_section_lines[0] = f"☛{locked_section_lines[0]}"
locked_section = "\n".join(locked_section_lines)

# Build the final message.
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
    "-# React to the :man_supervillain: @ https://discord.com/channels/1329384099609051136/1329419555600203776/1330466188349800458 "
    "to get notified on updates and announcements~"
)

data = {
    "content": message,
    "allowed_mentions": {"parse": []},
    "flags": 4  # Disables embeds
}

response = requests.post(DISCORD_WEBHOOK, json=data)
if response.status_code == 204:
    print(f"✅ Sent notification for new arc: {new_locked_arc}")
else:
    print(f"❌ Failed to send notification. Status Code: {response.status_code}")
