#!/usr/bin/env python3
import os, json, time, datetime, requests

# Optional: pull logo/host pretty names from your mapping
try:
    from novel_mappings import HOSTING_SITE_DATA
except Exception:
    HOSTING_SITE_DATA = {}

DISCORD_TOKEN   = os.environ["DISCORD_BOT_TOKEN"]
CHANNEL_ID      = int(os.environ["DISCORD_MOD_CHANNEL_ID"])
EVENT_PATH      = os.environ["GITHUB_EVENT_PATH"]
REPO_SLUG       = os.environ.get("GITHUB_REPOSITORY", "")
GLOBAL_MENTION  = os.environ.get("GLOBAL_MENTION", "").strip()  # optional

def _human_delta(secs: int) -> str:
    secs = max(0, int(secs))
    d, r = divmod(secs, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m and not d: parts.append(f"{m}m")   # keep it short
    return " ".join(parts) or "0m"

def main():
    with open(EVENT_PATH, "r", encoding="utf-8") as f:
        event = json.load(f)

    payload = event.get("client_payload", {}) or {}
    host = payload.get("host", "Unknown host")
    token_secret_name = payload.get("token_secret_name", "SECRET")
    exp = int(payload.get("exp", 0))
    secs_left = int(payload.get("secs_left", max(0, exp - int(time.time()))))

    # Nice timestamps for Discord
    # <t:unix:R> relative, <t:unix:F> full
    t_rel = f"<t:{exp}:R>"
    t_full = f"<t:{exp}:F>"
    left_human = _human_delta(secs_left)

    # Host logo if present
    host_logo = ""
    if host in HOSTING_SITE_DATA:
        host_logo = HOSTING_SITE_DATA[host].get("host_logo", "")

    # Direct link to secret editor
    secret_url = f"https://github.com/{REPO_SLUG}/settings/secrets/actions/{token_secret_name}"

    # Fancy header outside embed (as you wanted)
    header = (
        "╔˚₊‧ ଳ ‧₊˚ ⋅══════════════╗\n"
        "     <:alertpink2:1365567099480707173>    *token expiration alert*\n"
        "╚══════════════˚₊‧ ଳ ‧₊˚ ⋅╝"
    )
    content = header
    if GLOBAL_MENTION:
        content = f"{GLOBAL_MENTION}\n{header}"

    # Embed body
    description = (
        f"**{host}** token is expiring soon\n"
        f"│ Token expires {t_rel} ({t_full}).\n"
        f"│ Time left: **{left_human}**.\n"
        f"│ Rotate the secret to prevent feed/API breakage.\n"
        f"│\n"
        f"│ Repo: `{REPO_SLUG}`"
    )

    embed = {
        "description": description,
        "color": int("F1202B", 16),
        "footer": {"text": "rss-feed • token watcher"},
    }
    # Put logo + host in the author line (title stays outside the embed)
    if host_logo:
        embed["author"] = {"name": host, "icon_url": host_logo}
    else:
        embed["author"] = {"name": host}

    # Link button
    components = [{
        "type": 1,  # action row
        "components": [{
            "type": 2,            # button
            "style": 5,           # link
            "label": "Update secret",
            "url": secret_url
        }]
    }]

    url = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"
    headers = {
        "Authorization": f"Bot {DISCORD_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "content": content,
        "embeds": [embed],
        "components": components,
        "allowed_mentions": {"parse": ["roles"]}  # allow role mentions if you supply one
    }

    r = requests.post(url, headers=headers, json=payload, timeout=20)
    if r.status_code >= 300:
        raise SystemExit(f"Discord send failed: {r.status_code} {r.text}")
    print("✅ Sent token alert to Discord.")

if __name__ == "__main__":
    main()
