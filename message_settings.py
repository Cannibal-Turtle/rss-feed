from __future__ import annotations

import os
from typing import Any, Mapping

from message_renderer import format_role_mention, parse_color, truthy

try:
    from config_loader import get_discord_webhook_role_id
except Exception:
    def get_discord_webhook_role_id(key: str, default: str = "") -> str:
        return default


def setting_bool(settings: Mapping[str, Any], key: str, default: bool = False, *, env: str = "") -> bool:
    raw = os.environ.get(env, "").strip() if env else ""

    if raw == "":
        raw = settings.get(key, default)

    return truthy(raw)


def setting_str(
    settings: Mapping[str, Any],
    key: str,
    default: str = "",
    *,
    env: str = "",
    fallback_env: str = "",
) -> str:
    env_value = os.environ.get(env, "").strip() if env else ""

    if not env_value and fallback_env:
        env_value = os.environ.get(fallback_env, "").strip()

    if env_value:
        return env_value

    value = settings.get(key, default)
    return str(value if value is not None else default).strip()


def setting_int(settings: Mapping[str, Any], key: str, default: int = 0, *, env: str = "") -> int:
    raw = setting_str(settings, key, str(default), env=env)

    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def setting_color_int(
    settings: Mapping[str, Any],
    key: str,
    default: int,
    *,
    env: str = "",
    fallback_env: str = "",
) -> int:
    raw = os.environ.get(env, "").strip() if env else ""

    if not raw and fallback_env:
        raw = os.environ.get(fallback_env, "").strip()

    if not raw:
        raw = settings.get(key, default)

    parsed = parse_color(raw)
    return int(parsed if parsed is not None else default)


def global_mention_from_settings(
    settings: Mapping[str, Any],
    *,
    envs: tuple[str, ...] = ("GLOBAL_MENTION",),
    role_setting: str = "global_mention_role",
    hidden_setting: str = "hide_global_mention",
    default_role: str = "admin",
) -> str:
    for env in envs:
        value = os.environ.get(env, "").strip()
        if value:
            return value

    direct_mention = setting_str(settings, "global_mention")
    if direct_mention:
        return direct_mention

    role_key = setting_str(settings, role_setting, default_role)
    hidden = setting_bool(settings, hidden_setting, True)

    if not role_key:
        return ""

    role_id = get_discord_webhook_role_id(role_key)
    return format_role_mention(role_id, hidden=hidden)