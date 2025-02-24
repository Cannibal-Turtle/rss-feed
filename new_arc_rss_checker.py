import requests
import feedparser
import os

# RSS Feeds
FREE_FEED_URL = "https://cannibal-turtle.github.io/rss-feed/free_chapters_feed.xml"
PAID_FEED_URL = "https://cannibal-turtle.github.io/rss-feed/paid_chapters_feed.xml"

# Get Discord Webhook from Environment Variable
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
if not DISCORD_WEBHOOK:
    raise ValueError("❌ DISCORD_WEBHOOK environment variable is not set! Make sure to add it as a GitHub Secret.")

# File to store last detected arc
LAST_ARC_FILE = "last_arc.txt"

# Fetch Feeds
free_feed = feedparser.parse(FREE_FEED_URL)
paid_feed = feedparser.parse(PAID_FEED_URL)

# Extract unlocked arcs (001 chapters)
free_arcs = [entry.get("nameextend", "").split(" 001")[0] for entry in free_feed.entries if " 001" in entry.get("nameextend", "")]
paid_arcs = [entry.get("nameextend", "").split(" 001")[0] for entry in paid_feed.entries if " 001" in entry.get("nameextend", "")]

# Get the last known unlocked arc (from the free feed)
if free_arcs:
    last_unlocked_arc = free_arcs[-1]  # Most recent unlocked arc
else:
    last_unlocked_arc = None

# Find the position of the last unlocked arc in the paid feed
if last_unlocked_arc and last_unlocked_arc in paid_arcs:
    unlocked_index = paid_arcs.index(last_unlocked_arc)
    locked_arcs = paid_arcs[unlocked_index + 1:]  # Everything after the last unlocked arc
else:
    locked_arcs = paid_arcs  # If no free arcs exist, all paid arcs are locked

# Find the next locked arc (for the "☛" emoji)
next_locked_arc = locked_arcs[0] if locked_arcs else None

# Read the last stored arc (to prevent duplicate announcements)
if os.path.exists(LAST_ARC_FILE):
    with open(LAST_ARC_FILE, "r") as f:
        last_stored_arc = f.read().strip()
else:
    last_stored_arc = ""

# If there's no new arc, exit early to avoid unnecessary GitHub Actions runs
if next_locked_arc == last_stored_arc:
    print(f"✅ No new arc detected. Last stored arc: {last_stored_arc}")
    exit(0)  # Stop script execution

# Update the stored arc file
with open(LAST_ARC_FILE, "w") as f:
    f.write(next_locked_arc)

# Update the "World X is Live for" section (Latest arc number = Total free arcs + 1)
latest_arc_number = len(free_arcs) + 1
latest_arc_title = next_locked_arc if next_locked_arc else "TBA"

# Format the Unlocked and Locked sections properly
unlocked_section = "\n".join([f"**【Arc {i+1}】** {arc}" for i, arc in enumerate(free_arcs)])
locked_section = "\n".join([f"**【Arc {i+len(free_arcs)+1}】** {arc}" for i, arc in enumerate(locked_arcs[:-1])])
locked_section += f"\n☛**【Arc {latest_arc_number}】 {latest_arc_title}**"  # Place "☛" on latest locked arc

# Construct Discord message
message = (
    f"<@&1329391480435114005> <@&1329502951764525187>\n"
    "## :loudspeaker: NEW ARC ALERT˚ · .˚ ༘:butterfly:⋆｡˚\n"
    f"***《World {latest_arc_number}》is Live for***\n"
    "### [Quick Transmigration: The Villain Is Too Pampered and Alluring](https://dragonholic.com/novel/quick-transmigration-the-villain-is-too-pampered-and-alluring/) :dracthyrhehe:\n\n"
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

# Send message to Discord
data = {"content": message}
response = requests.post(DISCORD_WEBHOOK, json=data)

if response.status_code == 204:
    print(f"✅ Sent notification: {last_unlocked_arc} unlocked, {latest_arc_title} locked.")
else:
    print(f"❌ Failed to send notification. Status Code: {response.status_code}")
