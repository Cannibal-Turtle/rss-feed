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


def get_integration_guild_id(
    name: str,
    default: str = "",
    *,
    server_key: str = "server_json",
    default_path: str = "config/server.json",
) -> str:
    server = load_integration_json(name, server_key, default_path)

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
