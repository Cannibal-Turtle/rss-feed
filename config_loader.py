from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
_REMOTE_JSON_CACHE: dict[str, dict[str, Any]] = {}

def load_json_config(filename: str) -> dict[str, Any]:
    path = CONFIG_DIR / filename

    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"⚠️ Could not load {path}: {exc}")
        return {}

    return data if isinstance(data, dict) else {}


def load_json_url(url: str, *, timeout: int = 15) -> dict[str, Any]:
    url = str(url or "").strip()
    if not url:
        return {}

    if url in _REMOTE_JSON_CACHE:
        return _REMOTE_JSON_CACHE[url]

    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        print(f"⚠️ Could not load remote JSON {url}: {exc}")
        data = {}

    if not isinstance(data, dict):
        data = {}

    _REMOTE_JSON_CACHE[url] = data
    return data


def load_integrations_config() -> dict[str, Any]:
    return load_json_config("integrations.json")


def get_downstream_repos() -> list[str]:
    cfg = load_integrations_config()
    repos = cfg.get("downstream_dispatch", {}).get("repos", [])
    return [str(repo).strip() for repo in repos if str(repo).strip()]


def get_dispatch_event(kind: str, default: str = "") -> str:
    cfg = load_integrations_config()
    event = (
        cfg.get("downstream_dispatch", {})
        .get("events", {})
        .get(kind)
    )
    return str(event or default).strip()


def get_discord_webhook_config() -> dict[str, Any]:
    cfg = load_integrations_config()
    section = cfg.get("discord_webhook", {})
    return section if isinstance(section, dict) else {}


def get_discord_webhook_raw_base(default: str = "") -> str:
    cfg = get_discord_webhook_config()
    return str(cfg.get("raw_base") or default).strip().rstrip("/")


def get_discord_webhook_path(key: str, default: str = "") -> str:
    cfg = get_discord_webhook_config()
    paths = cfg.get("paths", {})
    if not isinstance(paths, dict):
        paths = {}
    return str(paths.get(key) or default).strip().lstrip("/")


def get_discord_webhook_raw_url(key: str, default_path: str = "", default: str = "") -> str:
    base = get_discord_webhook_raw_base()
    path = get_discord_webhook_path(key, default_path)

    if base and path:
        return f"{base}/{path}"

    return default


def get_discord_webhook_server_url(default: str = "") -> str:
    return get_discord_webhook_raw_url(
        "server_json",
        "config/server.json",
        default,
    )


def get_novel_discord_map_url(default: str = "") -> str:
    return get_discord_webhook_raw_url(
        "novel_discord_map",
        "config/novel_discord_map.toml",
        default,
    )


def get_roles_json_url(default: str = "") -> str:
    return get_discord_webhook_raw_url(
        "roles_json",
        "config/roles.json",
        default,
    )


def get_tag_roles_url(default: str = "") -> str:
    return get_discord_webhook_raw_url(
        "tag_roles",
        "config/tag_roles.json",
        default,
    )


def get_completion_state_url(default: str = "") -> str:
    return get_discord_webhook_raw_url(
        "state",
        "state.json",
        default,
    )


def get_discord_webhook_server_json() -> dict[str, Any]:
    return load_json_url(get_discord_webhook_server_url())


def get_discord_webhook_roles_json() -> dict[str, Any]:
    return load_json_url(get_roles_json_url())


def get_discord_webhook_channel_id(key: str, default: str = "") -> str:
    server = get_discord_webhook_server_json()

    # Supports both flat server.json and the earlier nested shape.
    channels = server.get("channels", {})
    if not isinstance(channels, dict):
        channels = {}

    value = server.get(key) or channels.get(key) or default
    return str(value or "").strip()


def get_discord_webhook_guild_id(default: str = "") -> str:
    server = get_discord_webhook_server_json()

    guild = server.get("guild", {})
    if not isinstance(guild, dict):
        guild = {}

    value = server.get("guild_id") or guild.get("id") or default
    return str(value or "").strip()


def get_discord_webhook_role_id(key: str, default: str = "") -> str:
    roles = get_discord_webhook_roles_json()
    value = roles.get(key) or default
    return str(value or "").strip()


def get_mistmint_comments_config() -> dict[str, Any]:
    cfg = load_integrations_config()
    comments = (
        cfg.get("mistmint", {})
        .get("comments", {})
    )
    return comments if isinstance(comments, dict) else {}


def get_novelupdates_host_config() -> dict[str, Any]:
    cfg = load_integrations_config()
    host = (
        cfg.get("novelupdates", {})
        .get("host", {})
    )
    return host if isinstance(host, dict) else {}


def get_novelupdates_comments_config() -> dict[str, Any]:
    cfg = load_integrations_config()
    comments = (
        cfg.get("novelupdates", {})
        .get("comments", {})
    )
    return comments if isinstance(comments, dict) else {}


def get_paid_feed_config() -> dict[str, Any]:
    cfg = load_integrations_config()
    paid_feed = cfg.get("paid_feed", {})
    return paid_feed if isinstance(paid_feed, dict) else {}