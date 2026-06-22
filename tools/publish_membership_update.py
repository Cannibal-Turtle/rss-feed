#!/usr/bin/env python3
import os
import sys
import re
import requests
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from novel_mappings import HOSTING_SITE_DATA

TOKEN = os.environ["DISCORD_BOT_TOKEN"]

API_BASE = "https://discord.com/api/v10"

NOVEL_ROLE_ID_MAP_URL = "https://raw.githubusercontent.com/Cannibal-Turtle/discord-webhook/main/novel_role_id_map.json"
# currently only supports single server role attachment

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

NOVELS_DIR = ROOT / "mappings" / "novels"


def discord_headers():
    return {
        "Authorization": f"Bot {TOKEN}",
        "Content-Type": "application/json",
    }


_NOVEL_ROLE_ID_MAP_CACHE = {}

def normalize_role_id(value):
    m = re.search(r"\d{5,}", str(value or ""))
    return m.group(0) if m else ""

def fetch_novel_role_id_map():
    """
    Fetches short_code -> novel role ID from NOVEL_ROLE_ID_MAP_URL.
    Values may be raw IDs or <@&...>; this normalizes to raw IDs.
    """
    url = NOVEL_ROLE_ID_MAP_URL

    if not url:
        return {}

    if url in _NOVEL_ROLE_ID_MAP_CACHE:
        return _NOVEL_ROLE_ID_MAP_CACHE[url]

    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()

    if not isinstance(data, dict):
        raise RuntimeError(f"novel_role_id_map_url did not return a JSON object: {url}")

    normalized = {
        str(k).upper(): normalize_role_id(v)
        for k, v in data.items()
        if normalize_role_id(v)
    }

    _NOVEL_ROLE_ID_MAP_CACHE[url] = normalized
    return normalized

def resolve_novel_role_mention(short_code):
    role_map = fetch_novel_role_id_map()
    role_id = role_map.get(short_code.upper())
    return f"<@&{role_id}>" if role_id else ""


_THREAD_ID_MAP_CACHE = {}

def fetch_thread_id_map(hostdata):
    """
    Fetches the host's thread_id_map_url from novel_mappings.py.

    Expected JSON format:
    {
      "TVITPA": "1444214902322368675",
      "TDLBKGC": "1438462596381413417",
      "BOE": "N/A"
    }
    """
    url = (hostdata.get("thread_id_map_url") or "").strip()

    if not url:
        return {}

    if url in _THREAD_ID_MAP_CACHE:
        return _THREAD_ID_MAP_CACHE[url]

    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()

    if not isinstance(data, dict):
        raise RuntimeError(f"thread_id_map_url did not return a JSON object: {url}")

    normalized = {
        str(k).upper(): str(v).strip()
        for k, v in data.items()
        if str(v).strip()
    }

    _THREAD_ID_MAP_CACHE[url] = normalized
    return normalized


def resolve_forum_thread_id(hostdata, short_code):
    """
    Gets the forum/thread ID for this novel from the host's thread_id_map_url.
    """
    thread_map = fetch_thread_id_map(hostdata)
    return thread_map.get(short_code.upper())


def find_novel_by_short_code(short_code: str):
    short_code = short_code.upper().strip()

    for host, hostdata in HOSTING_SITE_DATA.items():
        for novel_title, novel in hostdata.get("novels", {}).items():
            if novel.get("short_code", "").upper() == short_code:
                return host, hostdata, novel_title, novel

    return None, None, None, None


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


def build_global_mention(*, novel_role_mention, channel_id, guild_id):
    if int(channel_id) == NEWS_CHANNEL_ID or str(guild_id) == MY_SERVER_GUILD_ID:
        mention_parts = [
            novel_role_mention,
            f"<@&{MEMBERSHIP_ROLE_ID}>",
        ]
        mention = " | ".join(part for part in mention_parts if part)

        role_ids = role_ids_from_text(mention)

        return mention, {
            "parse": [],
            "roles": role_ids,
        }

    return "||@everyone||", {
        "parse": ["everyone"],
    }


def build_membership_payload(*, host, novel_title, novel, banner_url, channel_id, guild_id, novel_role_mention):
    novel_url = novel.get("novel_url", "").strip()

    global_mention, allowed_mentions = build_global_mention(
        novel_role_mention=novel_role_mention,
        channel_id=channel_id,
        guild_id=guild_id,
    )

    return {
        "flags": 32768,
        "allowed_mentions": allowed_mentions,
        "components": [
            {
                "type": 17,
                "accent_color": ACCENT_COLOR,
                "components": [
                    {
                        "type": 10,
                        "content": global_mention,
                    },
                    {
                        "type": 10,
                        "content": "## <:mistmint_ticket:1517453566632001597> Membership Exclusive <:approvedpurple:1517512468446842990>",
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
                            f"is now available for ***{host} Membership!***\n\n"
                        ),
                    },
                    {
                        "type": 10,
                        "content": (
                            "Members can now choose this novel as their monthly pick and use tickets "
                            "to unlock its premium chapters.\n\n"
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


def load_toml_file(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def find_novel_toml_by_short_code(short_code: str):
    short_code = (short_code or "").strip().upper()

    for path in sorted(NOVELS_DIR.glob("*.toml")):
        data = load_toml_file(path)

        if (data.get("short_code", "") or "").strip().upper() == short_code:
            return path, data

    return None, None


def mark_short_code_as_membership(short_code: str):
    path, data = find_novel_toml_by_short_code(short_code)

    if not path:
        raise RuntimeError(f"Could not find novel TOML for short_code: {short_code}")

    if data.get("is_membership") is True:
        print(f"{short_code} is already marked as membership in {path}")
        return

    text = path.read_text(encoding="utf-8")

    # Main case:
    # is_membership = false
    new_text, count = re.subn(
        r"(?m)^(\s*is_membership\s*=\s*)false(\s*(?:#.*)?)$",
        r"\1true\2",
        text,
        count=1,
    )

    if count == 0:
        # If is_membership is missing, add it after is_nsfw if possible.
        new_text, count = re.subn(
            r"(?m)^(\s*is_nsfw\s*=\s*(?:true|false)\s*(?:#.*)?\n)",
            r"\1is_membership = true\n",
            text,
            count=1,
        )

    if count == 0:
        # Last fallback: append it at the end.
        new_text = text.rstrip() + "\n\nis_membership = true\n"

    path.write_text(new_text, encoding="utf-8")

    print(f"Marked {short_code} as membership in {path}")


def main():
    if len(sys.argv) < 3:
        print("Usage: python tools/publish_membership_update.py <short_code> <banner_url>")
        sys.exit(1)

    short_code = sys.argv[1].upper().strip()

    if not sys.argv[2].strip():
        print("Error: banner_url is required.")
        print("Usage: python tools/publish_membership_update.py <short_code> <banner_url>")
        sys.exit(1)

    banner_url = sys.argv[2].strip()

    host, hostdata, novel_title, novel = find_novel_by_short_code(short_code)

    if not novel:
        print(f"Unknown short_code: {short_code}")
        sys.exit(1)

    novel_role_mention = resolve_novel_role_mention(short_code)

    targets = [NEWS_CHANNEL_ID]
    
    thread_id = resolve_forum_thread_id(hostdata, short_code)
    
    if thread_id is None:
        print(f"ERROR: {short_code} is missing from {host}'s thread_id_map_url.")
        print('Add it to that host repo thread_id_map.json, or use "N/A" if it has no thread.')
        sys.exit(1)
    
    thread_id = str(thread_id).strip()
    
    if not thread_id:
        print(f"ERROR: {short_code} has an empty thread ID in {host}'s thread_id_map_url.")
        print('Use "N/A" if this novel should only post to your private/news server.')
        sys.exit(1)
    
    if thread_id.upper() == "N/A":
        print(f"{short_code} has no forum thread. Posting only to private/news server.")
    
    else:
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
            novel_role_mention=novel_role_mention,
        )

        msg = post_message(channel_id, payload)
        print(f"Posted membership update to {channel_id}: message {msg.get('id')}")

    mark_short_code_as_membership(short_code)


if __name__ == "__main__":
    main()
