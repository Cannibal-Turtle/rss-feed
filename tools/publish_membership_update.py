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
from message_renderer import load_template_settings, render_message, to_discord_api_payload
from message_settings import setting_str

try:
    from config_loader import (
        get_completion_state_url,
        get_discord_webhook_channel_id,
        get_discord_webhook_guild_id,
        get_novel_discord_map_url,
        get_roles_json_url,
    )
except Exception:
    def get_completion_state_url(default: str = "") -> str:
        return default

    def get_discord_webhook_channel_id(key: str, default: str = "") -> str:
        return default

    def get_discord_webhook_guild_id(default: str = "") -> str:
        return default

    def get_novel_discord_map_url(default: str = "") -> str:
        return default

    def get_roles_json_url(default: str = "") -> str:
        return default

TOKEN = os.environ["DISCORD_BOT_TOKEN"]

API_BASE = "https://discord.com/api/v10"

_TEMPLATE_SETTINGS = load_template_settings("membership_update")

NOVEL_DISCORD_MAP_URL = (
    os.environ.get("NOVEL_DISCORD_MAP_URL", "").strip()
    or get_novel_discord_map_url()
    or setting_str(_TEMPLATE_SETTINGS, "novel_discord_map_url")
)
# currently only supports single server role attachment
# Reads role IDs from discord-webhook's rich novel Discord TOML map.

# Always post here first.
# This is your server's news channel.
NEWS_CHANNEL_ID = int(
    os.environ.get("NEWS_CHANNEL_ID", "").strip()
    or get_discord_webhook_channel_id("announcements")
    or setting_str(_TEMPLATE_SETTINGS, "news_channel_id", "0")
    or 0
)

# Private/news server uses novel role + status role.
# Status role comes from discord-webhook roles.json:
# complete if paid_completion exists in state.json, otherwise ongoing.
# Non-private servers get public_global_mention.
MY_SERVER_GUILD_ID = (
    os.environ.get("MY_SERVER_GUILD_ID", "").strip()
    or get_discord_webhook_guild_id()
    or setting_str(_TEMPLATE_SETTINGS, "private_guild_id")
)

ROLES_JSON_URL = (
    os.environ.get("ROLES_JSON_URL", "").strip()
    or get_roles_json_url()
    or setting_str(_TEMPLATE_SETTINGS, "roles_json_url")
)

COMPLETION_STATE_URL = (
    os.environ.get("COMPLETION_STATE_URL", "").strip()
    or get_completion_state_url()
    or setting_str(_TEMPLATE_SETTINGS, "completion_state_url")
)

# Used only for non-private/public targets.
# Private/news server uses novel role + ongoing/complete status role instead.
PUBLIC_GLOBAL_MENTION = setting_str(
    _TEMPLATE_SETTINGS,
    "public_global_mention",
    "||@everyone||",
    env="PUBLIC_GLOBAL_MENTION",
)

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
    Fetches discord-webhook/config/novel_discord_map.toml
    and returns short_code -> raw novel role ID.
    """
    url = NOVEL_DISCORD_MAP_URL

    if not url:
        return {}

    if url in _NOVEL_ROLE_ID_MAP_CACHE:
        return _NOVEL_ROLE_ID_MAP_CACHE[url]

    r = requests.get(url, timeout=15)
    r.raise_for_status()

    data = tomllib.loads(r.text)

    if not isinstance(data, dict):
        raise RuntimeError(f"novel_discord_map_url did not return a TOML table: {url}")

    normalized = {}

    for short_code, value in data.items():
        code = str(short_code).strip().upper()

        if not code or not isinstance(value, dict):
            continue

        role_id = normalize_role_id(value.get("role_id", ""))

        if role_id:
            normalized[code] = role_id

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


_ROLES_JSON_CACHE = None
_COMPLETION_STATE_CACHE = None


def fetch_roles_json():
    global _ROLES_JSON_CACHE

    if _ROLES_JSON_CACHE is not None:
        return _ROLES_JSON_CACHE

    if not ROLES_JSON_URL:
        _ROLES_JSON_CACHE = {}
        return _ROLES_JSON_CACHE

    r = requests.get(ROLES_JSON_URL, timeout=15)
    r.raise_for_status()

    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"roles_json_url did not return a JSON object: {ROLES_JSON_URL}")

    _ROLES_JSON_CACHE = data
    return _ROLES_JSON_CACHE


def fetch_completion_state():
    global _COMPLETION_STATE_CACHE

    if _COMPLETION_STATE_CACHE is not None:
        return _COMPLETION_STATE_CACHE

    if not COMPLETION_STATE_URL:
        _COMPLETION_STATE_CACHE = {}
        return _COMPLETION_STATE_CACHE

    r = requests.get(COMPLETION_STATE_URL, timeout=15)
    r.raise_for_status()

    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"completion_state_url did not return a JSON object: {COMPLETION_STATE_URL}")

    _COMPLETION_STATE_CACHE = data
    return _COMPLETION_STATE_CACHE


def is_paid_completed_novel(novel_title: str) -> bool:
    state = fetch_completion_state()
    record = state.get(novel_title, {})

    if not isinstance(record, dict):
        return False

    return bool(record.get("paid_completion"))


def resolve_status_role_id(novel_title: str) -> str:
    roles = fetch_roles_json()
    role_key = "complete" if is_paid_completed_novel(novel_title) else "ongoing"
    return normalize_role_id(roles.get(role_key, ""))


def build_global_mention(*, novel_title, novel_role_mention, channel_id, guild_id):
    if int(channel_id) == NEWS_CHANNEL_ID or str(guild_id) == MY_SERVER_GUILD_ID:
        status_role_id = resolve_status_role_id(novel_title)

        mention_parts = [
            novel_role_mention,
            f"<@&{status_role_id}>" if status_role_id else "",
        ]
        mention = " | ".join(part for part in mention_parts if part)

        role_ids = role_ids_from_text(mention)

        return mention, {
            "parse": [],
            "roles": role_ids,
        }

    return PUBLIC_GLOBAL_MENTION, {
        "parse": ["everyone"],
    }


def build_membership_payload(*, host, novel_title, novel, banner_url, channel_id, guild_id, novel_role_mention):
    novel_url = novel.get("novel_url", "").strip()

    global_mention, allowed_mentions = build_global_mention(
        novel_title=novel_title,
        novel_role_mention=novel_role_mention,
        channel_id=channel_id,
        guild_id=guild_id,
    )

    ctx = {
        "host": host,
        "novel_title": novel_title,
        "novel_url": novel_url,
        "banner_url": banner_url,
        "global_mention": global_mention,
    }

    payload = to_discord_api_payload(render_message("membership_update", ctx))

    # Private/news server: novel role + ongoing/complete status role.
    # Public forum/thread: spoilered @everyone.
    payload["allowed_mentions"] = allowed_mentions

    return payload


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
