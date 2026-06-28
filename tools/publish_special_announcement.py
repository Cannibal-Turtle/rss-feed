#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageOps

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from novel_mappings import HOSTING_SITE_DATA
from message_renderer import load_template_settings, render_message, render_text, to_discord_api_payload
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

_TEMPLATE_SETTINGS = load_template_settings("special_announcement")

NOVEL_DISCORD_MAP_URL = (
    os.environ.get("NOVEL_DISCORD_MAP_URL", "").strip()
    or get_integration_raw_url(PRIMARY_DISCORD_INTEGRATION, "novel_discord_map", "config/novel_discord_map.toml")
    or setting_str(_TEMPLATE_SETTINGS, "novel_discord_map_url")
)

NEWS_CHANNEL_ID = int(
    os.environ.get("NEWS_CHANNEL_ID", "").strip()
    or get_integration_channel_id(PRIMARY_DISCORD_INTEGRATION, "announcements")
    or setting_str(_TEMPLATE_SETTINGS, "news_channel_id", "0")
    or 0
)

PREVIEW_CHANNEL_ID = int(
    os.environ.get("SPECIAL_ANNOUNCEMENT_PREVIEW_CHANNEL_ID", "").strip()
    or os.environ.get("DISCORD_MOD_CHANNEL_ID", "").strip()
    or get_integration_channel_id(PRIMARY_DISCORD_INTEGRATION, "mod")
    or setting_str(_TEMPLATE_SETTINGS, "preview_channel_id", "0")
    or 0
)

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

PUBLIC_GLOBAL_MENTION = setting_str(
    _TEMPLATE_SETTINGS,
    "public_global_mention",
    "||@everyone||",
    env="PUBLIC_GLOBAL_MENTION",
)

BANNER_OUTPUT_PATH = Path(
    os.environ.get("SPECIAL_ANNOUNCEMENT_BANNER_OUTPUT", "special_announcement_banner.png")
).resolve()
BANNER_FILENAME = BANNER_OUTPUT_PATH.name
BANNER_SIZE = (1600, 400)
BANNER_RATIO = BANNER_SIZE[0] / BANNER_SIZE[1]
VALID_MODES = {"crop preview", "preview", "publish"}
VALID_CROP_POSITIONS = {"top", "upper", "upper center", "center", "lower center", "lower", "bottom"}
CROP_PREVIEW_POSITIONS = ["top", "upper", "upper center", "center", "lower center", "lower", "bottom"]


def host_config_key(host: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(host or "").strip().casefold()).strip("_")


def dedupe_targets(targets: list[dict]) -> list[dict]:
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


def target_label(target: dict) -> str:
    label = str(target.get("label") or "").strip()
    integration = str(target.get("integration") or "").strip()
    channel_id = str(target.get("channel_id") or "").strip()
    return label or f"{integration}:{channel_id}"


# ---------------- Discord helpers ----------------

def require_discord_token() -> None:
    if not TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN is required for preview/publish mode.")


def discord_json_headers() -> dict[str, str]:
    require_discord_token()
    return {
        "Authorization": f"Bot {TOKEN}",
        "Content-Type": "application/json",
    }


def discord_auth_headers() -> dict[str, str]:
    require_discord_token()
    return {"Authorization": f"Bot {TOKEN}"}


def fetch_channel(channel_id: int) -> dict:
    """Used to detect which server the channel/thread belongs to."""
    try:
        r = requests.get(
            f"{API_BASE}/channels/{channel_id}",
            headers=discord_json_headers(),
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        print(f"Warning: could not fetch channel {channel_id}: {exc}")
        return {}


def post_message(channel_id: int, payload: dict, *, banner_file: Path | None = None) -> dict:
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


# ---------------- Novel / role helpers ----------------

_NOVEL_ROLE_ID_MAP_CACHE: dict[str, dict[str, str]] = {}
_ROLES_JSON_CACHE: dict[str, dict] = {}
_COMPLETION_STATE_CACHE: dict[str, dict] = {}
_THREAD_ID_MAP_CACHE: dict[str, dict[str, str]] = {}


def normalize_role_id(value) -> str:
    match = re.search(r"\d{5,}", str(value or ""))
    return match.group(0) if match else ""


def role_ids_from_text(text: str) -> list[str]:
    return re.findall(r"<@&(\d+)>", text or "")


def user_ids_from_text(text: str) -> list[str]:
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


def novel_discord_map_url_for_integration(integration: str) -> str:
    if integration == PRIMARY_DISCORD_INTEGRATION:
        return NOVEL_DISCORD_MAP_URL

    return get_integration_raw_url(integration, "novel_discord_map")


def fetch_novel_role_id_map(integration: str = PRIMARY_DISCORD_INTEGRATION) -> dict[str, str]:
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

def resolve_novel_role_mention(short_code: str, integration: str = PRIMARY_DISCORD_INTEGRATION) -> str:
    role_id = fetch_novel_role_id_map(integration).get(short_code.upper())
    return f"<@&{role_id}>" if role_id else ""


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
    return isinstance(record, dict) and bool(record.get("paid_completion"))


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

def fetch_thread_id_map(
    integration: str,
    map_key: str = "thread_id_map",
    default_path: str = "config/thread_id_map.json",
) -> dict[str, str]:
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

    normalized = {str(k).upper(): str(v).strip() for k, v in data.items() if str(v).strip()}
    _THREAD_ID_MAP_CACHE[url] = normalized
    return normalized


def resolve_forum_thread_id(integration: str, short_code: str, route: dict) -> str | None:
    map_key = str(route.get("map_key") or "thread_id_map").strip()
    default_path = str(route.get("default_path") or "config/thread_id_map.json").strip()
    return fetch_thread_id_map(integration, map_key, default_path).get(short_code.upper())

def find_novel_by_short_code(short_code: str):
    short_code = short_code.upper().strip()

    for host, hostdata in HOSTING_SITE_DATA.items():
        for novel_title, novel in hostdata.get("novels", {}).items():
            if (novel.get("short_code", "") or "").upper() == short_code:
                return host, hostdata, novel_title, novel

    return None, None, None, None


def route_for_event(target_cfg: dict, event_type: str) -> dict:
    routes = target_cfg.get("routes", {})

    if isinstance(routes, dict):
        route = routes.get(event_type) or routes.get("default")
        if isinstance(route, dict):
            return route

    route = target_cfg.get("route", {})
    return route if isinstance(route, dict) else {}


def resolve_host_discord_targets(host: str, short_code: str, event_type: str) -> list[dict]:
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


def resolve_publish_targets(host: str, hostdata: dict, short_code: str) -> list[dict]:
    if not NEWS_CHANNEL_ID:
        raise RuntimeError("NEWS_CHANNEL_ID could not be resolved from env, server.json announcements, or template settings.")

    targets = [{
        "channel_id": NEWS_CHANNEL_ID,
        "integration": PRIMARY_DISCORD_INTEGRATION,
        "label": "primary announcements channel",
        "private_channel_id": NEWS_CHANNEL_ID,
    }]

    targets.extend(resolve_host_discord_targets(host, short_code, "special_announcement"))
    return dedupe_targets(targets)


# ---------------- Banner helpers ----------------

def download_image(url: str) -> Image.Image:
    url = (url or "").strip()

    if not url:
        raise RuntimeError("No image URL was provided.")

    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()

    image = Image.open(io.BytesIO(r.content))
    image.load()
    return ImageOps.exif_transpose(image)


def crop_to_ratio(image: Image.Image, ratio: float, crop_position: str = "upper center") -> Image.Image:
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
        factor = vertical_positions.get((crop_position or "upper center").strip().lower(), 0.35)
        top = int(round(excess * factor))
        top = max(0, min(top, excess))
        return image.crop((0, top, width, top + new_height))

    return image


def save_image_as_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA")

    image.save(path, "PNG", optimize=True)


def save_banner_preview_from_url(url: str, path: Path, *, crop: bool, crop_position: str = "upper center") -> Path:
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


def save_contact_sheet(preview_images, path: Path) -> Path:
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


def save_crop_preview_set_from_url(url: str, base_path: Path, *, selected_crop_position: str) -> list[Path]:
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


def prepare_banner_image(*, novel: dict, manual_banner_url: str, mode: str, crop_position: str):
    manual_banner_url = (manual_banner_url or "").strip()

    if manual_banner_url:
        # Treat manual URLs as finished banners. Download and re-upload as an attachment.
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


# ---------------- Payload helpers ----------------

def template_text_setting(key: str, default: str = "") -> str:
    """Read editable announcement text from message_templates/special_announcement.toml [settings]."""
    value = _TEMPLATE_SETTINGS.get(key, default)
    if value is None:
        value = default
    return str(value).strip()


def discord_timestamp_now() -> str:
    fmt = setting_str(_TEMPLATE_SETTINGS, "time_format", "f") or "f"
    fmt = re.sub(r"[^tTdDfFR]", "", fmt) or "f"
    return f"<t:{int(time.time())}:{fmt}>"


def build_special_payload(
    *,
    host: str,
    hostdata: dict,
    novel_title: str,
    novel: dict,
    banner_url: str,
    channel_id: int,
    guild_id: str | None,
    novel_role_mention: str,
    target_integration: str,
    private_channel_id: int,
    announcement_title: str,
    announcement_message: str,
    button_label: str,
    button_url: str,
    suppress_mentions: bool = False,
) -> dict:
    global_mention, allowed_mentions = build_global_mention(
        novel_title=novel_title,
        novel=novel,
        novel_role_mention=novel_role_mention,
        channel_id=channel_id,
        guild_id=guild_id,
        integration=target_integration,
        event_type="special_announcement",
        private_channel_id=private_channel_id,
    )

    ctx = {
        "accent_color": setting_str(_TEMPLATE_SETTINGS, "accent_color") or novel.get("discord_color") or hostdata.get("discord_color") or "#C9D3FF",
        "announcement_title": announcement_title,
        "announcement_message": announcement_message,
        "banner_url": banner_url,
        "button_label": button_label,
        "button_url": button_url or novel.get("novel_url", ""),
        "discord_time": discord_timestamp_now(),
        "global_mention": global_mention,
        "host": host,
        "host_emoji": hostdata.get("host_emoji", ""),
        "novel_title": novel_title,
        "novel_url": novel.get("novel_url", ""),
        "short_code": (novel.get("short_code") or "").upper(),
    }

    # Let editable [settings] text use the same placeholders as the template.
    # Example: announcement_message can contain {novel_title} or {novel_url}.
    for key in ("announcement_title", "announcement_message", "button_label", "button_url"):
        ctx[key] = render_text(ctx.get(key, ""), ctx)

    payload = to_discord_api_payload(render_message("special_announcement", ctx))
    payload["allowed_mentions"] = {"parse": []} if suppress_mentions else allowed_mentions
    return payload


def parse_args():
    if len(sys.argv) < 2:
        usage()
        sys.exit(1)

    short_code = sys.argv[1].upper().strip()
    banner_url = sys.argv[2].strip() if len(sys.argv) >= 3 else ""
    mode = sys.argv[3].strip().lower() if len(sys.argv) >= 4 else "publish"
    crop_position = sys.argv[4].strip().lower() if len(sys.argv) >= 5 else "upper center"

    return short_code, banner_url, mode, crop_position


def usage():
    print("Usage: python tools/publish_special_announcement.py <short_code> [banner_url] [mode] [crop_position]")
    print("Modes: crop preview, preview, publish")
    print("Crop positions: top, upper, upper center, center, lower center, lower, bottom")
    print("banner_url is optional. Leave it empty to auto-crop the novel featured_image to 4:1.")
    print("Edit message_templates/special_announcement.toml to change title, body, button label, or button URL.")


def main() -> None:
    short_code, manual_banner_url, mode, crop_position = parse_args()

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

    announcement_title = template_text_setting("announcement_title", "Special Chapter Announcement")
    announcement_message = template_text_setting("announcement_message")
    button_label = template_text_setting("button_label", "READ HERE")
    button_url = template_text_setting("button_url") or novel.get("novel_url", "")

    if mode != "crop preview" and not announcement_message:
        raise RuntimeError("Announcement message is required for preview/publish mode.")

    if mode != "crop preview" and not button_url:
        raise RuntimeError("Button URL is empty and this novel has no novel_url fallback.")

    banner_url, banner_file, banner_source = prepare_banner_image(
        novel=novel,
        manual_banner_url=manual_banner_url,
        mode=mode,
        crop_position=crop_position,
    )

    print(f"Special announcement mode: {mode}")
    print(f"Crop position: {crop_position}")
    print(f"Novel: {novel_title}")
    print(f"Title: {announcement_title}")
    print(f"Button: {button_label} -> {button_url}")
    print(f"Banner source: {banner_source}")

    if banner_file:
        print(f"Banner file: {banner_file}")

    if mode == "crop preview":
        print("Crop/image preview only. No Discord message sent.")
        if manual_banner_url:
            print("Note: crop_position is ignored when banner_url is provided.")
            print("Manual banner_url preview creates one image only because it is treated as an already-made banner.")
        else:
            print("Created crop preview files:")
            for preview_path in sorted(BANNER_OUTPUT_PATH.parent.glob(f"{BANNER_OUTPUT_PATH.stem}*.png")):
                print(f"- {preview_path.name}")
        return

    require_discord_token()

    if mode == "preview":
        if not PREVIEW_CHANNEL_ID:
            raise RuntimeError(
                "Preview channel could not be resolved. "
                "Check discord-webhook/config/server.json has channels.mod, "
                "or set SPECIAL_ANNOUNCEMENT_PREVIEW_CHANNEL_ID / DISCORD_MOD_CHANNEL_ID."
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
        print(f"Publishing special announcement for: {novel_title}")
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

        payload = build_special_payload(
            host=host,
            hostdata=hostdata,
            novel_title=novel_title,
            novel=novel,
            banner_url=banner_url,
            channel_id=channel_id,
            guild_id=guild_id,
            novel_role_mention=target_novel_role_mention,
            target_integration=target_integration,
            private_channel_id=private_channel_id,
            announcement_title=announcement_title,
            announcement_message=announcement_message,
            button_label=button_label,
            button_url=button_url,
            suppress_mentions=suppress_mentions,
        )

        msg = post_message(channel_id, payload, banner_file=banner_file)
        print(f"Posted special announcement to {target_label(target)} ({channel_id}): message {msg.get('id')}")

    if mode == "preview":
        print("Preview only. Nothing committed or edited.")


if __name__ == "__main__":
    main()
