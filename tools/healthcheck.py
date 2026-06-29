#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Safe repository healthcheck for rss-feed.

This is a local/CI sanity check. It does not post to Discord, does not require
Discord bot tokens, and does not require Mistmint cookies/API secrets.

It checks three levels:
1. Basic repo health: JSON/TOML parsing, Python syntax, ignored cache files.
2. Runtime config health: source_modes, integrations, host mappings, workflows.
3. Optional tool health: token alert, feed_api alert, membership, revenue,
   Novel Updates readers, novel cards, special announcements, comments.

Missing secrets are warnings at most. Disabled optional features are not errors.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 and below
    import tomli as tomllib  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
MAPPINGS_DIR = ROOT / "mappings"
TEMPLATE_DIR = ROOT / "message_templates"
WORKFLOW_DIR = ROOT / ".github" / "workflows"
SNAPSHOT_DIR = ROOT / "snapshots"

VALID_CHAPTER_SOURCE_MODES = {"feed", "api", "feed_api"}
VALID_CHAPTER_MODE = {"auto", "manual"}
VALID_COMMENT_SOURCE_MODES = {"trans", "public", "auto"}
SOURCE_MODE_KEYS = {
    "free_chapters_source",
    "paid_chapters_source",
    "chapter_mode",
    "comments_source",
}

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache"}


class Healthcheck:
    def __init__(self) -> None:
        self.ok_count = 0
        self.warnings: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self.sections: dict[str, dict[str, int]] = {}
        self.current_section = "general"

    def section(self, name: str) -> None:
        self.current_section = name
        self.sections.setdefault(name, {"ok": 0, "warnings": 0, "errors": 0})

    def _bump(self, kind: str) -> None:
        self.sections.setdefault(self.current_section, {"ok": 0, "warnings": 0, "errors": 0})
        self.sections[self.current_section][kind] += 1

    def ok(self, title: str, message: str = "", **ctx: Any) -> None:
        self.ok_count += 1
        self._bump("ok")
        print(f"✅ {title}: {message}" if message else f"✅ {title}")

    def warn(self, title: str, message: str = "", **ctx: Any) -> None:
        item = {"section": self.current_section, "title": title, "message": message, **ctx}
        self.warnings.append(item)
        self._bump("warnings")
        print(f"⚠️  {title}: {message}" if message else f"⚠️  {title}")

    def error(self, title: str, message: str = "", **ctx: Any) -> None:
        item = {"section": self.current_section, "title": title, "message": message, **ctx}
        self.errors.append(item)
        self._bump("errors")
        print(f"❌ {title}: {message}" if message else f"❌ {title}")

    def summary(self) -> dict[str, Any]:
        return {
            "ok": self.ok_count,
            "warning_count": len(self.warnings),
            "error_count": len(self.errors),
            "warnings": self.warnings,
            "errors": self.errors,
            "sections": self.sections,
        }


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y", "on"}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else {}


def _read_toml(path: Path) -> dict[str, Any] | None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else {}


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def _normalize_config_key(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = text.replace("&", " and ")
    text = "".join(ch if ch.isalnum() else "_" for ch in text)
    return "_".join(part for part in text.split("_") if part)


def _normalize_chapter_source_mode(value: Any) -> str:
    raw = str(value or "").strip().casefold().replace("-", "_").replace("+", "_")
    raw = re.sub(r"\s+", "_", raw)

    aliases = {
        "feed": "feed",
        "rss": "feed",
        "api": "api",
        "feed_api": "feed_api",
        "api_feed": "feed_api",
        "feed_with_api": "feed_api",
        "feed_with_api_fallback": "feed_api",
        "feed_api_fallback": "feed_api",
        "hybrid": "feed_api",
    }
    return aliases.get(raw, "")


def _python_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(ROOT.rglob("*.py")):
        parts = path.relative_to(ROOT).parts
        if any(part in SKIP_DIRS for part in parts):
            continue
        files.append(path)
    return files


def _load_host_data() -> dict[str, dict[str, Any]]:
    hosts: dict[str, dict[str, Any]] = {}
    hosts_dir = MAPPINGS_DIR / "hosts"
    if not hosts_dir.exists():
        return hosts

    for path in sorted(hosts_dir.glob("*.toml")):
        data = _read_toml(path)
        if data is None:
            continue
        name = str(data.get("name") or path.stem).strip()
        hosts[name] = data
        hosts[path.stem] = data
    return hosts


def _host_lookup(hosts: dict[str, dict[str, Any]], key: str) -> tuple[str, dict[str, Any] | None]:
    if key in hosts:
        display = str(hosts[key].get("name") or key).strip() or key
        return display, hosts[key]

    want = _normalize_config_key(key)
    for name, data in hosts.items():
        if _normalize_config_key(name) == want:
            display = str(data.get("name") or name).strip() or name
            return display, data

    return key, None


def _load_integrations() -> dict[str, Any]:
    return _read_json(CONFIG_DIR / "integrations.json") or {}


def _integration_section(cfg: dict[str, Any], name: str) -> dict[str, Any]:
    return _as_dict(cfg.get(str(name or "").strip()))


def _integration_paths(cfg: dict[str, Any], name: str) -> dict[str, Any]:
    return _as_dict(_integration_section(cfg, name).get("paths"))


def _integration_has_path(cfg: dict[str, Any], name: str, path_key: str) -> bool:
    return bool(str(_integration_paths(cfg, name).get(path_key) or "").strip())


def _template_exists(name: str) -> bool:
    return (TEMPLATE_DIR / f"{name}.toml").exists()


def _script_exists(path: str) -> bool:
    return (ROOT / path).exists()


def _template_payload_ok(hc: Healthcheck, name: str, ctx: dict[str, Any], *, variant: str | None = None) -> None:
    label = f"{name}[{variant}]" if variant else name
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from message_renderer import render_message, to_discord_api_payload

        payload = to_discord_api_payload(render_message(name, ctx, variant=variant))
        if payload.get("content") or payload.get("embeds") or payload.get("components"):
            hc.ok("template render", f"{label} renders Discord API payload")
        else:
            hc.error("template render", f"{label} rendered an empty payload")
    except Exception as exc:
        hc.error("template render", f"{label}: {exc}")


def _sample_ctx() -> dict[str, Any]:
    return {
        "accent_color": "#C9D3FF",
        "announcement_message": "Example announcement message.",
        "announcement_title": "Special Release Unlocked!",
        "banner_not_spoiler": True,
        "banner_spoiler": False,
        "banner_url": "https://example.com/banner.png",
        "button_label": "Read Now",
        "button_url": "https://example.com/read",
        "category": "SFW",
        "chapter": "Chapter 19",
        "chapter_type": "free",
        "chaptername": "Example Chapter Name",
        "container_spoiler": False,
        "description": "Example description.",
        "discord_color": "#C9D3FF",
        "discord_time": "<t:1893456000:D>",
        "embed_color": "#9DA148",
        "error_msg": "example error",
        "expires_full": "<t:1893456000:F>",
        "expires_relative": "<t:1893456000:R>",
        "featured_image": "https://example.com/cover.png",
        "feed_label": "public",
        "global_mention": "||<@&123456789012345678>||",
        "guid": "example-guid",
        "host": "Mistmint Haven",
        "host_divider": "•",
        "host_emoji": "<:mistmint:123456789012345678>",
        "host_logo": "https://example.com/logo.png",
        "label": "Example Novel",
        "link": "https://example.com/chapter",
        "links_text": "[Read](https://example.com)",
        "mention": "<@&123456789012345678>",
        "missing_count": 1,
        "missing_lines": "««« Example Novel — Chapter 19 not picked up by Mistmint Haven public feed",
        "mode": "api fallback",
        "month_label_upper": "JUNE 2026",
        "monthly_coins_text": "100 coins",
        "monthly_tickets_text": "2 tickets",
        "novel_role_mention": "<@&123456789012345678>",
        "novel_title": "Example Novel",
        "novel_url": "https://example.com/novel",
        "repo_slug": "Cannibal-Turtle/rss-feed",
        "role_mention": "<@&123456789012345678>",
        "safe_message": "example failure",
        "secret_url": "https://github.com/example/repo/settings/secrets/actions/SECRET",
        "short_code": "EX",
        "show_role": True,
        "status_text": "Ongoing",
        "timestamp": "2026-06-29T00:00:00+00:00",
        "title": "Example Novel",
        "volume": "Arc 1",
        "coins_total_text": "100 coins",
        "coins_delta_text": "+10 coins",
        "coin_emoji": "🪙",
        "tickets_total_text": "2 tickets",
        "tickets_delta_text": "+1 ticket",
        "ticket_emoji": "🎟️",
    }


def check_parse_files(hc: Healthcheck) -> None:
    hc.section("parse")

    for path in sorted(ROOT.rglob("*.json")):
        parts = path.relative_to(ROOT).parts
        if any(part in SKIP_DIRS for part in parts):
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
            hc.ok("json parse", _rel(path))
        except Exception as exc:
            hc.error("json parse", f"{_rel(path)}: {exc}")

    for path in sorted(ROOT.rglob("*.toml")):
        parts = path.relative_to(ROOT).parts
        if any(part in SKIP_DIRS for part in parts):
            continue
        try:
            tomllib.loads(path.read_text(encoding="utf-8"))
            hc.ok("toml parse", _rel(path))
        except Exception as exc:
            hc.error("toml parse", f"{_rel(path)}: {exc}")


def check_python_syntax(hc: Healthcheck) -> None:
    hc.section("python")
    for path in _python_files():
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
            hc.ok("python syntax", _rel(path))
        except Exception as exc:
            hc.error("python syntax", f"{_rel(path)}: {exc}")


def check_gitignore_and_cache(hc: Healthcheck) -> None:
    hc.section("gitignore")
    path = ROOT / ".gitignore"
    if not path.exists():
        hc.warn("gitignore", ".gitignore is missing")
    else:
        text = path.read_text(encoding="utf-8")
        if "__pycache__/" in text:
            hc.ok("gitignore", "__pycache__/ ignored")
        else:
            hc.warn("gitignore", "add __pycache__/")

        if "*.py[cod]" in text or "*.pyc" in text:
            hc.ok("gitignore", "compiled Python files ignored")
        else:
            hc.warn("gitignore", "add *.py[cod] so loose .pyc files are ignored too")

    caches = [p for p in ROOT.rglob("__pycache__") if ".git" not in p.parts]
    pycs = [p for p in ROOT.rglob("*.pyc") if ".git" not in p.parts]
    if caches or pycs:
        hc.warn("python cache files", f"found {len(caches)} __pycache__ folder(s) and {len(pycs)} .pyc file(s); do not commit them")
    else:
        hc.ok("python cache files", "no __pycache__/.pyc files found")


def check_workflow_script_paths(hc: Healthcheck) -> None:
    hc.section("workflows")
    if not WORKFLOW_DIR.exists():
        hc.warn("workflows", ".github/workflows is missing")
        return

    script_re = re.compile(r"(?:^|\s)python(?:\s+-m)?\s+([A-Za-z0-9_./-]+\.py)\b")
    count = 0
    for path in sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        for match in script_re.finditer(text):
            script = match.group(1)
            # Ignore heredoc snippets like python - <<'PY'. Regex does not match those.
            count += 1
            if (ROOT / script).exists():
                hc.ok("workflow script", f"{_rel(path)} → {script}")
            else:
                hc.error("workflow script", f"{_rel(path)} references missing {script}")

    if not count:
        hc.warn("workflow script", "no python script references found in workflows")


def check_source_modes(hc: Healthcheck, hosts: dict[str, dict[str, Any]]) -> None:
    hc.section("source modes")
    path = CONFIG_DIR / "source_modes.json"
    cfg = _read_json(path)
    if cfg is None:
        hc.error("source modes", "config/source_modes.json is missing or invalid JSON")
        return

    host_map = _as_dict(cfg.get("hosts")) or cfg
    if not host_map:
        hc.warn("source modes", "config/source_modes.json has no host sections")
        return

    for host_key, section_value in sorted(host_map.items()):
        if str(host_key).startswith("_"):
            continue

        section = _as_dict(section_value)
        if not section:
            hc.error("source modes", f"{host_key}: host section must be an object")
            continue

        host_name, host_data = _host_lookup(hosts, str(host_key))
        if host_data is None:
            hc.error("source modes", f"{host_key}: no matching mappings/hosts/*.toml found")
            continue

        unknown = sorted(set(section) - SOURCE_MODE_KEYS)
        if unknown:
            hc.warn("source modes", f"{host_key}: unknown key(s): {', '.join(unknown)}")

        for key in ("free_chapters_source", "paid_chapters_source"):
            raw = section.get(key, "")
            if raw == "":
                continue

            mode = _normalize_chapter_source_mode(raw)
            chapter_type = "free" if key.startswith("free") else "paid"
            feed_key = f"{chapter_type}_feed_url"

            if mode not in VALID_CHAPTER_SOURCE_MODES:
                hc.error("source modes", f"{host_key}.{key}: invalid mode {raw!r}")
                continue

            if mode in {"feed", "feed_api"} and not str(host_data.get(feed_key) or "").strip():
                hc.error("source modes", f"{host_key}.{key}={mode!r} needs {feed_key} in host mapping")

            if mode in {"api", "feed_api"} and not str(host_data.get("chapters_api_url") or "").strip():
                hc.error("source modes", f"{host_key}.{key}={mode!r} needs chapters_api_url in host mapping")

            hc.ok("source mode", f"{host_name}.{key} = {mode}")

        chapter_mode = str(section.get("chapter_mode", "") or "").strip().casefold()
        if chapter_mode:
            if chapter_mode not in VALID_CHAPTER_MODE:
                hc.error("source modes", f"{host_key}.chapter_mode: invalid mode {chapter_mode!r}")
            else:
                hc.ok("source mode", f"{host_name}.chapter_mode = {chapter_mode}")

        comments_source = str(section.get("comments_source", "") or "").strip().casefold()
        if comments_source:
            if comments_source not in VALID_COMMENT_SOURCE_MODES:
                hc.error("source modes", f"{host_key}.comments_source: invalid mode {comments_source!r}")
            else:
                if comments_source in {"trans", "auto"} and not str(host_data.get("comments_api_url") or "").strip():
                    hc.warn("source modes", f"{host_key}.comments_source={comments_source!r} but comments_api_url is missing")
                if comments_source == "trans" and not str(host_data.get("token_secret") or "").strip():
                    hc.warn("source modes", f"{host_key}.comments_source='trans' usually needs token_secret in host mapping")
                hc.ok("source mode", f"{host_name}.comments_source = {comments_source}")


def check_runtime_config(hc: Healthcheck) -> None:
    hc.section("runtime config")
    cfg = _read_json(CONFIG_DIR / "runtime.json")
    if cfg is None:
        hc.warn("runtime config", "config/runtime.json missing or invalid; defaults will be used")
        return

    fetch = _as_dict(cfg.get("fetch"))
    if not fetch:
        hc.warn("runtime config", "runtime.fetch is missing; defaults will be used")
        return

    for key in (
        "chapter_fetch_concurrency",
        "free_fetch_concurrency",
        "paid_fetch_concurrency",
        "max_chapter_fetch_concurrency",
    ):
        if key not in fetch:
            continue
        try:
            value = int(fetch[key])
            if value <= 0:
                hc.error("runtime config", f"fetch.{key} must be > 0")
            else:
                hc.ok("runtime config", f"fetch.{key} = {value}")
        except Exception:
            hc.error("runtime config", f"fetch.{key} must be an integer")


def check_integrations_base(hc: Healthcheck, cfg: dict[str, Any]) -> None:
    hc.section("integrations")
    if not cfg:
        hc.error("integrations", "config/integrations.json is missing or invalid JSON")
        return

    dispatch = _as_dict(cfg.get("downstream_dispatch"))
    repos = _as_list(dispatch.get("repos"))
    events = _as_dict(dispatch.get("events"))
    if repos:
        bad = [repo for repo in repos if not re.fullmatch(r"[^/\s]+/[^/\s]+", str(repo or ""))]
        if bad:
            hc.error("downstream dispatch", f"bad repo slug(s): {bad}")
        else:
            hc.ok("downstream dispatch", f"{len(repos)} repo(s) configured")
    else:
        hc.warn("downstream dispatch", "no downstream_dispatch.repos configured")

    for kind in ("chapters", "comments"):
        if str(events.get(kind) or "").strip():
            hc.ok("downstream dispatch", f"event for {kind}: {events[kind]}")
        else:
            hc.warn("downstream dispatch", f"event for {kind} is missing")

    primary = _as_dict(cfg.get("primary_discord"))
    primary_name = str(primary.get("integration") or "discord_webhook").strip()
    if not _integration_section(cfg, primary_name):
        hc.warn("primary discord", f"integration {primary_name!r} not found")
    else:
        hc.ok("primary discord", f"integration = {primary_name}")

    for name, section in sorted(cfg.items()):
        if not isinstance(section, dict):
            continue
        if "raw_base" not in section and "paths" not in section:
            continue
        raw_base = str(section.get("raw_base") or "").strip()
        paths = _as_dict(section.get("paths"))
        if raw_base:
            hc.ok("integration", f"{name}.raw_base configured")
        else:
            hc.warn("integration", f"{name}.raw_base missing")
        if paths:
            hc.ok("integration", f"{name}.paths has {len(paths)} item(s)")
        else:
            hc.warn("integration", f"{name}.paths missing")


def check_host_discord_targets(hc: Healthcheck, cfg: dict[str, Any], hosts: dict[str, dict[str, Any]]) -> None:
    hc.section("discord routes")
    targets = _as_dict(cfg.get("host_discord_targets"))
    if not targets:
        hc.warn("host discord targets", "no host_discord_targets configured")
        return

    for host_key, target_value in sorted(targets.items()):
        host_name, host_data = _host_lookup(hosts, host_key)
        if host_data is None:
            hc.error("host discord targets", f"{host_key}: no matching host mapping")
            continue

        target = _as_dict(target_value)
        integration = str(target.get("integration") or "").strip()
        if not integration:
            hc.error("host discord targets", f"{host_key}: integration missing")
            continue
        if not _integration_section(cfg, integration):
            hc.error("host discord targets", f"{host_key}: integration {integration!r} not found")
            continue

        routes = _as_dict(target.get("routes"))
        if not routes:
            hc.warn("host discord targets", f"{host_key}: no routes configured")
            continue

        for route_name, route_value in sorted(routes.items()):
            route = _as_dict(route_value)
            route_type = str(route.get("type") or "").strip()
            if route_type == "thread_map":
                map_key = str(route.get("map_key") or "").strip()
                if not map_key:
                    hc.error("host discord targets", f"{host_key}.{route_name}: thread_map needs map_key")
                elif not _integration_has_path(cfg, integration, map_key) and not str(route.get("default_path") or "").strip():
                    hc.error("host discord targets", f"{host_key}.{route_name}: map_key {map_key!r} has no integration path/default_path")
                else:
                    hc.ok("host route", f"{host_name}.{route_name} → {integration}.{map_key}")
            elif route_type == "channel":
                channel_key = str(route.get("channel_key") or "").strip()
                server_key = str(route.get("server_key") or "server_json").strip()
                if not channel_key:
                    hc.error("host discord targets", f"{host_key}.{route_name}: channel route needs channel_key")
                elif not _integration_has_path(cfg, integration, server_key) and not str(route.get("default_path") or "").strip():
                    hc.error("host discord targets", f"{host_key}.{route_name}: server_key {server_key!r} has no integration path/default_path")
                else:
                    hc.ok("host route", f"{host_name}.{route_name} → {integration}.{server_key}:{channel_key}")
            else:
                hc.warn("host discord targets", f"{host_key}.{route_name}: unknown route type {route_type!r}")


def check_feed_api_alert(hc: Healthcheck, cfg: dict[str, Any]) -> None:
    hc.section("feed_api alert")
    alerts = _as_dict(cfg.get("feed_api_alerts"))
    if not alerts:
        hc.ok("feed_api alerts", "no section; disabled")
        return

    if not _script_exists("feed_api/send_feed_api_alert.py"):
        hc.error("feed_api alerts", "feed_api/send_feed_api_alert.py missing")
    else:
        hc.ok("feed_api alerts", "script exists")

    if not _template_exists("feed_api_alert"):
        hc.error("feed_api alerts", "message_templates/feed_api_alert.toml missing")
    else:
        hc.ok("feed_api alerts", "template exists")
        _template_payload_ok(hc, "feed_api_alert", _sample_ctx())

    if not _truthy(alerts.get("enabled", False)):
        hc.ok("feed_api alerts", "disabled; no token/channel required")
        return

    integration_name = str(alerts.get("integration") or "discord_webhook").strip()
    integration = _integration_section(cfg, integration_name)
    paths = _as_dict(integration.get("paths"))
    if not integration:
        hc.error("feed_api alerts", f"integration {integration_name!r} not found")
        return

    if alerts.get("channel_id"):
        hc.ok("feed_api alerts", "channel_id configured directly")
    else:
        channel_key = str(alerts.get("channel_key") or "mod").strip() or "mod"
        if not paths.get("server_json"):
            hc.error("feed_api alerts", f"channel_key={channel_key!r} needs {integration_name}.paths.server_json")
        else:
            hc.ok("feed_api alerts", f"channel_key={channel_key!r} via server_json")

    has_direct_mention = bool(str(alerts.get("mention") or "").strip())
    has_direct_role_id = bool(str(alerts.get("mention_role_id") or alerts.get("role_id") or "").strip())
    role_key = str(alerts.get("mention_role_key") or alerts.get("role_key") or "").strip()
    if has_direct_mention or has_direct_role_id:
        hc.ok("feed_api alerts", "mention configured directly")
    elif role_key:
        roles_path_key = str(alerts.get("roles_key") or "roles_json").strip() or "roles_json"
        if not paths.get(roles_path_key):
            hc.error("feed_api alerts", f"mention_role_key={role_key!r} needs {integration_name}.paths.{roles_path_key}")
        else:
            hc.ok("feed_api alerts", f"mention_role_key={role_key!r} via {roles_path_key}")
    else:
        hc.warn("feed_api alerts", "enabled but no mention/role configured; alert will send without ping")

    try:
        max_items = int(alerts.get("max_items") or 10)
        if max_items <= 0:
            hc.error("feed_api alerts", "max_items must be > 0")
        else:
            hc.ok("feed_api alerts", f"max_items = {max_items}")
    except Exception:
        hc.error("feed_api alerts", "max_items must be an integer")

    if os.getenv("DISCORD_BOT_TOKEN"):
        hc.ok("feed_api alerts", "DISCORD_BOT_TOKEN is available for local/CI posting scripts")
    else:
        hc.ok("feed_api alerts", "DISCORD_BOT_TOKEN not set; healthcheck does not need secrets")


def _check_template_settings_role(
    hc: Healthcheck,
    cfg: dict[str, Any],
    *,
    template_name: str,
    tool_name: str,
    integration: str = "discord_webhook",
    role_setting: str = "global_mention_role",
) -> None:
    path = TEMPLATE_DIR / f"{template_name}.toml"
    data = _read_toml(path) or {}
    settings = _as_dict(data.get("settings"))
    role_key = str(settings.get(role_setting) or "").strip()
    if not role_key:
        return
    if _integration_has_path(cfg, integration, "roles_json"):
        hc.ok(tool_name, f"{template_name}.{role_setting}={role_key!r} can use {integration}.roles_json")
    else:
        hc.warn(tool_name, f"{template_name}.{role_setting}={role_key!r} but {integration}.paths.roles_json is missing")


def check_token_alert(hc: Healthcheck, cfg: dict[str, Any]) -> None:
    hc.section("token alert")
    if not _script_exists("token/send_token_alert.py"):
        hc.error("token alert", "token/send_token_alert.py missing")
    else:
        hc.ok("token alert", "script exists")

    if not _template_exists("token_alert"):
        hc.error("token alert", "message_templates/token_alert.toml missing")
        return

    hc.ok("token alert", "template exists")
    ctx = _sample_ctx()
    _template_payload_ok(hc, "token_alert", ctx, variant="expiring")
    _template_payload_ok(hc, "token_alert", ctx, variant="invalid")

    if _integration_has_path(cfg, "discord_webhook", "server_json"):
        hc.ok("token alert", "mod channel can be resolved through discord_webhook.server_json")
    else:
        hc.warn("token alert", "mod channel lookup needs discord_webhook.paths.server_json")

    _check_template_settings_role(hc, cfg, template_name="token_alert", tool_name="token alert")

    token_hosts = []
    for data in _load_host_data().values():
        if str(data.get("token_secret") or "").strip():
            token_hosts.append(str(data.get("name") or "host"))
    if token_hosts:
        hc.ok("token alert", f"{len(set(token_hosts))} host(s) declare token_secret")
    else:
        hc.warn("token alert", "no host mapping declares token_secret")


def check_membership_tool(hc: Healthcheck, cfg: dict[str, Any]) -> None:
    hc.section("membership tool")
    if not _script_exists("tools/publish_membership_update.py"):
        hc.error("membership", "tools/publish_membership_update.py missing")
    else:
        hc.ok("membership", "script exists")

    if not _template_exists("membership_update"):
        hc.error("membership", "message_templates/membership_update.toml missing")
    else:
        hc.ok("membership", "template exists")
        ctx = _sample_ctx()
        ctx.update({"global_mention": "||@everyone||", "banner_spoiler": False, "banner_not_spoiler": True})
        _template_payload_ok(hc, "membership_update", ctx)

    targets = _as_dict(cfg.get("host_discord_targets"))
    found = False
    for host_key, host_routes in targets.items():
        routes = _as_dict(_as_dict(host_routes).get("routes"))
        if "membership_update" in routes:
            found = True
            hc.ok("membership", f"route configured for {host_key}")
    if not found:
        hc.warn("membership", "no host_discord_targets.*.routes.membership_update configured")


def check_revenue_tool(hc: Healthcheck, cfg: dict[str, Any]) -> None:
    hc.section("revenue tool")
    if not _script_exists("revenue/report.py"):
        hc.error("revenue", "revenue/report.py missing")
    else:
        hc.ok("revenue", "script exists")

    if not _template_exists("revenue_report"):
        hc.error("revenue", "message_templates/revenue_report.toml missing")
    else:
        hc.ok("revenue", "template exists")
        ctx = _sample_ctx()
        _template_payload_ok(hc, "revenue_report", ctx, variant="message")
        _template_payload_ok(hc, "revenue_report", ctx, variant="error")
        _template_payload_ok(hc, "revenue_report", ctx, variant="embed")

    hosts_dir = ROOT / "revenue" / "hosts"
    adapters = sorted(p for p in hosts_dir.glob("*.py") if p.name != "__init__.py") if hosts_dir.exists() else []
    if adapters:
        hc.ok("revenue", f"{len(adapters)} host adapter(s): {', '.join(p.stem for p in adapters)}")
    else:
        hc.warn("revenue", "no revenue/hosts/*.py adapters found")

    _check_template_settings_role(hc, cfg, template_name="revenue_report", tool_name="revenue")


def check_novel_card_tool(hc: Healthcheck, cfg: dict[str, Any]) -> None:
    hc.section("novel card tool")
    if not _script_exists("tools/publish_novel_card.py"):
        hc.error("novel card", "tools/publish_novel_card.py missing")
    else:
        hc.ok("novel card", "publish script exists")

    if not _script_exists("tools/update_novel_card.py"):
        hc.warn("novel card", "tools/update_novel_card.py missing")
    else:
        hc.ok("novel card", "update script exists")

    if not _template_exists("publish_novel_card"):
        hc.error("novel card", "message_templates/publish_novel_card.toml missing")
    else:
        hc.ok("novel card", "template exists")
        _template_payload_ok(hc, "publish_novel_card", _sample_ctx())

    targets = _as_dict(cfg.get("host_discord_targets"))
    found = False
    for host_key, host_routes in targets.items():
        routes = _as_dict(_as_dict(host_routes).get("routes"))
        if "publish_novel_card" in routes:
            found = True
            hc.ok("novel card", f"route configured for {host_key}")
    if not found:
        hc.warn("novel card", "no host_discord_targets.*.routes.publish_novel_card configured")


def check_special_announcement_tool(hc: Healthcheck, cfg: dict[str, Any]) -> None:
    hc.section("special announcement tool")
    if not _script_exists("tools/publish_special_announcement.py"):
        hc.error("special announcement", "tools/publish_special_announcement.py missing")
    else:
        hc.ok("special announcement", "script exists")

    if not _template_exists("special_announcement"):
        hc.error("special announcement", "message_templates/special_announcement.toml missing")
    else:
        hc.ok("special announcement", "template exists")
        ctx = _sample_ctx()
        ctx.update({"container_spoiler": False, "banner_spoiler": False, "banner_not_spoiler": True})
        _template_payload_ok(hc, "special_announcement", ctx)

    targets = _as_dict(cfg.get("host_discord_targets"))
    found = False
    for host_key, host_routes in targets.items():
        routes = _as_dict(_as_dict(host_routes).get("routes"))
        if "special_announcement" in routes:
            found = True
            hc.ok("special announcement", f"route configured for {host_key}")
    if not found:
        hc.warn("special announcement", "no host_discord_targets.*.routes.special_announcement configured")


def check_nu_weekly_tool(hc: Healthcheck, cfg: dict[str, Any]) -> None:
    hc.section("nu weekly readers")
    if not _script_exists("novelupdates/nu_weekly_readers.py"):
        hc.error("nu weekly", "novelupdates/nu_weekly_readers.py missing")
    else:
        hc.ok("nu weekly", "script exists")

    if not _template_exists("nu_weekly_readers"):
        hc.error("nu weekly", "message_templates/nu_weekly_readers.toml missing")
    else:
        hc.ok("nu weekly", "template exists")
        ctx = _sample_ctx()
        ctx.update({"count": 123, "delta_text": "+5 this week"})
        _template_payload_ok(hc, "nu_weekly_readers", ctx, variant="message")

    _check_template_settings_role(hc, cfg, template_name="nu_weekly_readers", tool_name="nu weekly")


def check_comments_config(hc: Healthcheck, cfg: dict[str, Any]) -> None:
    hc.section("comments")
    if not _script_exists("comments.py"):
        hc.error("comments", "comments.py missing")
    else:
        hc.ok("comments", "comments.py exists")

    comments = _as_dict(cfg.get("comments"))
    if not comments:
        hc.warn("comments", "integrations.comments config missing")
        return

    for source, section_value in sorted(comments.items()):
        section = _as_dict(section_value)
        if not section:
            hc.warn("comments", f"{source}: config section is empty")
            continue
        hc.ok("comments", f"{source} config exists")
        for key in sorted(k for k in section if k.endswith("concurrency_default") or k.endswith("concurrency_max")):
            try:
                value = int(section[key])
                if value <= 0:
                    hc.error("comments", f"{source}.{key} must be > 0")
                else:
                    hc.ok("comments", f"{source}.{key} = {value}")
            except Exception:
                hc.error("comments", f"{source}.{key} must be an integer")

    if _script_exists("host_utils/host_nu_comments.py"):
        hc.ok("comments", "Novel Updates comments helper exists")
    else:
        hc.warn("comments", "host_utils/host_nu_comments.py missing")


def check_novel_mappings(hc: Healthcheck, hosts: dict[str, dict[str, Any]]) -> None:
    hc.section("novel mappings")
    novels_dir = MAPPINGS_DIR / "novels"
    if not novels_dir.exists():
        hc.warn("novel mappings", "mappings/novels missing")
        return

    files = sorted(novels_dir.glob("*.toml"))
    if not files:
        hc.warn("novel mappings", "no novel TOML files found")
        return

    seen_codes: dict[str, str] = {}
    for path in files:
        data = _read_toml(path)
        if data is None:
            continue
        title = str(data.get("title") or data.get("novel_title") or "").strip()
        host = str(data.get("host") or data.get("hosting_site") or "").strip()
        short_code = str(data.get("short_code") or path.stem).strip().upper()
        if not title:
            hc.warn("novel mapping", f"{_rel(path)}: title missing")
        if not host:
            hc.warn("novel mapping", f"{_rel(path)}: host missing")
        elif _host_lookup(hosts, host)[1] is None:
            hc.warn("novel mapping", f"{_rel(path)}: host {host!r} has no host mapping")
        if short_code in seen_codes:
            hc.error("novel mapping", f"duplicate short_code {short_code}: {_rel(path)} and {seen_codes[short_code]}")
        else:
            seen_codes[short_code] = _rel(path)
    hc.ok("novel mappings", f"checked {len(files)} novel file(s)")


def check_card_status_update(hc: Healthcheck, cfg: dict[str, Any]) -> None:
    hc.section("card status update")
    card = _as_dict(cfg.get("card_status_update"))
    if not card:
        hc.ok("card status update", "no config section; disabled")
        return
    if not _truthy(card.get("enabled", False)):
        hc.ok("card status update", "disabled")
        return
    if str(card.get("repo") or "").strip():
        hc.ok("card status update", f"repo = {card.get('repo')}")
    else:
        hc.error("card status update", "enabled but repo is missing")
    if str(card.get("event_type") or "").strip():
        hc.ok("card status update", f"event_type = {card.get('event_type')}")
    else:
        hc.error("card status update", "enabled but event_type is missing")


def run_all_checks(*, include_python: bool = True) -> Healthcheck:
    hc = Healthcheck()
    check_parse_files(hc)
    if include_python:
        check_python_syntax(hc)
    check_gitignore_and_cache(hc)
    check_workflow_script_paths(hc)

    hosts = _load_host_data()
    cfg = _load_integrations()

    check_novel_mappings(hc, hosts)
    check_source_modes(hc, hosts)
    check_runtime_config(hc)
    check_integrations_base(hc, cfg)
    check_host_discord_targets(hc, cfg, hosts)
    check_card_status_update(hc, cfg)

    check_feed_api_alert(hc, cfg)
    check_token_alert(hc, cfg)
    check_membership_tool(hc, cfg)
    check_revenue_tool(hc, cfg)
    check_novel_card_tool(hc, cfg)
    check_special_announcement_tool(hc, cfg)
    check_nu_weekly_tool(hc, cfg)
    check_comments_config(hc, cfg)

    return hc


def write_snapshot(hc: Healthcheck, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(hc.summary(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📝 wrote {_rel(path)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check rss-feed config, templates, workflows, and optional tools.")
    parser.add_argument("--no-python", action="store_true", help="Skip Python syntax checks.")
    parser.add_argument("--snapshot", action="store_true", help="Write snapshots/diagnostics.json.")
    parser.add_argument("--json-out", default="snapshots/diagnostics.json", help="Snapshot path when --snapshot is used.")
    args = parser.parse_args()

    hc = run_all_checks(include_python=not args.no_python)

    if args.snapshot:
        write_snapshot(hc, ROOT / args.json_out)

    summary = hc.summary()
    print("\n=== Healthcheck summary ===")
    print(f"OK: {summary['ok']}")
    print(f"Warnings: {summary['warning_count']}")
    print(f"Errors: {summary['error_count']}")

    return 1 if summary["error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
