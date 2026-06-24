#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from message_renderer import render_message, to_discord_api_payload
from novel_mappings import HOSTING_SITE_DATA

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
CHANNEL_ID = int(os.environ["DISCORD_MOD_CHANNEL_ID"])
EVENT_PATH = os.environ["GITHUB_EVENT_PATH"]
REPO_SLUG = os.environ.get("GITHUB_REPOSITORY", "")
GLOBAL_MENTION = "||<@&1329392448798982214>||"


def _human_delta(secs: int) -> str:
    secs = max(0, int(secs))
    d, r = divmod(secs, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m and not d:
        parts.append(f"{m}m")  # keep it short
    return " ".join(parts) or "0m"


def main() -> None:
    with open(EVENT_PATH, "r", encoding="utf-8") as f:
        event = json.load(f)

    client_payload = event.get("client_payload", {}) or {}
    event_type = event.get("action", "")

    host = client_payload.get("host", "Unknown host")
    error_msg = client_payload.get("error", "")
    token_secret_name = client_payload.get("token_secret_name", "SECRET")

    exp = int(client_payload.get("exp", 0) or 0)
    secs_left = int(client_payload.get("secs_left", max(0, exp - int(time.time())))) if exp else 0

    # Nice timestamps for Discord
    # <t:unix:R> relative, <t:unix:F> full
    t_rel = f"<t:{exp}:R>"
    t_full = f"<t:{exp}:F>"

    # Host logo if present
    host_logo = ""
    if host in HOSTING_SITE_DATA:
        host_logo = HOSTING_SITE_DATA[host].get("host_logo", "")

    # Direct link to secret editor
    secret_url = f"https://github.com/{REPO_SLUG}/settings/secrets/actions/{token_secret_name}"

    ctx = {
        "global_mention": GLOBAL_MENTION,
        "host": host,
        "host_logo": host_logo,
        "error_msg": error_msg,
        "repo_slug": REPO_SLUG,
        "secret_url": secret_url,
        "expires_relative": t_rel,
        "expires_full": t_full,
        "secs_left": secs_left,
        "time_left_text": _human_delta(secs_left),
    }

    variant = "invalid" if event_type == "token-invalid" else "expiring"
    discord_payload = to_discord_api_payload(
        render_message("token_alert", ctx, variant=variant)
    )

    url = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"
    headers = {
        "Authorization": f"Bot {DISCORD_TOKEN}",
        "Content-Type": "application/json",
    }

    r = requests.post(url, headers=headers, json=discord_payload, timeout=20)
    if r.status_code >= 300:
        raise SystemExit(f"Discord send failed: {r.status_code} {r.text}")

    print("✅ Sent token alert to Discord.")


if __name__ == "__main__":
    main()
