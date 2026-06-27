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
        get_completion_state_url,
        get_discord_webhook_channel_id,
        get_discord_webhook_guild_id,
        get_novel_discord_map_url,
        get_roles_json_url,
    )
except Exception:
    def get_completion_state_url(default: str = "") -> str:
        return default

    def get_discord_webhook_channel_id(key: str, default: str = "") -> str:
        return default

    def get_discord_webhook_guild_id(default: str = "") -> str:
        return default

    def get_novel_discord_map_url(default: str = "") -> str:
        return default

    def get_roles_json_url(default: str = "") -> str:
        return default

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()

API_BASE = "https://discord.com/api/v10"

_TEMPLATE_SETTINGS = load_template_settings("membership_update")

NOVEL_DISCORD_MAP_URL = (
    os.environ.get("NOVEL_DISCORD_MAP_URL", "").strip()
    or get_novel_discord_map_url()
    or setting_str(_TEMPLATE_SETTINGS, "novel_discord_map_url")
)
# currently only supports single server role attachment
# Reads role IDs from discord-webhook's rich novel Discord TOML map.

# Always post here first.
# This is your server's news channel.
NEWS_CHANNEL_ID = int(
    os.environ.get("NEWS_CHANNEL_ID", "").strip()
    or get_discord_webhook_channel_id("announcements")
    or setting_str(_TEMPLATE_SETTINGS, "news_channel_id", "0")
    or 0
)

# Preview mode posts to discord-webhook/config/server.json -> channels.mod.
# No channel ID is hardcoded here.
PREVIEW_CHANNEL_ID = int(
    os.environ.get("MEMBERSHIP_PREVIEW_CHANNEL_ID", "").strip()
    or os.environ.get("DISCORD_MOD_CHANNEL_ID", "").strip()
    or get_discord_webhook_channel_id("mod")
    or setting_str(_TEMPLATE_SETTINGS, "preview_channel_id", "0")
    or 0
)

# Private/news server uses novel role + status role.
# Status role comes from discord-webhook roles.json:
# complete if paid_completion exists in state.json, otherwise ongoing.
# Non-private servers get public_global_mention.
MY_SERVER_GUILD_ID = (
    os.environ.get("MY_SERVER_GUILD_ID", "").strip()
    or get_discord_webhook_guild_id()
    or setting_str(_TEMPLATE_SETTINGS, "private_guild_id")
)

ROLES_JSON_URL = (
    os.environ.get("ROLES_JSON_URL", "").strip()
    or get_roles_json_url()
    or setting_str(_TEMPLATE_SETTINGS, "roles_json_url")
)

COMPLETION_STATE_URL = (
    os.environ.get("COMPLETION_STATE_URL", "").strip()
    or get_completion_state_url()
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


def fetch_novel_role_id_map():
    """
    Fetches discord-webhook/config/novel_discord_map.toml
    and returns short_code -> raw novel role ID.
    """
    url = NOVEL_DISCORD_MAP_URL

    if not url:
        return {}

    if url in _NOVEL_ROLE_ID_MAP_CACHE:
        return _NOVEL_ROLE_ID_MAP_CACHE[url]

    r = requests.get(url, timeout=15)
    r.raise_for_status()

    data = tomllib.loads(r.text)

    if not isinstance(data, dict):
        raise RuntimeError(f"novel_discord_map_url did not return a TOML table: {url}")

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


def resolve_novel_role_mention(short_code):
    role_map = fetch_novel_role_id_map()
    role_id = role_map.get(short_code.upper())
    return f"<@&{role_id}>" if role_id else ""


_THREAD_ID_MAP_CACHE = {}


def fetch_thread_id_map(hostdata):
    """
    Fetches the host's thread_id_map_url from novel_mappings.py.

    Expected JSON format:
    {
      "TVITPA": "1444214902322368675",
      "TDLBKGC": "1438462596381413417",
      "BOE": "N/A"
    }
    """
    url = (hostdata.get("thread_id_map_url") or "").strip()

    if not url:
        return {}

    if url in _THREAD_ID_MAP_CACHE:
        return _THREAD_ID_MAP_CACHE[url]

    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()

    if not isinstance(data, dict):
        raise RuntimeError(f"thread_id_map_url did not return a JSON object: {url}")

    normalized = {
        str(k).upper(): str(v).strip()
        for k, v in data.items()
        if str(v).strip()
    }

    _THREAD_ID_MAP_CACHE[url] = normalized
    return normalized


def resolve_forum_thread_id(hostdata, short_code):
    """
    Gets the forum/thread ID for this novel from the host's thread_id_map_url.
    """
    thread_map = fetch_thread_id_map(hostdata)
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


_ROLES_JSON_CACHE = None
_COMPLETION_STATE_CACHE = None


def fetch_roles_json():
    global _ROLES_JSON_CACHE

    if _ROLES_JSON_CACHE is not None:
        return _ROLES_JSON_CACHE

    if not ROLES_JSON_URL:
        _ROLES_JSON_CACHE = {}
        return _ROLES_JSON_CACHE

    r = requests.get(ROLES_JSON_URL, timeout=15)
    r.raise_for_status()

    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"roles_json_url did not return a JSON object: {ROLES_JSON_URL}")

    _ROLES_JSON_CACHE = data
    return _ROLES_JSON_CACHE


def fetch_completion_state():
    global _COMPLETION_STATE_CACHE

    if _COMPLETION_STATE_CACHE is not None:
        return _COMPLETION_STATE_CACHE

    if not COMPLETION_STATE_URL:
        _COMPLETION_STATE_CACHE = {}
        return _COMPLETION_STATE_CACHE

    r = requests.get(COMPLETION_STATE_URL, timeout=15)
    r.raise_for_status()

    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"completion_state_url did not return a JSON object: {COMPLETION_STATE_URL}")

    _COMPLETION_STATE_CACHE = data
    return _COMPLETION_STATE_CACHE


def is_paid_completed_novel(novel_title: str) -> bool:
    state = fetch_completion_state()
    record = state.get(novel_title, {})

    if not isinstance(record, dict):
        return False

    return bool(record.get("paid_completion"))


def resolve_status_role_id(novel_title: str) -> str:
    roles = fetch_roles_json()
    role_key = "complete" if is_paid_completed_novel(novel_title) else "ongoing"
    return normalize_role_id(roles.get(role_key, ""))


def build_global_mention(*, novel_title, novel_role_mention, channel_id, guild_id):
    if int(channel_id) == NEWS_CHANNEL_ID or str(guild_id) == MY_SERVER_GUILD_ID:
        status_role_id = resolve_status_role_id(novel_title)

        mention_parts = [
            novel_role_mention,
            f"<@&{status_role_id}>" if status_role_id else "",
        ]
        mention = " | ".join(part for part in mention_parts if part)

        role_ids = role_ids_from_text(mention)

        return mention, {
            "parse": [],
            "roles": role_ids,
        }

    return PUBLIC_GLOBAL_MENTION, {
        "parse": ["everyone"],
    }


def build_membership_payload(*, host, novel_title, novel, banner_url, channel_id, guild_id, novel_role_mention, suppress_mentions=False):
    novel_url = novel.get("novel_url", "").strip()

    global_mention, allowed_mentions = build_global_mention(
        novel_title=novel_title,
        novel_role_mention=novel_role_mention,
        channel_id=channel_id,
        guild_id=guild_id,
    )

    ctx = {
        "host": host,
        "novel_title": novel_title,
        "novel_url": novel_url,
        "banner_url": banner_url,
        "global_mention": global_mention,
    }

    payload = to_discord_api_payload(render_message("membership_update", ctx))

    # Private/news server: novel role + ongoing/complete status role.
    # Public forum/thread: spoilered @everyone.
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


def resolve_publish_targets(hostdata, short_code):
    if not NEWS_CHANNEL_ID:
        raise RuntimeError("NEWS_CHANNEL_ID could not be resolved from env, server.json announcements, or template settings.")

    targets = [NEWS_CHANNEL_ID]

    thread_id = resolve_forum_thread_id(hostdata, short_code)

    if thread_id is None:
        print(f"ERROR: {short_code} is missing from the host's thread_id_map_url.")
        print('Add it to that host repo thread_id_map.json, or use "N/A" if it has no thread.')
        sys.exit(1)

    thread_id = str(thread_id).strip()

    if not thread_id:
        print(f"ERROR: {short_code} has an empty thread ID in the host's thread_id_map_url.")
        print('Use "N/A" if this novel should only post to your private/news server.')
        sys.exit(1)

    if thread_id.upper() == "N/A":
        print(f"{short_code} has no forum thread. Posting only to private/news server.")

    else:
        thread_id = int(thread_id)

        if thread_id not in targets:
            targets.append(thread_id)

    return targets


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

    novel_role_mention = resolve_novel_role_mention(short_code)

    if mode == "preview":
        if not PREVIEW_CHANNEL_ID:
            raise RuntimeError(
                "Preview channel could not be resolved. "
                "Check discord-webhook/config/server.json has channels.mod, "
                "or set MEMBERSHIP_PREVIEW_CHANNEL_ID / DISCORD_MOD_CHANNEL_ID."
            )

        targets = [PREVIEW_CHANNEL_ID]
        suppress_mentions = True
        print(f"Preview target: mod channel {PREVIEW_CHANNEL_ID}")

    else:
        targets = resolve_publish_targets(hostdata, short_code)
        suppress_mentions = False
        print(f"Publishing membership update for: {novel_title}")
        print(f"Targets: {targets}")

    for channel_id in targets:
        channel_data = fetch_channel(channel_id)
        guild_id = channel_data.get("guild_id")

        payload = build_membership_payload(
            host=host,
            novel_title=novel_title,
            novel=novel,
            banner_url=banner_url,
            channel_id=channel_id,
            guild_id=guild_id,
            novel_role_mention=novel_role_mention,
            suppress_mentions=suppress_mentions,
        )

        msg = post_message(channel_id, payload, banner_file=banner_file)
        print(f"Posted membership update to {channel_id}: message {msg.get('id')}")

    if mode == "publish":
        mark_short_code_as_membership(short_code)
    else:
        print("Preview only. No TOML edited.")


if __name__ == "__main__":
    main()
