#!/usr/bin/env python3
import os
import sys
import re
import ast
import requests
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from novel_mappings import HOSTING_SITE_DATA

TOKEN = os.environ["DISCORD_BOT_TOKEN"]

API_BASE = "https://discord.com/api/v10"

# Always post here first.
# This is your server's news channel.
NEWS_CHANNEL_ID = 1330049962129489930

# Your server guild ID.
# This is from your role URLs in novel_mappings.py.
MY_SERVER_GUILD_ID = "1329384099609051136"

# Membership role in your server.
MEMBERSHIP_ROLE_ID = "1329502951764525187"

# #c9d3ff
ACCENT_COLOR = 0xC9D3FF

MAPPINGS_FILE = ROOT / "novel_mappings.py"
PUBLISH_SINGLE_NOVEL_FILE = ROOT / "tools" / "publish_single_novel.py"


def discord_headers():
    return {
        "Authorization": f"Bot {TOKEN}",
        "Content-Type": "application/json",
    }


def load_novel_meta_from_publish_single():
    """
    Do NOT import tools.publish_single_novel directly.

    That file has top-level bot-running code, so importing it can accidentally
    start/exit the script. This safely reads only the NOVEL_META assignment.
    """
    source = PUBLISH_SINGLE_NOVEL_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "NOVEL_META":
                    return ast.literal_eval(node.value)

    raise RuntimeError("Could not find NOVEL_META in tools/publish_single_novel.py")


def find_novel_by_short_code(short_code: str):
    short_code = short_code.upper().strip()

    for host, hostdata in HOSTING_SITE_DATA.items():
        for novel_title, novel in hostdata.get("novels", {}).items():
            if novel.get("short_code", "").upper() == short_code:
                return host, novel_title, novel

    return None, None, None


def fetch_channel(channel_id: int):
    """
    Used to detect which server the channel/thread belongs to.
    """
    try:
        r = requests.get(
            f"{API_BASE}/channels/{channel_id}",
            headers=discord_headers(),
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Warning: could not fetch channel {channel_id}: {e}")
        return {}


def role_ids_from_text(text: str):
    return re.findall(r"<@&(\d+)>", text or "")


def build_global_mention(*, novel, channel_id, guild_id):
    """
    Your server/news channel:
      novel role | membership role

    Mistmint Haven / other server:
      ||@everyone||
    """
    novel_role = novel.get("discord_role_id", "").strip()

    if int(channel_id) == NEWS_CHANNEL_ID or str(guild_id) == MY_SERVER_GUILD_ID:
        mention = f"{novel_role} | <@&{MEMBERSHIP_ROLE_ID}>"

        role_ids = role_ids_from_text(mention)

        return mention, {
            "parse": [],
            "roles": role_ids,
        }

    return "||@everyone||", {
        "parse": ["everyone"],
    }


def build_membership_payload(*, host, novel_title, novel, banner_url, channel_id, guild_id):
    novel_url = novel.get("novel_url", "").strip()

    global_mention, allowed_mentions = build_global_mention(
        novel=novel,
        channel_id=channel_id,
        guild_id=guild_id,
    )

    return {
        "flags": 32768,
        "allowed_mentions": allowed_mentions,
        "components": [
            {
                "type": 10,
                "content": global_mention,
            },
            {
                "type": 17,
                "accent_color": ACCENT_COLOR,
                "components": [
                    {
                        "type": 10,
                        "content": "## <:mistmint_ticket:1517453566632001597> Membership Update <:approvedpurple:1517433828535173231>",
                    },
                    {
                        "type": 14,
                        "spacing": 1,
                        "divider": False,
                    },
                    {
                        "type": 12,
                        "items": [
                            {
                                "media": {
                                    "url": banner_url,
                                },
                                "description": "Membership banner",
                                "spoiler": False,
                            }
                        ],
                    },
                    {
                        "type": 14,
                        "spacing": 1,
                        "divider": False,
                    },
                    {
                        "type": 10,
                        "content": (
                            f"<a:blackcatbracket_1:1517457481532440576>"
                            f"**{novel_title}**"
                            f"<a:blackcatbracket_2:1517457479380766751> "
                            f"is now available for {host} Membership!"
                        ),
                    },
                    {
                        "type": 10,
                        "content": (
                            "Members can now choose this novel as their monthly pick and use tickets "
                            "to unlock its premium chapters.\n"
                            "Happy reading <a:purple_book:1517433229018136617>"
                        ),
                    },
                    {
                        "type": 14,
                        "spacing": 1,
                        "divider": True,
                    },
                    {
                        "type": 9,
                        "components": [
                            {
                                "type": 10,
                                "content": "*Become a member?*",
                            }
                        ],
                        "accessory": {
                            "type": 2,
                            "style": 5,
                            "label": "SUBSCRIBE",
                            "emoji": {
                                "id": "1517425652838432840",
                                "name": "purple_crown",
                                "animated": True,
                            },
                            "url": novel_url,
                        },
                    },
                ],
                "spoiler": False,
            },
        ],
    }


def post_message(channel_id: int, payload: dict):
    r = requests.post(
        f"{API_BASE}/channels/{channel_id}/messages",
        headers=discord_headers(),
        json=payload,
        timeout=20,
    )

    if r.status_code >= 400:
        print("Discord error response:")
        print(r.text)

    r.raise_for_status()
    return r.json()


def ensure_membership_helpers_exist(text: str):
    changed = False

    if "MEMBERSHIP_NOVEL_SHORT_CODES" not in text:
        text = text.rstrip() + '''

# ---------------- Membership Helpers ----------------

MEMBERSHIP_NOVEL_SHORT_CODES = [
]

def get_membership_novel_short_codes():
    """Returns short codes for novels currently available for membership."""
    return [code.upper() for code in MEMBERSHIP_NOVEL_SHORT_CODES]

def get_membership_novels():
    """
    Returns membership novels grouped by host.

    Example:
    {
        "Mistmint Haven": {
            "Novel Title": {...novel details...}
        }
    }
    """
    membership_codes = set(get_membership_novel_short_codes())
    out = {}

    for host, hostdata in HOSTING_SITE_DATA.items():
        for title, novel in hostdata.get("novels", {}).items():
            if novel.get("short_code", "").upper() in membership_codes:
                out.setdefault(host, {})[title] = novel

    return out
'''
        changed = True

    return text, changed


def mark_novel_as_membership(short_code: str):
    short_code = short_code.upper().strip()

    text = MAPPINGS_FILE.read_text(encoding="utf-8")
    text, changed = ensure_membership_helpers_exist(text)

    pattern = re.compile(
        r"MEMBERSHIP_NOVEL_SHORT_CODES\s*=\s*\[(.*?)\]",
        re.DOTALL,
    )

    match = pattern.search(text)
    if not match:
        raise RuntimeError("Could not find MEMBERSHIP_NOVEL_SHORT_CODES in novel_mappings.py")

    body = match.group(1)
    existing_codes = re.findall(r'["\']([^"\']+)["\']', body)
    existing_codes = [code.upper() for code in existing_codes]

    if short_code not in existing_codes:
        existing_codes.append(short_code)
        changed = True

    new_block = "MEMBERSHIP_NOVEL_SHORT_CODES = [\n"
    for code in existing_codes:
        new_block += f'    "{code}",\n'
    new_block += "]"

    text = text[:match.start()] + new_block + text[match.end():]

    if changed:
        MAPPINGS_FILE.write_text(text.rstrip() + "\n", encoding="utf-8")
        print(f"Marked {short_code} as membership in novel_mappings.py")
    else:
        print(f"{short_code} is already marked as membership in novel_mappings.py")


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/publish_membership_update.py <short_code> <banner_url>")
        sys.exit(1)

    short_code = sys.argv[1].upper().strip()

    if len(sys.argv) < 3 or not sys.argv[2].strip():
        print("Error: banner_url is required.")
        print("Usage: python tools/publish_membership_update.py <short_code> <banner_url>")
        sys.exit(1)
    
    banner_url = sys.argv[2].strip()

    host, novel_title, novel = find_novel_by_short_code(short_code)

    if not novel:
        print(f"Unknown short_code: {short_code}")
        sys.exit(1)

    novel_meta = load_novel_meta_from_publish_single()

    targets = [NEWS_CHANNEL_ID]

    thread_id = novel_meta.get(short_code, {}).get("forum_post_id")
    if thread_id:
        thread_id = int(thread_id)
        if thread_id not in targets:
            targets.append(thread_id)

    print(f"Publishing membership update for: {novel_title}")
    print(f"Targets: {targets}")

    for channel_id in targets:
        channel_data = fetch_channel(channel_id)
        guild_id = channel_data.get("guild_id")

        payload = build_membership_payload(
            host=host,
            novel_title=novel_title,
            novel=novel,
            banner_url=banner_url,
            channel_id=channel_id,
            guild_id=guild_id,
        )

        msg = post_message(channel_id, payload)
        print(f"Posted membership update to {channel_id}: message {msg.get('id')}")

    mark_novel_as_membership(short_code)


if __name__ == "__main__":
    main()
