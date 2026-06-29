from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
_REMOTE_JSON_CACHE: dict[str, dict[str, Any]] = {}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def load_json_config(filename: str) -> dict[str, Any]:
    path = CONFIG_DIR / filename

    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"⚠️ Could not load {path}: {exc}")
        return {}

    return _as_dict(data)


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

    data = _as_dict(data)
    _REMOTE_JSON_CACHE[url] = data
    return data


def load_integrations_config() -> dict[str, Any]:
    return load_json_config("integrations.json")


def load_runtime_config() -> dict[str, Any]:
    return load_json_config("runtime.json")


def get_runtime_fetch_config() -> dict[str, Any]:
    return _as_dict(load_runtime_config().get("fetch", {}))


# ---------------- Source/mode config helpers ----------------

def normalize_config_key(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = text.replace("&", " and ")
    text = "".join(ch if ch.isalnum() else "_" for ch in text)
    text = "_".join(part for part in text.split("_") if part)
    return text


def load_source_modes_config() -> dict[str, Any]:
    return load_json_config("source_modes.json")


def get_source_mode_host_config(host: str) -> dict[str, Any]:
    cfg = load_source_modes_config()

    # Preferred shape:
    # {"mistmint_haven": {"free_chapters_source": "feed_api", ...}}
    # Also supports:
    # {"hosts": {"mistmint_haven": {...}}}
    host_map = _as_dict(cfg.get("hosts")) or cfg

    host_text = str(host or "").strip()
    candidates = []
    if host_text:
        candidates.append(host_text)
        candidates.append(normalize_config_key(host_text))

    seen: set[str] = set()
    for key in candidates:
        if not key or key in seen:
            continue
        seen.add(key)
        section = _as_dict(host_map.get(key))
        if section:
            return section

    return {}


def get_source_mode_value(host: str, key: str, default: Any = "") -> Any:
    section = get_source_mode_host_config(host)
    value = section.get(key, None)
    return default if value is None or value == "" else value


def get_downstream_repos() -> list[str]:
    cfg = load_integrations_config()
    dispatch = _as_dict(cfg.get("downstream_dispatch", {}))
    repos = dispatch.get("repos", [])
    return [str(repo).strip() for repo in repos if str(repo).strip()]


def get_dispatch_event(kind: str, default: str = "") -> str:
    cfg = load_integrations_config()
    dispatch = _as_dict(cfg.get("downstream_dispatch", {}))
    events = _as_dict(dispatch.get("events", {}))
    return str(events.get(kind) or default).strip()


# ---------------- Generic integration helpers ----------------

def get_integration_config(name: str) -> dict[str, Any]:
    cfg = load_integrations_config()
    return _as_dict(cfg.get(str(name or "").strip(), {}))


def get_integration_raw_base(name: str, default: str = "") -> str:
    section = get_integration_config(name)
    return str(section.get("raw_base") or default).strip().rstrip("/")


def get_integration_path(name: str, key: str, default: str = "") -> str:
    section = get_integration_config(name)
    paths = _as_dict(section.get("paths", {}))
    return str(paths.get(key) or default).strip().lstrip("/")


def get_integration_raw_url(
    name: str,
    key: str,
    default_path: str = "",
    default: str = "",
) -> str:
    base = get_integration_raw_base(name)
    path = get_integration_path(name, key, default_path)

    if base and path:
        return f"{base}/{path}"

    return str(default or "").strip()


def load_integration_json(
    name: str,
    key: str,
    default_path: str = "",
    *,
    timeout: int = 15,
) -> dict[str, Any]:
    return load_json_url(
        get_integration_raw_url(name, key, default_path),
        timeout=timeout,
    )


def get_integration_channel_id(
    name: str,
    key: str,
    default: str = "",
    *,
    server_key: str = "server_json",
    default_path: str = "config/server.json",
) -> str:
    server = load_integration_json(name, server_key, default_path)

    # Supports both flat server.json and a nested {"channels": {...}} shape.
    channels = _as_dict(server.get("channels", {}))
    value = server.get(key) or channels.get(key) or default
    return str(value or "").strip()


def get_integration_server_config(
    name: str,
    *,
    server_key: str = "server_json",
    default_path: str = "config/server.json",
    timeout: int = 15,
) -> dict[str, Any]:
    return load_integration_json(name, server_key, default_path, timeout=timeout)


def get_integration_server_value(
    name: str,
    key: str,
    default: str = "",
    *,
    server_key: str = "server_json",
    default_path: str = "config/server.json",
) -> str:
    server = get_integration_server_config(
        name,
        server_key=server_key,
        default_path=default_path,
    )

    # Supports both flat server.json and nested {"mentions": {...}} for mention strings.
    mentions = _as_dict(server.get("mentions", {}))
    value = server.get(key) or mentions.get(key) or default
    return str(value or "").strip()


def get_integration_global_mention(name: str, default: str = "") -> str:
    return get_integration_server_value(name, "global_mention", default)


def get_integration_guild_id(
    name: str,
    default: str = "",
    *,
    server_key: str = "server_json",
    default_path: str = "config/server.json",
) -> str:
    server = get_integration_server_config(
        name,
        server_key=server_key,
        default_path=default_path,
    )

    # Supports both flat server.json and a nested {"guild": {"id": "..."}} shape.
    guild = _as_dict(server.get("guild", {}))
    value = server.get("guild_id") or guild.get("id") or default
    return str(value or "").strip()


def get_integration_role_id(
    name: str,
    key: str,
    default: str = "",
    *,
    roles_key: str = "roles_json",
    default_path: str = "config/roles.json",
) -> str:
    roles = load_integration_json(name, roles_key, default_path)
    value = roles.get(key) or default
    return str(value or "").strip()


# ---------------- Generic Discord routing helpers ----------------

def get_primary_discord_config() -> dict[str, Any]:
    cfg = load_integrations_config()
    return _as_dict(cfg.get("primary_discord", {}))


def get_primary_discord_integration(default: str = "discord_webhook") -> str:
    primary = get_primary_discord_config()
    return str(primary.get("integration") or default).strip()


def get_host_discord_targets_config() -> dict[str, Any]:
    cfg = load_integrations_config()
    return _as_dict(cfg.get("host_discord_targets", {}))


def get_host_discord_target(host_key: str) -> dict[str, Any]:
    targets = get_host_discord_targets_config()
    return _as_dict(targets.get(str(host_key or "").strip(), {}))


# ---------------- Generic comments helpers ----------------

def get_comments_config(source: str) -> dict[str, Any]:
    cfg = load_integrations_config()
    comments = _as_dict(cfg.get("comments", {}))
    return _as_dict(comments.get(str(source or "").strip(), {}))


def get_comments_host_config(source: str) -> dict[str, Any]:
    comments = get_comments_config(source)
    return _as_dict(comments.get("host", {}))


def get_comments_enabled(source: str, default: bool = True) -> bool:
    comments = get_comments_config(source)
    raw = comments.get("enabled", default)

    if isinstance(raw, bool):
        return raw

    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}
