import requests
import feedparser
import os
import json

# === CONFIGURATION ===
FREE_FEED_URL = "https://cannibal-turtle.github.io/rss-feed/free_chapters_feed.xml"
PAID_FEED_URL = "https://cannibal-turtle.github.io/rss-feed/paid_chapters_feed.xml"
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
if not DISCORD_WEBHOOK:
    raise ValueError("❌ DISCORD_WEBHOOK environment variable is not set! Make sure to add it as a GitHub Secret.")

# Files for persistent storage
HISTORY_FILE = "arc_history.json"  # JSON file to store all arc names
LAST_ARC_FILE = "last_arc.txt"       # Used to check if the new locked arc has already been announced

# === HELPER FUNCTIONS ===
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return json.load(f)
    else:
        # Initialize with empty lists if the file does not exist.
        return {"unlocked": [], "locked": []}

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=4)

def clean_title(raw_title):
    # Remove unwanted markdown characters from the raw title.
    return raw_title.replace("*", "").strip()

# === FETCH FEEDS ===
free_feed = feedparser.parse(FREE_FEED_URL)
paid_feed = feedparser.parse(PAID_FEED_URL)

# Extract arc titles based on first chapter indicator (" 001")
free_arcs_feed = [clean_title(entry.get("nameextend", "").split(" 001")[0])
                   for entry in free_feed.entries if " 001" in entry.get("nameextend", "")]
paid_arcs_feed = [clean_title(entry.get("nameextend", "").split(" 001")[0])
                   for entry in paid_feed.entries if " 001" in entry.get("nameextend", "")]

# === LOAD PERSISTENT HISTORY ===
history = load_history()

# === UPDATE HISTORY BASED ON FEEDS ===
# Any arc found in the free feed is considered unlocked.
for arc in free_arcs_feed:
    if arc not in history["unlocked"]:
        history["unlocked"].append(arc)
    if arc in history["locked"]:
        history["locked"].remove(arc)

# Any arc found in the paid feed that is not already unlocked or stored is added as locked.
for arc in paid_arcs_feed:
    if arc not in history["unlocked"] and arc not in history["locked"]:
        history["locked"].append(arc)

# Save the updated history
save_history(history)

# === DETERMINE NEW LOCKED ARC TO ANNOUNCE ===
# We assume the first element in the locked list is the next new arc.
new_locked_arc = history["locked"][0] if history["locked"] else None

# Read last announced locked arc to avoid duplicate announcements.
if os.path.exists(LAST_ARC_FILE):
    with open(LAST_ARC_FILE, "r") as f:
        last_announced = f.read().strip()
else:
    last_announced = ""

if new_locked_arc == last_announced:
    print(f"✅ No new arc detected. Last announced locked arc: {last_announced}")
    exit(0)

# Update the last announced arc file.
with open(LAST_ARC_FILE, "w") as f:
    f.write(new_locked_arc if new_locked_arc else "")

# === BUILD THE DISCORD MESSAGE ===
total_unlocked = len(history["unlocked"])
total_locked = len(history["locked"])
new_arc_number = total_unlocked + total_locked + 1  # New arc's number

# Build sections with plain titles; numbering will be applied by the script.
unlocked_section = "\n".join([f"**【Arc {i+1}】** {title}" for i, title in enumerate(history["unlocked"])])
locked_section_lines = [f"**【Arc {i+total_unlocked+1}】** {title}" for i, title in enumerate(history["locked"])]
if locked_section_lines:
    locked_section_lines[0] = f"☛{locked_section_lines[0]}"  # Mark the new locked arc with ☛
locked_section = "\n".join(locked_section_lines)

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
