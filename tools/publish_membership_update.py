#!/usr/bin/env python3
import io
import json
import os
import sys
import re
import requests
from pathlib import Path

from PIL import Image, ImageOps, ImageDraw

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
        get_host_discord_target,
        get_integration_channel_id,
        get_integration_global_mention,
        get_integration_guild_id,
        get_integration_raw_url,
        get_primary_discord_integration,
    )
except Exception:
    def get_host_discord_target(host_key: str):
        return {}

    def get_integration_channel_id(name: str, key: str, default: str = "") -> str:
        return default

    def get_integration_global_mention(name: str, default: str = "") -> str:
        return default

    def get_integration_guild_id(name: str, default: str = "") -> str:
        return default

    def get_integration_raw_url(name: str, key: str, default_path: str = "", default: str = "") -> str:
        return default

    def get_primary_discord_integration(default: str = "discord_webhook") -> str:
        return default

PRIMARY_DISCORD_INTEGRATION = (
    os.getenv("PRIMARY_DISCORD_INTEGRATION", "").strip()
    or os.getenv("DISCORD_INTEGRATION", "").strip()
    or get_primary_discord_integration("discord_webhook")
    or "discord_webhook"
)

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()

API_BASE = "https://discord.com/api/v10"

_TEMPLATE_SETTINGS = load_template_settings("membership_update")

NOVEL_DISCORD_MAP_URL = (
    os.environ.get("NOVEL_DISCORD_MAP_URL", "").strip()
    or get_integration_raw_url(PRIMARY_DISCORD_INTEGRATION, "novel_discord_map", "config/novel_discord_map.toml")
    or setting_str(_TEMPLATE_SETTINGS, "novel_discord_map_url")
)
# currently only supports single server role attachment
# Reads role IDs from discord-webhook's rich novel Discord TOML map.

# Always post here first.
# This is your server's news channel.
NEWS_CHANNEL_ID = int(
    os.environ.get("NEWS_CHANNEL_ID", "").strip()
    or get_integration_channel_id(PRIMARY_DISCORD_INTEGRATION, "announcements")
    or setting_str(_TEMPLATE_SETTINGS, "news_channel_id", "0")
    or 0
)

# Preview mode posts to discord-webhook/config/server.json -> channels.mod.
# No channel ID is hardcoded here.
PREVIEW_CHANNEL_ID = int(
    os.environ.get("MEMBERSHIP_PREVIEW_CHANNEL_ID", "").strip()
    or os.environ.get("DISCORD_MOD_CHANNEL_ID", "").strip()
    or get_integration_channel_id(PRIMARY_DISCORD_INTEGRATION, "mod")
    or setting_str(_TEMPLATE_SETTINGS, "preview_channel_id", "0")
    or 0
)

# Private/news server uses novel role + status role.
# Status role comes from discord-webhook roles.json:
# complete if paid_completion exists in state.json, otherwise ongoing.
# Non-private servers get public_global_mention.
MY_SERVER_GUILD_ID = (
    os.environ.get("MY_SERVER_GUILD_ID", "").strip()
    or get_integration_guild_id(PRIMARY_DISCORD_INTEGRATION)
    or setting_str(_TEMPLATE_SETTINGS, "private_guild_id")
)

ROLES_JSON_URL = (
    os.environ.get("ROLES_JSON_URL", "").strip()
    or get_integration_raw_url(PRIMARY_DISCORD_INTEGRATION, "roles_json", "config/roles.json")
    or setting_str(_TEMPLATE_SETTINGS, "roles_json_url")
)

COMPLETION_STATE_URL = (
    os.environ.get("COMPLETION_STATE_URL", "").strip()
    or get_integration_raw_url(PRIMARY_DISCORD_INTEGRATION, "state", "state.json")
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
BANNER_OUTPUT_PATH = Path(os.environ.get("MEMBERSHIP_BANNER_OUTPUT", "membership_banner.png")).resolve()
BANNER_FILENAME = BANNER_OUTPUT_PATH.name
BANNER_SIZE = (1600, 400)
BANNER_RATIO = BANNER_SIZE[0] / BANNER_SIZE[1]
VALID_MODES = {"crop preview", "preview", "publish"}
VALID_CROP_POSITIONS = {"top", "upper", "upper center", "center", "lower center", "lower", "bottom"}
CROP_PREVIEW_POSITIONS = ["top", "upper", "upper center", "center", "lower center", "lower", "bottom"]


def host_config_key(host: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(host or "").strip().casefold()).strip("_")


def dedupe_targets(targets):
    seen = set()
    deduped = []

    for target in targets:
        channel_id = int(target.get("channel_id") or 0)
        if not channel_id or channel_id in seen:
            continue
        seen.add(channel_id)
        target = dict(target)
        target["channel_id"] = channel_id
        deduped.append(target)

    return deduped


def target_label(target):
    label = str(target.get("label") or "").strip()
    integration = str(target.get("integration") or "").strip()
    channel_id = str(target.get("channel_id") or "").strip()
    return label or f"{integration}:{channel_id}"


def require_discord_token():
    if not TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN is required for preview/publish mode.")


def discord_json_headers():
    require_discord_token()
    return {
        "Authorization": f"Bot {TOKEN}",
        "Content-Type": "application/json",
    }


def discord_auth_headers():
    require_discord_token()
    return {
        "Authorization": f"Bot {TOKEN}",
    }


_NOVEL_ROLE_ID_MAP_CACHE = {}


def normalize_role_id(value):
    m = re.search(r"\d{5,}", str(value or ""))
    return m.group(0) if m else ""


def novel_discord_map_url_for_integration(integration: str) -> str:
    if integration == PRIMARY_DISCORD_INTEGRATION:
        return NOVEL_DISCORD_MAP_URL

    return get_integration_raw_url(integration, "novel_discord_map")


def fetch_novel_role_id_map(integration: str = PRIMARY_DISCORD_INTEGRATION):
    """Fetch the target Discord integration's novel_discord_map.toml as short_code -> role_id."""
    url = novel_discord_map_url_for_integration(integration)

    if not url:
        return {}

    if url in _NOVEL_ROLE_ID_MAP_CACHE:
        return _NOVEL_ROLE_ID_MAP_CACHE[url]

    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = tomllib.loads(r.text)
    except Exception as exc:
        print(f"Warning: could not load novel role map for {integration} from {url}: {exc}")
        data = {}

    if not isinstance(data, dict):
        print(f"Warning: novel_discord_map_url did not return a TOML table: {url}")
        data = {}

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

def resolve_novel_role_mention(short_code, integration: str = PRIMARY_DISCORD_INTEGRATION):
    role_map = fetch_novel_role_id_map(integration)
    role_id = role_map.get(short_code.upper())
    return f"<@&{role_id}>" if role_id else ""


_THREAD_ID_MAP_CACHE = {}


def fetch_thread_id_map(
    integration: str,
    map_key: str = "thread_id_map",
    default_path: str = "config/thread_id_map.json",
):
    """
    Fetches a host Discord integration's thread ID map.

    Expected JSON format:
    {
      "TVITPA": "1444214902322368675",
      "TDLBKGC": "1438462596381413417",
      "BOE": "N/A"
    }
    """
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


def resolve_forum_thread_id(integration: str, short_code: str, route: dict):
    """
    Gets the thread ID for this novel from the selected host Discord route.
    """
    map_key = str(route.get("map_key") or "thread_id_map").strip()
    default_path = str(route.get("default_path") or "config/thread_id_map.json").strip()
    thread_map = fetch_thread_id_map(integration, map_key, default_path)
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
            headers=discord_json_headers(),
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Warning: could not fetch channel {channel_id}: {e}")
        return {}


def role_ids_from_text(text: str):
    return re.findall(r"<@&(\d+)>", text or "")


def user_ids_from_text(text: str):
    return re.findall(r"<@!?(\d+)>", text or "")


def normalize_mention_value(value, *, digits_as_role: bool = True) -> str:
    text = str(value or "").strip()

    if not text:
        return ""

    if re.fullmatch(r"\d{5,}", text):
        return f"<@&{text}>" if digits_as_role else f"<@{text}>"

    return text


def role_mention_from_id(value) -> str:
    role_id = normalize_role_id(value)
    return f"<@&{role_id}>" if role_id else ""


_ROLES_JSON_CACHE = {}
_COMPLETION_STATE_CACHE = {}


def roles_json_url_for_integration(integration: str) -> str:
    if integration == PRIMARY_DISCORD_INTEGRATION:
        return ROLES_JSON_URL

    return get_integration_raw_url(integration, "roles_json")


def completion_state_url_for_integration(integration: str) -> str:
    if integration == PRIMARY_DISCORD_INTEGRATION:
        return COMPLETION_STATE_URL

    return get_integration_raw_url(integration, "state")


def guild_id_for_integration(integration: str) -> str:
    if integration == PRIMARY_DISCORD_INTEGRATION:
        return MY_SERVER_GUILD_ID

    return get_integration_guild_id(integration)


def fetch_roles_json(integration: str = PRIMARY_DISCORD_INTEGRATION):
    url = roles_json_url_for_integration(integration)

    if not url:
        return {}

    if url in _ROLES_JSON_CACHE:
        return _ROLES_JSON_CACHE[url]

    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        print(f"Warning: could not load roles_json for {integration} from {url}: {exc}")
        data = {}

    if not isinstance(data, dict):
        print(f"Warning: roles_json_url did not return a JSON object: {url}")
        data = {}

    _ROLES_JSON_CACHE[url] = data
    return _ROLES_JSON_CACHE[url]

def fetch_completion_state(integration: str = PRIMARY_DISCORD_INTEGRATION):
    url = completion_state_url_for_integration(integration)

    if not url:
        return {}

    if url in _COMPLETION_STATE_CACHE:
        return _COMPLETION_STATE_CACHE[url]

    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        print(f"Warning: could not load completion state for {integration} from {url}: {exc}")
        data = {}

    if not isinstance(data, dict):
        print(f"Warning: completion_state_url did not return a JSON object: {url}")
        data = {}

    _COMPLETION_STATE_CACHE[url] = data
    return _COMPLETION_STATE_CACHE[url]

def is_paid_completed_novel(novel_title: str, integration: str = PRIMARY_DISCORD_INTEGRATION) -> bool:
    state = fetch_completion_state(integration)
    record = state.get(novel_title, {})

    if not isinstance(record, dict):
        return False

    return bool(record.get("paid_completion"))


def resolve_status_role_id(novel_title: str, integration: str = PRIMARY_DISCORD_INTEGRATION) -> str:
    roles = fetch_roles_json(integration)
    role_key = "complete" if is_paid_completed_novel(novel_title, integration) else "ongoing"
    return normalize_role_id(roles.get(role_key, ""))


def allowed_mentions_for_mention(mention: str):
    mention = str(mention or "")
    role_ids = role_ids_from_text(mention)
    user_ids = user_ids_from_text(mention)
    parse = ["everyone"] if "@everyone" in mention or "@here" in mention else []

    allowed = {"parse": parse}
    if role_ids:
        allowed["roles"] = role_ids
    if user_ids:
        allowed["users"] = user_ids

    return allowed


def resolve_global_mention(integration: str) -> str:
    # Preferred: target Discord repo config/server.json -> global_mention.
    mention = normalize_mention_value(get_integration_global_mention(integration))
    if mention:
        return mention

    # Fallback: target Discord repo config/roles.json -> global_mention/global.
    roles = fetch_roles_json(integration)
    return normalize_mention_value(roles.get("global_mention") or roles.get("global") or "")


def resolve_named_role_mention(integration: str, *keys: str) -> str:
    roles = fetch_roles_json(integration)

    for key in keys:
        mention = role_mention_from_id(roles.get(key, ""))
        if mention:
            return mention

    return ""


def resolve_event_role_mention(integration: str, event_type: str) -> str:
    if event_type == "membership_update":
        return resolve_named_role_mention(integration, "membership_update", "membership")

    if event_type == "special_announcement":
        return resolve_named_role_mention(integration, "special_announcement", "special")

    return resolve_named_role_mention(integration, event_type)


def build_global_mention(*, novel_title, novel, novel_role_mention, channel_id, guild_id, integration, event_type: str, private_channel_id=0):
    status_role_id = resolve_status_role_id(novel_title, integration)
    nsfw_role = resolve_named_role_mention(integration, "nsfw") if bool(novel.get("is_nsfw", False)) else ""

    mention_parts = [
        resolve_global_mention(integration),
        novel_role_mention,
        resolve_event_role_mention(integration, event_type),
        role_mention_from_id(status_role_id),
        nsfw_role,
    ]
    mention = " | ".join(part for part in mention_parts if part)

    if mention:
        return mention, allowed_mentions_for_mention(mention)

    return PUBLIC_GLOBAL_MENTION, allowed_mentions_for_mention(PUBLIC_GLOBAL_MENTION)

def build_membership_payload(*, host, novel_title, novel, banner_url, channel_id, guild_id, novel_role_mention, target_integration, private_channel_id=0, suppress_mentions=False):
    novel_url = novel.get("novel_url", "").strip()

    global_mention, allowed_mentions = build_global_mention(
        novel_title=novel_title,
        novel=novel,
        novel_role_mention=novel_role_mention,
        channel_id=channel_id,
        guild_id=guild_id,
        integration=target_integration,
        event_type="membership_update",
        private_channel_id=private_channel_id,
    )

    banner_spoiler = bool(novel.get("is_nsfw", False))

    ctx = {
        "host": host,
        "novel_title": novel_title,
        "novel_url": novel_url,
        "banner_url": banner_url,
        "banner_spoiler": banner_spoiler,
        "banner_not_spoiler": not banner_spoiler,
        "global_mention": global_mention,
    }

    payload = to_discord_api_payload(render_message("membership_update", ctx))

    # Mention is resolved from the target Discord integration's own server/roles/novel map.
    payload["allowed_mentions"] = {"parse": []} if suppress_mentions else allowed_mentions

    return payload


def post_message(channel_id: int, payload: dict, *, banner_file: Path | None = None):
    if banner_file:
        api_payload = dict(payload)
        api_payload["attachments"] = [
            {
                "id": 0,
                "filename": banner_file.name,
            }
        ]

        with banner_file.open("rb") as f:
            r = requests.post(
                f"{API_BASE}/channels/{channel_id}/messages",
                headers=discord_auth_headers(),
                data={"payload_json": json.dumps(api_payload, ensure_ascii=False)},
                files={"files[0]": (banner_file.name, f, "image/png")},
                timeout=30,
            )
    else:
        r = requests.post(
            f"{API_BASE}/channels/{channel_id}/messages",
            headers=discord_json_headers(),
            json=payload,
            timeout=20,
        )

    if r.status_code >= 400:
        print("Discord error response:")
        print(r.text)

    r.raise_for_status()
    return r.json()


def download_image(url: str) -> Image.Image:
    url = (url or "").strip()

    if not url:
        raise RuntimeError("No image URL was provided.")

    r = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    r.raise_for_status()

    image = Image.open(io.BytesIO(r.content))
    image.load()
    return ImageOps.exif_transpose(image)


def crop_to_ratio(image: Image.Image, ratio: float, crop_position: str = "upper") -> Image.Image:
    width, height = image.size

    if width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid image size: {width}x{height}")

    current_ratio = width / height

    if current_ratio > ratio:
        new_width = int(height * ratio)
        left = max((width - new_width) // 2, 0)
        return image.crop((left, 0, left + new_width, height))

    if current_ratio < ratio:
        new_height = int(width / ratio)
        excess = max(height - new_height, 0)

        vertical_positions = {
            "top": 0.00,
            "upper": 0.20,
            "upper center": 0.35,
            "center": 0.50,
            "lower center": 0.65,
            "lower": 0.80,
            "bottom": 1.00,
        }
        factor = vertical_positions.get((crop_position or "upper").strip().lower(), 0.25)
        top = int(round(excess * factor))
        top = max(0, min(top, excess))

        return image.crop((0, top, width, top + new_height))

    return image


def save_image_as_png(image: Image.Image, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)

    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA")

    image.save(path, "PNG", optimize=True)


def save_banner_preview_from_url(url: str, path: Path, *, crop: bool, crop_position: str = "upper"):
    image = download_image(url)

    if crop:
        image = crop_to_ratio(image, BANNER_RATIO, crop_position=crop_position)
        image = image.resize(BANNER_SIZE, Image.Resampling.LANCZOS)

    save_image_as_png(image, path)
    return path


def banner_preview_path_for_position(base_path: Path, crop_position: str) -> Path:
    safe_crop_position = crop_position.replace(" ", "_")
    return base_path.with_name(f"{base_path.stem}_{safe_crop_position}{base_path.suffix}")


def contact_sheet_path_for_banner(base_path: Path) -> Path:
    return base_path.with_name(f"{base_path.stem}_contact_sheet{base_path.suffix}")


def save_crop_preview_set_from_url(url: str, base_path: Path, *, selected_crop_position: str):
    """
    For crop preview mode, create:
    - membership_banner.png = the selected crop_position
    - membership_banner_top.png
    - membership_banner_upper.png
    - membership_banner_center.png
    - membership_banner_lower.png
    - membership_banner_bottom.png
    - membership_banner_contact_sheet.png
    """
    source_image = download_image(url)
    preview_images = []

    for crop_position in CROP_PREVIEW_POSITIONS:
        cropped = crop_to_ratio(source_image.copy(), BANNER_RATIO, crop_position=crop_position)
        cropped = cropped.resize(BANNER_SIZE, Image.Resampling.LANCZOS)

        position_path = banner_preview_path_for_position(base_path, crop_position)
        save_image_as_png(cropped, position_path)
        preview_images.append((crop_position, cropped.copy(), position_path))

        if crop_position == selected_crop_position:
            save_image_as_png(cropped, base_path)

    contact_sheet_path = contact_sheet_path_for_banner(base_path)
    save_contact_sheet(preview_images, contact_sheet_path)

    return [base_path] + [path for _, _, path in preview_images] + [contact_sheet_path]


def save_contact_sheet(preview_images, path: Path):
    label_height = 48
    sheet_width = BANNER_SIZE[0]
    sheet_height = (BANNER_SIZE[1] + label_height) * len(preview_images)

    sheet = Image.new("RGB", (sheet_width, sheet_height), "white")
    draw = ImageDraw.Draw(sheet)

    for index, (crop_position, image, _) in enumerate(preview_images):
        y = index * (BANNER_SIZE[1] + label_height)
        label = f"{crop_position.upper()} crop"
        draw.rectangle((0, y, sheet_width, y + label_height), fill=(240, 240, 240))
        draw.text((24, y + 16), label, fill=(0, 0, 0))
        sheet.paste(image.convert("RGB"), (0, y + label_height))

    save_image_as_png(sheet, path)
    return path


def prepare_banner_image(*, novel: dict, manual_banner_url: str, mode: str, crop_position: str):
    """
    Returns (banner_url_for_discord, optional_local_file, banner_source_label).

    - manual_banner_url filled: download it and upload it to Discord as an attachment,
      so the announcement does not depend on the external image URL staying alive.
    - manual_banner_url empty: use novel featured_image, crop it to 4:1 using crop_position,
      and send it to Discord as an attachment.
    - crop preview + banner_url empty: writes all crop positions plus a contact sheet.
    """
    manual_banner_url = (manual_banner_url or "").strip()

    if manual_banner_url:
        save_banner_preview_from_url(manual_banner_url, BANNER_OUTPUT_PATH, crop=False)
        return f"attachment://{BANNER_FILENAME}", BANNER_OUTPUT_PATH, "provided banner_url (downloaded and re-uploaded as Discord attachment)"

    featured_image = (novel.get("featured_image") or "").strip()

    if not featured_image:
        raise RuntimeError("banner_url was empty and this novel has no featured_image to auto-crop.")

    if mode == "crop preview":
        save_crop_preview_set_from_url(
            featured_image,
            BANNER_OUTPUT_PATH,
            selected_crop_position=crop_position,
        )
    else:
        save_banner_preview_from_url(featured_image, BANNER_OUTPUT_PATH, crop=True, crop_position=crop_position)

    return f"attachment://{BANNER_FILENAME}", BANNER_OUTPUT_PATH, f"auto-cropped featured_image ({crop_position})"


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


def route_for_event(target_cfg: dict, event_type: str) -> dict:
    routes = target_cfg.get("routes", {})

    if isinstance(routes, dict):
        route = routes.get(event_type) or routes.get("default")
        if isinstance(route, dict):
            return route

    route = target_cfg.get("route", {})
    return route if isinstance(route, dict) else {}


def resolve_host_discord_targets(host: str, short_code: str, event_type: str):
    host_key = host_config_key(host)
    target_cfg = get_host_discord_target(host_key)

    if not target_cfg:
        print(f"No host-specific Discord target configured for {host_key}. Posting only to primary Discord.")
        return []

    integration = str(target_cfg.get("integration") or "").strip()
    if not integration:
        print(f"Host-specific Discord target for {host_key} has no integration. Posting only to primary Discord.")
        return []

    route = route_for_event(target_cfg, event_type)
    route_type = str(route.get("type") or "thread_map").strip().lower()

    if route_type == "none":
        print(f"Host-specific Discord route for {host_key}/{event_type} is disabled.")
        return []

    if route_type == "channel":
        channel_id = str(route.get("channel_id") or "").strip()
        channel_key = str(route.get("channel_key") or "announcements").strip()

        if not channel_id:
            channel_id = get_integration_channel_id(integration, channel_key)

        if not channel_id:
            print(f"No channel target found for {host_key}/{event_type} in {integration}.")
            return []

        return [{
            "channel_id": int(channel_id),
            "integration": integration,
            "label": f"{host_key} {channel_key} channel",
            "private_channel_id": int(channel_id),
        }]

    if route_type == "thread_map":
        thread_id = resolve_forum_thread_id(integration, short_code, route)

        if thread_id is None:
            print(f"No thread target found for {short_code} in {integration}. Posting only to primary Discord.")
            return []

        thread_id = str(thread_id).strip()

        if not thread_id or thread_id.upper() == "N/A":
            print(f"{short_code} has no host-specific thread target. Posting only to primary Discord.")
            return []

        return [{
            "channel_id": int(thread_id),
            "integration": integration,
            "label": f"{host_key} thread",
            "private_channel_id": 0,
        }]

    print(f"Unknown host Discord route type {route_type!r} for {host_key}/{event_type}. Posting only to primary Discord.")
    return []


def resolve_publish_targets(host, hostdata, short_code):
    if not NEWS_CHANNEL_ID:
        raise RuntimeError("NEWS_CHANNEL_ID could not be resolved from env, server.json announcements, or template settings.")

    targets = [{
        "channel_id": NEWS_CHANNEL_ID,
        "integration": PRIMARY_DISCORD_INTEGRATION,
        "label": "primary announcements channel",
        "private_channel_id": NEWS_CHANNEL_ID,
    }]

    targets.extend(resolve_host_discord_targets(host, short_code, "membership_update"))
    return dedupe_targets(targets)

def usage():
    print("Usage: python tools/publish_membership_update.py <short_code> [banner_url] [mode] [crop_position]")
    print("Modes: crop preview, preview, publish")
    print("Crop positions: top, upper, upper center, center, lower center, lower, bottom")
    print("banner_url is optional. Leave it empty to auto-crop the novel featured_image to 4:1.")


def main():
    if len(sys.argv) < 2:
        usage()
        sys.exit(1)

    short_code = sys.argv[1].upper().strip()
    banner_url_arg = sys.argv[2].strip() if len(sys.argv) >= 3 else ""
    mode = sys.argv[3].strip().lower() if len(sys.argv) >= 4 else "publish"
    crop_position = sys.argv[4].strip().lower() if len(sys.argv) >= 5 else "upper center"

    if mode not in VALID_MODES:
        print(f"Error: unknown mode {mode!r}.")
        usage()
        sys.exit(1)

    if crop_position not in VALID_CROP_POSITIONS:
        print(f"Error: unknown crop_position {crop_position!r}.")
        usage()
        sys.exit(1)

    host, hostdata, novel_title, novel = find_novel_by_short_code(short_code)

    if not novel:
        print(f"Unknown short_code: {short_code}")
        sys.exit(1)

    banner_url, banner_file, banner_source = prepare_banner_image(
        novel=novel,
        manual_banner_url=banner_url_arg,
        mode=mode,
        crop_position=crop_position,
    )

    print(f"Membership update mode: {mode}")
    print(f"Crop position: {crop_position}")
    print(f"Novel: {novel_title}")
    print(f"Banner source: {banner_source}")

    if banner_file:
        print(f"Banner file: {banner_file}")

    if mode == "crop preview":
        print("Crop/image preview only. No Discord message sent and no TOML edited.")
        if banner_url_arg:
            print("Note: crop_position is ignored when banner_url is provided.")
            print("Manual banner_url preview creates one image only because it is treated as an already-made banner.")
        else:
            print("Created crop preview files:")
            for preview_path in sorted(BANNER_OUTPUT_PATH.parent.glob(f"{BANNER_OUTPUT_PATH.stem}*.png")):
                print(f"- {preview_path.name}")
        return

    require_discord_token()

    if banner_url_arg:
        print("Manual banner_url provided: it will be downloaded and re-uploaded to Discord as an attachment.")
    else:
        print("banner_url empty: using featured_image auto-crop.")

    if mode == "preview":
        if not PREVIEW_CHANNEL_ID:
            raise RuntimeError(
                "Preview channel could not be resolved. "
                "Check discord-webhook/config/server.json has channels.mod, "
                "or set MEMBERSHIP_PREVIEW_CHANNEL_ID / DISCORD_MOD_CHANNEL_ID."
            )

        targets = [{
            "channel_id": PREVIEW_CHANNEL_ID,
            "integration": PRIMARY_DISCORD_INTEGRATION,
            "label": "primary mod preview channel",
            "private_channel_id": PREVIEW_CHANNEL_ID,
        }]
        suppress_mentions = True
        print(f"Preview target: mod channel {PREVIEW_CHANNEL_ID}")

    else:
        targets = resolve_publish_targets(host, hostdata, short_code)
        suppress_mentions = False
        print(f"Publishing membership update for: {novel_title}")
        print("Targets:")
        for target in targets:
            print(f"- {target_label(target)} -> {target['channel_id']}")

    for target in targets:
        channel_id = int(target["channel_id"])
        target_integration = str(target.get("integration") or PRIMARY_DISCORD_INTEGRATION)
        private_channel_id = int(target.get("private_channel_id") or 0)
        channel_data = fetch_channel(channel_id)
        guild_id = channel_data.get("guild_id")
        target_novel_role_mention = resolve_novel_role_mention(short_code, target_integration)

        payload = build_membership_payload(
            host=host,
            novel_title=novel_title,
            novel=novel,
            banner_url=banner_url,
            channel_id=channel_id,
            guild_id=guild_id,
            novel_role_mention=target_novel_role_mention,
            target_integration=target_integration,
            private_channel_id=private_channel_id,
            suppress_mentions=suppress_mentions,
        )

        msg = post_message(channel_id, payload, banner_file=banner_file)
        print(f"Posted membership update to {target_label(target)} ({channel_id}): message {msg.get('id')}")

    if mode == "publish":
        mark_short_code_as_membership(short_code)
    else:
        print("Preview only. No TOML edited.")


if __name__ == "__main__":
    main()
