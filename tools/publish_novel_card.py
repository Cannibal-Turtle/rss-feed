#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import os
import json
import re
import requests
from datetime import datetime, timezone
from dateutil import parser as dateparser

import discord

from novel_mappings import HOSTING_SITE_DATA, get_novelupdates_url
from host_utils import get_host_utils
from message_renderer import load_template_settings, render_message, to_discord_py_kwargs
from message_settings import setting_str

try:
    from config_loader import (
        get_host_discord_target,
        get_integration_channel_id,
        get_integration_guild_id,
        get_integration_raw_url,
        get_primary_discord_integration,
    )
except Exception:
    def get_host_discord_target(host_key: str):
        return {}

    def get_integration_channel_id(name: str, key: str, default: str = "") -> str:
        return default

    def get_integration_raw_url(name: str, key: str, default_path: str = "", default: str = "") -> str:
        return default

    def get_integration_guild_id(name: str, default: str = "") -> str:
        return default

    def get_primary_discord_integration(default: str = "discord_webhook") -> str:
        return default

DISCORD_INTEGRATION = (
    os.getenv("PRIMARY_DISCORD_INTEGRATION", "").strip()
    or os.getenv("DISCORD_INTEGRATION", "").strip()
    or get_primary_discord_integration("discord_webhook")
    or "discord_webhook"
)

# Optional override for manual/testing runs.
# If unset, the script chooses the host-specific Discord target from
# config/integrations.json -> host_discord_targets.<host>.
THREAD_INTEGRATION_OVERRIDE = os.getenv("THREAD_INTEGRATION", "").strip()
THREAD_MAP_URL_OVERRIDE = os.getenv("THREAD_ID_MAP_URL", "").strip()
THREAD_MAP_KEY_OVERRIDE = os.getenv("THREAD_MAP_KEY", "thread_id_map").strip() or "thread_id_map"
THREAD_MAP_DEFAULT_PATH_OVERRIDE = (
    os.getenv("THREAD_MAP_DEFAULT_PATH", "config/thread_id_map.json").strip()
    or "config/thread_id_map.json"
)

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

TOKEN = os.environ["DISCORD_BOT_TOKEN"]
STATE_FILE = "novel_status_targets.json"

_TEMPLATE_SETTINGS = load_template_settings("publish_novel_card")

ARCHIVE_CHANNEL_ID = int(
    os.environ.get("ARCHIVE_CHANNEL_ID", "").strip()
    or get_integration_channel_id(DISCORD_INTEGRATION, "novel_cards_archive")
    or setting_str(_TEMPLATE_SETTINGS, "archive_channel_id", "1463476725253144751")
)

# Optional manual override for the primary/private Discord novel role map.
# Host-specific posts use their own integration's novel_discord_map unless this is set.
NOVEL_DISCORD_MAP_URL_OVERRIDE = os.environ.get("NOVEL_DISCORD_MAP_URL", "").strip()

# Optional manual override for the second/extra post target's Discord integration.
EXTRA_DISCORD_INTEGRATION_OVERRIDE = os.getenv("EXTRA_DISCORD_INTEGRATION", "").strip()

# ---------------- utils ----------------

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def fetch_api(url, cookie_env):
    headers = {}
    cookie = os.environ.get(cookie_env)
    if cookie:
        headers["Cookie"] = cookie
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()

_THREAD_ID_MAP_CACHE = {}

_NOVEL_DISCORD_MAP_URL_CACHE = {}

def normalize_role_id(value):
    m = re.search(r"\d{5,}", str(value or ""))
    return m.group(0) if m else ""


def host_config_key(host: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(host or "").strip().casefold()).strip("_")


def route_for_single_novel(target_cfg: dict) -> dict:
    """
    Return the host Discord route used by the novel-card publisher.

    For novel cards, the normal host route is a shared archive channel
    (config/server.json -> novel_cards_archive), not a per-novel thread.

    Preferred route keys, in order:
      - publish_novel_card
      - novel_card
      - default
    """
    routes = target_cfg.get("routes", {})

    if isinstance(routes, dict):
        for key in ("publish_novel_card", "novel_card", "default"):
            route = routes.get(key)
            if isinstance(route, dict):
                return route

    route = target_cfg.get("route", {})
    if isinstance(route, dict) and route:
        return route

    return {
        "type": "channel",
        "channel_key": "novel_cards_archive",
        "server_key": "server_json",
        "default_path": "config/server.json",
    }


def resolve_single_novel_thread_route(host: str):
    """
    Resolve which host-specific Discord integration/thread map should be used
    for this novel card's optional Forum Post link.

    The primary/private Discord archive post is still controlled by
    DISCORD_INTEGRATION. This only controls the host-specific forum/thread link.
    """
    if THREAD_INTEGRATION_OVERRIDE or THREAD_MAP_URL_OVERRIDE:
        return THREAD_INTEGRATION_OVERRIDE or "thread_id_map_url_override", {
            "type": "thread_map",
            "map_key": THREAD_MAP_KEY_OVERRIDE,
            "default_path": THREAD_MAP_DEFAULT_PATH_OVERRIDE,
        }

    host_key = host_config_key(host)
    target_cfg = get_host_discord_target(host_key)

    if not target_cfg:
        return "", {}

    integration = str(target_cfg.get("integration") or "").strip()
    if not integration:
        return "", {}

    return integration, route_for_single_novel(target_cfg)


def novel_discord_map_url_for_integration(integration: str) -> str:
    integration = str(integration or "").strip()

    if not integration:
        return ""

    if integration == DISCORD_INTEGRATION and NOVEL_DISCORD_MAP_URL_OVERRIDE:
        return NOVEL_DISCORD_MAP_URL_OVERRIDE

    return get_integration_raw_url(
        integration,
        "novel_discord_map",
        "config/novel_discord_map.toml",
    )


def fetch_novel_role_id_map(integration: str):
    """
    Fetches one Discord integration's novel_discord_map.toml and returns
    short_code -> raw novel role ID.

    Role IDs are server-specific, so every post target must use the map from
    the Discord integration that owns that target.
    """
    url = novel_discord_map_url_for_integration(integration)

    if not url:
        return {}

    if url in _NOVEL_DISCORD_MAP_URL_CACHE:
        return _NOVEL_DISCORD_MAP_URL_CACHE[url]

    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = tomllib.loads(r.text)
    except Exception as exc:
        print(f"Warning: could not load novel_discord_map for {integration} from {url}: {exc}")
        data = {}

    if not isinstance(data, dict):
        print(f"Warning: novel_discord_map did not return a TOML table for {integration}: {url}")
        data = {}

    normalized = {}

    for short_code, value in data.items():
        code = str(short_code).strip().upper()

        if not code or not isinstance(value, dict):
            continue

        role_id = normalize_role_id(value.get("role_id", ""))

        if role_id:
            normalized[code] = role_id

    _NOVEL_DISCORD_MAP_URL_CACHE[url] = normalized
    return normalized


def resolve_novel_role_mention(short_code, integration: str):
    role_map = fetch_novel_role_id_map(integration)
    role_id = role_map.get(short_code.upper())
    return f"<@&{role_id}>" if role_id else ""
    
def host_discord_integration_for_host(host: str) -> str:
    if EXTRA_DISCORD_INTEGRATION_OVERRIDE:
        return EXTRA_DISCORD_INTEGRATION_OVERRIDE

    target_cfg = get_host_discord_target(host_config_key(host))
    return str(target_cfg.get("integration") or "").strip()


def host_novel_cards_archive_target(host: str) -> dict | None:
    """
    Resolve the host/server archive channel for novel cards.

    Example: Mistmint Haven -> host_discord_targets.mistmint_haven.integration
    -> that Discord repo's config/server.json -> novel_cards_archive.
    """
    target_cfg = get_host_discord_target(host_config_key(host))
    integration = str(target_cfg.get("integration") or "").strip()

    if EXTRA_DISCORD_INTEGRATION_OVERRIDE:
        integration = EXTRA_DISCORD_INTEGRATION_OVERRIDE

    if not integration:
        print(f"No host-specific Discord integration configured for {host_config_key(host)}; no host archive card will be posted.")
        return None

    route = route_for_single_novel(target_cfg)
    route_type = str(route.get("type") or "channel").strip().lower()

    if route_type == "none":
        print(f"Host-specific novel-card archive route is disabled for {host_config_key(host)}.")
        return None

    if route_type != "channel":
        print(
            f"Host-specific novel-card route for {host_config_key(host)} is {route_type!r}, "
            "not a shared archive channel; no host archive card will be posted."
        )
        return None

    channel_key = str(route.get("channel_key") or "novel_cards_archive").strip()
    server_key = str(route.get("server_key") or "server_json").strip()
    default_path = str(route.get("default_path") or "config/server.json").strip()

    channel_id = get_integration_channel_id(
        integration,
        channel_key,
        server_key=server_key,
        default_path=default_path,
    )

    if not channel_id:
        print(
            f"No {channel_key} found in {integration} {default_path}; "
            f"no host archive card will be posted for {host_config_key(host)}."
        )
        return None

    try:
        channel_id_int = int(channel_id)
    except ValueError:
        print(f"Invalid {channel_key} for {integration}: {channel_id!r}")
        return None

    return {
        "channel_id": channel_id_int,
        "preferred_integration": integration,
    }


def channel_guild_id(channel) -> str:
    if getattr(channel, "guild", None):
        return str(channel.guild.id)

    guild_id = getattr(channel, "guild_id", None)
    return str(guild_id or "").strip()


def integration_for_channel(channel, preferred_integration: str = "") -> str:
    """
    Pick the Discord integration that owns this channel/thread.

    This prevents a role ID from one server being shown in another server's
    embed. Keep guild_id in each Discord repo's config/server.json so this
    matching can be exact when multiple Discord targets exist.
    """
    channel_guild = channel_guild_id(channel)
    preferred_integration = str(preferred_integration or "").strip()

    candidates = []

    for candidate in (preferred_integration, DISCORD_INTEGRATION):
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    if channel_guild:
        for candidate in candidates:
            configured_guild = str(get_integration_guild_id(candidate) or "").strip()
            if configured_guild and configured_guild == channel_guild:
                return candidate

    # If we cannot compare guild IDs, trust the explicit/preferred integration.
    # If there is no preferred integration, use the primary/private integration.
    return preferred_integration or DISCORD_INTEGRATION


def fetch_thread_id_map(integration: str, route: dict):
    """
    Fetches a host-specific Discord thread ID map from config/integrations.json.

    Expected JSON format:
    {
      "TVITPA": "1444214902322368675",
      "TDLBKGC": "1438462596381413417"
    }
    """
    if THREAD_MAP_URL_OVERRIDE:
        url = THREAD_MAP_URL_OVERRIDE
    else:
        map_key = str(route.get("map_key") or "thread_id_map").strip()
        default_path = str(route.get("default_path") or "config/thread_id_map.json").strip()
        url = get_integration_raw_url(integration, map_key, default_path)

    if not url:
        return {}

    if url in _THREAD_ID_MAP_CACHE:
        return _THREAD_ID_MAP_CACHE[url]

    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()

    if not isinstance(data, dict):
        raise RuntimeError(f"thread ID map URL did not return a JSON object: {url}")

    normalized = {
        str(k).upper(): str(v).strip()
        for k, v in data.items()
        if str(v).strip()
    }

    _THREAD_ID_MAP_CACHE[url] = normalized
    return normalized

def resolve_forum_post_id(host, short_code):
    """
    Gets the host-specific forum/thread ID for this novel.

    If this host has no configured host-specific Discord target, or its route is
    channel-only, the private archive card is still posted; the Forum Post link
    is simply omitted.
    """
    integration, route = resolve_single_novel_thread_route(host)

    if not integration:
        print(f"No host-specific Discord target configured for {host_config_key(host)}; no Forum Post link will be added.")
        return None

    route_type = str(route.get("type") or "thread_map").strip().lower()

    if route_type == "none":
        print(f"Host-specific Discord route for {host_config_key(host)}/publish_novel_card is disabled.")
        return None

    if route_type == "channel":
        print(f"Host-specific Discord route for {host_config_key(host)}/publish_novel_card is channel-only; no per-novel Forum Post link will be added.")
        return None

    if route_type != "thread_map":
        print(f"Unknown host Discord route type {route_type!r} for {host_config_key(host)}/publish_novel_card; no Forum Post link will be added.")
        return None

    thread_map = fetch_thread_id_map(integration, route)
    return thread_map.get(short_code.upper())

def normalize_api(api):
    if not api:
        return []
    if isinstance(api, dict):
        return api.get("data", [])
    if isinstance(api, list):
        return api
    return []

def flatten_chapters(api):
    volumes = normalize_api(api)
    out = []

    for vol in volumes:
        if not isinstance(vol, dict):
            continue
        for ch in vol.get("chapters", []):
            if not ch.get("isHidden"):
                out.append(ch)

    # order is safer than createdAt when present
    out.sort(key=lambda c: (
        c.get("order", 0),
        c.get("createdAt", "")
    ))
    return out

def human_delta(dt):
    if not dt:
        return "Unknown"
    now = datetime.now(timezone.utc)
    delta = dt - now
    if delta.total_seconds() <= 0:
        return "Available now"
    d, s = delta.days, delta.seconds
    h = s // 3600
    m = (s % 3600) // 60
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m and not d:
        parts.append(f"{m}m")
    return " ".join(parts)

def text_match(needle: str, haystack: str) -> bool:
    if not needle or not haystack:
        return False
    return re.search(
        rf"\b{re.escape(needle)}\b",
        haystack,
        flags=re.IGNORECASE
    ) is not None

def compute_status(chapters, last_chapter_text):
    completed = False
    next_free_dt = None
    last_free_dt = None

    last_chapter_text = (last_chapter_text or "").strip()

    # ── Case 1: Chapter N
    m = re.match(
        r"chapter\s+(\d+(\.\d+)?)(?:\b|[^0-9])",
        last_chapter_text,
        re.IGNORECASE
    )
    if m:
        target_num = m.group(1)
        for c in chapters:
            if str(c.get("chapterNumber", "")).strip() == target_num:
                completed = True
                break

    # ── Case 2: Extras / side stories / named chapters
    else:
        needle = last_chapter_text
        if needle:
            for c in chapters:
                if (
                    text_match(needle, c.get("chapterNumber") or "") or
                    text_match(needle, c.get("title") or "")
                ):
                    completed = True
                    break

    # ── Next free chapter logic
    now = datetime.now(timezone.utc)

    for c in chapters:
        free_at = c.get("freeAt")
        if not free_at:
            continue

        try:
            dt = dateparser.parse(free_at)
        except Exception:
            continue

        if dt > now:
            if not next_free_dt or dt < next_free_dt:
                next_free_dt = dt
        else:
            if not last_free_dt or dt > last_free_dt:
                last_free_dt = dt

    return completed, next_free_dt, last_free_dt

def build_status_text(*, completed, next_free_dt, last_free_dt):
    status_lines = []

    status_lines.append("*Completed*" if completed else "*Ongoing*")

    if next_free_dt:
        unix_ts = int(next_free_dt.timestamp())
        status_lines.append(f"Next free chapter live **<t:{unix_ts}:R>**")

    elif last_free_dt:
        unix_ts = int(last_free_dt.timestamp())
        abs_time = last_free_dt.strftime("%A, %d %B %Y")
        status_lines.append(
            f"Last free chapter live **<t:{unix_ts}:R>** ({abs_time})"
        )

    else:
        status_lines.append("_No free chapter timing available_")

    return "\n".join(status_lines)

def build_links_text(*, novel, host, forum_post_url):
    links = []

    # Host link
    host_url = novel.get("novel_url")
    if host_url:
        links.append(f"[{host}]({host_url})")

    # NovelUpdates link
    nu = get_novelupdates_url(novel)
    if nu:
        links.append(f"[NU]({nu})")

    # Forum post
    if forum_post_url:
        links.append(f"[Forum Post]({forum_post_url})")

    return " • ".join(links)

def build_message_payload_for_channel(
    *,
    title,
    novel,
    host,
    completed,
    next_free_dt,
    last_free_dt,
    target_channel_id,
    target_integration,
    forum_post_url,
    novel_role_mention,
):
    """
    Builds the same novel-card message as before, but with the visible text/layout
    moved to message_templates/publish_novel_card.toml.
    """
    status_text = build_status_text(
        completed=completed,
        next_free_dt=next_free_dt,
        last_free_dt=last_free_dt,
    )

    links_text = build_links_text(
        novel=novel,
        host=host,
        forum_post_url=forum_post_url,
    )

    # Role IDs are server-specific. Only show the Role field if this target
    # integration's own novel_discord_map.toml had a role for this novel.
    show_role = bool(target_integration and novel_role_mention)

    ctx = {
        "title": title,
        "host": host,
        "discord_color": novel.get("discord_color", "#ffffff"),
        "featured_image": novel.get("featured_image") or "",
        "novel_role_mention": novel_role_mention,
        "show_role": show_role,
        "status_text": status_text,
        "links_text": links_text,
    }

    return render_message("publish_novel_card", ctx)

# ---------------- main ----------------

if len(sys.argv) < 2:
    print("Usage: python publish_novel_card.py <short_code> [channel_id]")
    sys.exit(1)

SHORT_CODE = sys.argv[1].upper()

# If a second channel/thread ID is provided, post there too.
# It will still always post to the archive channel.
# The host-specific thread map is used only for the Forum Post link.
EXTRA_CHANNEL_ID = None

if len(sys.argv) >= 3 and sys.argv[2].strip():
    EXTRA_CHANNEL_ID = int(sys.argv[2])

intents = discord.Intents.default()
bot = discord.Client(intents=intents)

async def resolve_channel(channel_id: int):
    """
    bot.get_channel can fail for some threads if they are not cached.
    fetch_channel is safer.
    """
    channel = bot.get_channel(channel_id)
    if channel is None:
        channel = await bot.fetch_channel(channel_id)
    return channel

async def build_forum_post_url(forum_post_id):
    """
    Builds the Forum Post link using the correct server ID.

    forum_post_id now comes from the configured thread ID map.
    The bot fetches the channel/thread and reads the guild/server ID automatically.
    """
    forum_post_id = str(forum_post_id or "").strip()

    if not forum_post_id or forum_post_id.upper() == "N/A":
        return None

    try:
        forum_channel = await resolve_channel(int(forum_post_id))

        guild_id = None

        if getattr(forum_channel, "guild", None):
            guild_id = forum_channel.guild.id

        if not guild_id:
            guild_id = getattr(forum_channel, "guild_id", None)

        if not guild_id:
            print(f"Warning: could not find guild/server ID for forum_post_id {forum_post_id}")
            return None

        return f"https://discord.com/channels/{guild_id}/{forum_post_id}"

    except Exception as e:
        print(f"Warning: could not resolve forum post link for {forum_post_id}: {e}")
        return None

@bot.event
async def on_ready():
    state = load_state()

    for host, hostdata in HOSTING_SITE_DATA.items():
        for title, novel in hostdata["novels"].items():
            print("Checking:", novel.get("short_code"))

            if novel.get("short_code", "").upper() != SHORT_CODE:
                continue

            utils = get_host_utils(host)
            resolve_api_url = utils.get("resolve_chapters_api_url")

            if not resolve_api_url:
                print(f"❌ Host {host} does not support resolve_chapters_api_url.")
                continue

            api_url = resolve_api_url(hostdata, title, novel)

            if not api_url:
                print(f"❌ No chapters_api_url found for {host} / {title}")
                continue

            api = fetch_api(api_url, hostdata["token_secret"])
            chapters = flatten_chapters(api)

            completed, next_free_dt, last_free_dt = compute_status(
                chapters,
                novel.get("last_chapter"),
            )

            # Get the forum/thread ID from this host's configured Discord target, if any.
            forum_post_id = resolve_forum_post_id(host, SHORT_CODE)

            if not forum_post_id:
                print(f"Warning: no forum/thread ID found for {SHORT_CODE} in this host's configured Discord target.")

            forum_post_url = await build_forum_post_url(forum_post_id)

            # Always post to the primary/private archive.
            # Also post to the host/server archive when integrations.json points
            # this host to a Discord repo whose server.json has novel_cards_archive.
            # If a second channel/thread ID is passed manually, treat it as an
            # extra override/testing target. Each target resolves its role field
            # from the Discord integration that owns that channel/server.
            target_posts = [
                {
                    "channel_id": ARCHIVE_CHANNEL_ID,
                    "preferred_integration": DISCORD_INTEGRATION,
                }
            ]

            host_archive_target = host_novel_cards_archive_target(host)

            if host_archive_target:
                target_posts.append(host_archive_target)

            if EXTRA_CHANNEL_ID:
                target_posts.append({
                    "channel_id": EXTRA_CHANNEL_ID,
                    "preferred_integration": host_discord_integration_for_host(host),
                })

            # Avoid duplicate posts while preserving target integration hints.
            unique_posts = []
            seen_channel_ids = set()

            for post in target_posts:
                channel_id = int(post["channel_id"])
                if channel_id in seen_channel_ids:
                    continue
                seen_channel_ids.add(channel_id)
                unique_posts.append(post)

            state.setdefault(SHORT_CODE, [])

            for target_post in unique_posts:
                target_channel_id = int(target_post["channel_id"])
                preferred_integration = str(target_post.get("preferred_integration") or "").strip()

                already_posted = any(
                    str(item.get("channel_id")) == str(target_channel_id)
                    for item in state.get(SHORT_CODE, [])
                )
            
                if already_posted:
                    print(f"↷ Already has novel card for {SHORT_CODE} in {target_channel_id}; skipping.")
                    continue
            
                try:
                    channel = await resolve_channel(target_channel_id)
                    target_integration = integration_for_channel(channel, preferred_integration)
                    novel_role_mention = resolve_novel_role_mention(SHORT_CODE, target_integration)
            
                    payload = build_message_payload_for_channel(
                        title=title,
                        novel=novel,
                        host=host,
                        completed=completed,
                        next_free_dt=next_free_dt,
                        last_free_dt=last_free_dt,
                        target_channel_id=int(channel.id),
                        target_integration=target_integration,
                        forum_post_url=forum_post_url,
                        novel_role_mention=novel_role_mention,
                    )

                    msg = await channel.send(**to_discord_py_kwargs(payload))

                    entry = {
                        "channel_id": str(channel.id),
                        "message_id": str(msg.id),
                    }

                    if entry not in state[SHORT_CODE]:
                        state[SHORT_CODE].append(entry)
                        save_state(state)

                    print(f"Posted novel card for {SHORT_CODE} to {channel.id} using {target_integration or 'no'} Discord integration")

                except Exception as e:
                    print(f"Failed to post novel card for {SHORT_CODE} to {target_channel_id}: {e}")

            await bot.close()
            return

    print("Novel not found in mappings.")
    await bot.close()


bot.run(TOKEN)
