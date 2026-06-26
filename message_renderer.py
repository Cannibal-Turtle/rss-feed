# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 and below
    import tomli as tomllib  # type: ignore

try:
    import discord
    from discord import Embed
    from discord.ui import Button, View
except Exception:
    # This lets requests-only scripts import the renderer without discord.py installed.
    discord = None
    Embed = None
    Button = None
    View = None

ROOT = Path(__file__).resolve().parent
TEMPLATE_DIR = ROOT / "message_templates"
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_\.]*)\}")

# These empty values are meaningful and must not be dropped.
KEEP_EMPTY_KEYS = {
    "parse",
    "users",
    "roles",
    "allowed_mentions",
    "components",
    "items",
}


# ---------------------------------------------------------------------------
# TOML loading
# ---------------------------------------------------------------------------

def load_toml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path

    if not path.exists():
        raise FileNotFoundError(f"TOML template not found: {path}")

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"TOML template must be a table/object: {path}")
    return data


def load_template_settings(name: str) -> dict[str, Any]:
    """Load the optional [settings] table from message_templates/{name}.toml.

    These settings are for script/user config that belongs beside the template
    but should not be sent to Discord as part of the message payload.
    """
    path = TEMPLATE_DIR / f"{name}.toml"
    data = load_toml(path)
    settings = data.get("settings", {})

    if settings in (None, ""):
        return {}
    if not isinstance(settings, dict):
        raise RuntimeError(f"[settings] in {path} must be a table/object")

    return copy.deepcopy(settings)


def load_template(name: str, *, variant: str | None = None) -> dict[str, Any]:
    """
    Load message_templates/{name}.toml.

    Use variant for templates like:

        [expiring]
        content = "..."

        [invalid]
        content = "..."

    Then call:
        render_message("token_alert", ctx, variant="expiring")

    A top-level [settings] table is reserved for script/user config and is
    removed from normal payload rendering. Read it with load_template_settings().
    """
    path = TEMPLATE_DIR / f"{name}.toml"
    data = load_toml(path)

    if variant:
        if variant not in data:
            raise RuntimeError(f"Missing [{variant}] in {path}")
        if not isinstance(data[variant], dict):
            raise RuntimeError(f"[{variant}] in {path} must be a table/object")
        return copy.deepcopy(data[variant])

    data = copy.deepcopy(data)
    data.pop("settings", None)
    return data


# ---------------------------------------------------------------------------
# Placeholder rendering
# ---------------------------------------------------------------------------

def get_path(ctx: dict[str, Any], key: str, default: Any = "") -> Any:
    """Supports {title} and nested placeholders like {novel.url}."""
    cur: Any = ctx

    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]

    return cur


def is_truthy(ctx: dict[str, Any], key: str | None) -> bool:
    """
    Used by TOML conditions:

        when = "banner_url"
        icon_url_when = "host_logo"
    """
    if not key:
        return True
    return bool(get_path(ctx, key, ""))


def render_text(value: Any, ctx: dict[str, Any]) -> Any:
    """Replace {placeholders}. Unknown placeholders become empty strings."""
    if not isinstance(value, str):
        return value

    def repl(match: re.Match[str]) -> str:
        replacement = get_path(ctx, match.group(1), "")
        return "" if replacement is None else str(replacement)

    return PLACEHOLDER_RE.sub(repl, value)


def parse_color(value: Any) -> int | None:
    """
    Accepts:
      13227007
      "13227007"
      "C9D3FF"
      "#C9D3FF"
      "0xC9D3FF"

    Returns a Discord color integer.
    """
    if value is None or value == "":
        return None

    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value

    text = str(value).strip()
    if not text:
        return None

    if text.startswith("#"):
        return int(text[1:], 16)

    if text.lower().startswith("0x"):
        return int(text[2:], 16)

    # Hex colors normally contain A-F. Pure digits are treated as decimal ints.
    if re.fullmatch(r"[0-9A-Fa-f]{6}", text) and re.search(r"[A-Fa-f]", text):
        return int(text, 16)

    if re.fullmatch(r"\d+", text):
        return int(text, 10)

    # Last fallback: allow non-6-length hex if someone writes it intentionally.
    if re.fullmatch(r"[0-9A-Fa-f]+", text):
        return int(text, 16)

    raise ValueError(f"Invalid Discord color value: {value!r}")


def should_drop(key: str, value: Any) -> bool:
    if key in KEEP_EMPTY_KEYS:
        return False
    return value in (None, "", {}, [])


def render_obj(obj: Any, ctx: dict[str, Any]) -> Any:
    """Recursively render strings/lists/dicts from TOML."""
    if isinstance(obj, str):
        return render_text(obj, ctx)

    if isinstance(obj, list):
        out = []
        for item in obj:
            rendered = render_obj(item, ctx)
            if rendered not in (None, "", {}, []):
                out.append(rendered)
        return out

    if isinstance(obj, dict):
        # Object-level conditional:
        #   when = "some_ctx_key"
        if not is_truthy(ctx, obj.get("when")):
            return None

        out: dict[str, Any] = {}

        for key, value in obj.items():
            if key == "when" or key.endswith("_when"):
                continue

            # Field-level conditional:
            #   icon_url_when = "host_logo"
            condition_key = obj.get(f"{key}_when")
            if condition_key and not is_truthy(ctx, condition_key):
                continue

            rendered = render_obj(value, ctx)

            if key == "color" or key == "accent_color":
                rendered = parse_color(rendered)

            if should_drop(key, rendered):
                continue

            out[key] = rendered

        return out

    return obj


def _postprocess_payload(payload: dict[str, Any]) -> dict[str, Any]:
    # Do not strip content newlines here. Discord message spacing should be
    # controlled exactly by the TOML template.

    # suppress_embeds is easier to read/write in TOML than flags = 4.
    if payload.pop("suppress_embeds", False):
        payload["flags"] = int(payload.get("flags", 0)) | 4

    return payload


def render_message(name: str, ctx: dict[str, Any], *, variant: str | None = None) -> dict[str, Any]:
    """
    Render one TOML template into a generic Discord payload dict.

    This does not force discord.py or raw API shape yet. After this, call either:
      - to_discord_api_payload(payload) for requests.post(..., json=payload)
      - to_discord_py_kwargs(payload) for await channel.send(**kwargs)
    """
    template = load_template(name, variant=variant)
    payload = render_obj(template, ctx) or {}

    if not isinstance(payload, dict):
        raise RuntimeError(f"Rendered template {name!r} must be a dict payload")

    return _postprocess_payload(payload)


def render_message_sequence(name: str, ctx: dict[str, Any], *, variant: str | None = None) -> list[dict[str, Any]]:
    """
    For templates shaped like:

        [[messages]]
        content = "..."

        [[messages]]
        content = "..."
    """
    template = load_template(name, variant=variant)
    messages = template.get("messages", [])

    rendered_messages: list[dict[str, Any]] = []
    for message in messages:
        rendered = render_obj(message, ctx)
        if not rendered or not isinstance(rendered, dict):
            continue
        rendered_messages.append(_postprocess_payload(rendered))

    return rendered_messages

# ---------------------------------------------------------------------------
# Hide mentions in template control
# ---------------------------------------------------------------------------

def truthy(value) -> bool:
    if isinstance(value, bool):
        return value

    return str(value or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def format_role_mention(role_id: str, *, hidden: bool = False) -> str:
    role_id = str(role_id or "").strip()

    if not role_id:
        return ""

    mention = f"<@&{role_id}>"
    return f"||{mention}||" if hidden else mention


# ---------------------------------------------------------------------------
# Emoji / button helpers
# ---------------------------------------------------------------------------

def parse_custom_emoji(value: Any) -> Any:
    """Return discord.py PartialEmoji for <:name:id>, or unicode/plain emoji string."""
    if value is None:
        return None

    s = str(value).strip()
    if not s:
        return None

    m = re.match(r"^<(?P<animated>a?):(?P<name>[A-Za-z0-9_]+):(?P<id>\d+)>", s)
    if m and discord is not None:
        return discord.PartialEmoji(
            name=m.group("name"),
            id=int(m.group("id")),
            animated=bool(m.group("animated")),
        )

    return s


def api_emoji(value: Any) -> dict[str, Any] | None:
    """Return Discord API emoji object for buttons/components."""
    if value is None:
        return None

    if isinstance(value, dict):
        out = {k: v for k, v in value.items() if v not in (None, "")}
        if "id" in out:
            out["id"] = str(out["id"])
        return out or None

    s = str(value).strip()
    if not s:
        return None

    m = re.match(r"^<(?P<animated>a?):(?P<name>[A-Za-z0-9_]+):(?P<id>\d+)>", s)
    if m:
        return {
            "name": m.group("name"),
            "id": m.group("id"),
            "animated": bool(m.group("animated")),
        }

    return {"name": s}


def button_style_value(style: Any) -> int:
    """Map readable TOML button styles to Discord API style numbers."""
    if isinstance(style, int):
        return style

    s = str(style or "link").strip().lower()
    return {
        "primary": 1,
        "secondary": 2,
        "success": 3,
        "danger": 4,
        "link": 5,
    }.get(s, 5)


# ---------------------------------------------------------------------------
# discord.py conversion
# ---------------------------------------------------------------------------

def build_embed(data: dict[str, Any]) -> Any:
    """Convert a rendered embed dict into discord.Embed."""
    if Embed is None:
        raise RuntimeError("discord.py is not available, cannot build discord.Embed")

    data = dict(data)
    color = data.pop("color", None)

    embed = Embed(
        title=data.pop("title", None),
        url=data.pop("url", None),
        description=data.pop("description", None),
        color=color,
    )

    timestamp = data.pop("timestamp", None)
    if timestamp:
        try:
            from dateutil import parser as dateparser
            embed.timestamp = dateparser.parse(str(timestamp))
        except Exception:
            pass

    author = data.pop("author", None)
    if isinstance(author, dict) and author.get("name"):
        embed.set_author(**author)

    thumbnail = data.pop("thumbnail", None)
    if isinstance(thumbnail, dict) and thumbnail.get("url"):
        embed.set_thumbnail(url=thumbnail["url"])

    image = data.pop("image", None)
    if isinstance(image, dict) and image.get("url"):
        embed.set_image(url=image["url"])

    footer = data.pop("footer", None)
    if isinstance(footer, dict) and (footer.get("text") or footer.get("icon_url")):
        embed.set_footer(**footer)

    for field in data.pop("fields", []) or []:
        if not isinstance(field, dict):
            continue
        embed.add_field(
            name=field.get("name") or "\u200b",
            value=field.get("value") or "\u200b",
            inline=bool(field.get("inline", False)),
        )

    return embed


def build_view(components: Any) -> Any:
    """Convert friendly classic button TOML into a discord.ui.View."""
    if not components:
        return None
    if View is None or Button is None:
        raise RuntimeError("discord.py is not available, cannot build discord.ui.View")

    # Expected friendly classic TOML shape:
    # [components]
    # [[components.action_rows]]
    # [[components.action_rows.buttons]]
    rows = []
    if isinstance(components, dict):
        rows = components.get("action_rows") or []
    elif isinstance(components, list):
        rows = components

    view = View()

    for row in rows:
        if not isinstance(row, dict):
            continue

        # Raw Discord action row support: {type=1, components=[...]}
        buttons = row.get("buttons") or row.get("components") or []

        for button in buttons:
            if not isinstance(button, dict):
                continue

            style = button_style_value(button.get("style", "link"))

            # For your current scripts, link buttons are the only generic/safe button.
            # Non-link buttons need callbacks, so they are skipped in discord.py mode.
            if style != 5:
                continue

            kwargs = {
                "label": button.get("label") or None,
                "url": button.get("url") or None,
            }

            emoji = parse_custom_emoji(button.get("emoji"))
            if emoji:
                kwargs["emoji"] = emoji

            if kwargs["url"]:
                view.add_item(Button(**kwargs))

    return view if view.children else None


def build_allowed_mentions(allowed_mentions: Any) -> Any:
    """Convert rendered allowed_mentions dict into discord.AllowedMentions."""
    if discord is None:
        raise RuntimeError("discord.py is not available, cannot build AllowedMentions")

    if not isinstance(allowed_mentions, dict):
        return None

    parse = set(allowed_mentions.get("parse") or [])

    if "users" in parse:
        users_value: bool | list[Any] = True
    else:
        users = [str(x).strip() for x in allowed_mentions.get("users", []) if str(x).strip()]
        users_value = [discord.Object(id=int(x)) for x in users] if users else False

    if "roles" in parse:
        roles_value: bool | list[Any] = True
    else:
        roles = [str(x).strip() for x in allowed_mentions.get("roles", []) if str(x).strip()]
        roles_value = [discord.Object(id=int(x)) for x in roles] if roles else False

    return discord.AllowedMentions(
        everyone=("everyone" in parse),
        users=users_value,
        roles=roles_value,
        replied_user=bool(allowed_mentions.get("replied_user", False)),
    )


def to_discord_py_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Convert rendered payload into kwargs for discord.py:

        await channel_or_thread.send(**to_discord_py_kwargs(payload))

    This is for classic content/embed/link-button messages.
    Do not use this for Components v2 messages. Components v2 should use raw API.
    """
    mode = str(payload.get("mode", "classic") or "classic").strip().lower()
    if mode == "components_v2":
        raise RuntimeError("Components v2 payloads must be sent with raw Discord API, not discord.py kwargs")

    kwargs: dict[str, Any] = {}

    if payload.get("content") not in (None, ""):
        kwargs["content"] = payload["content"]

    embeds_data = payload.get("embeds") or []
    embeds = [build_embed(e) for e in embeds_data if isinstance(e, dict)]

    if len(embeds) == 1:
        kwargs["embed"] = embeds[0]
    elif len(embeds) > 1:
        kwargs["embeds"] = embeds

    view = build_view(payload.get("components"))
    if view:
        kwargs["view"] = view

    allowed_mentions = build_allowed_mentions(payload.get("allowed_mentions"))
    if allowed_mentions is not None:
        kwargs["allowed_mentions"] = allowed_mentions

    if int(payload.get("flags", 0)) & 4:
        kwargs["suppress_embeds"] = True

    return kwargs


# ---------------------------------------------------------------------------
# Raw Discord API conversion
# ---------------------------------------------------------------------------

def looks_like_raw_discord_components(components: Any) -> bool:
    return (
        isinstance(components, list)
        and all(isinstance(item, dict) and "type" in item for item in components)
    )


def api_components(components: Any) -> list[dict[str, Any]] | None:
    """
    Convert friendly classic button TOML into raw Discord API components.

    This is for old/classic action rows and buttons.
    Components v2 should not be converted. Use mode = "components_v2" instead.
    """
    if not components:
        return None

    # Already raw Discord action rows, like:
    # [{"type": 1, "components": [{"type": 2, ...}]}]
    if looks_like_raw_discord_components(components):
        return components

    rows = []
    if isinstance(components, dict):
        rows = components.get("action_rows") or []
    elif isinstance(components, list):
        rows = components

    api_rows: list[dict[str, Any]] = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        api_buttons: list[dict[str, Any]] = []
        for button in row.get("buttons", []) or row.get("components", []) or []:
            if not isinstance(button, dict):
                continue

            style = button_style_value(button.get("style", "link"))
            b: dict[str, Any] = {
                "type": 2,
                "style": style,
            }

            if button.get("label"):
                b["label"] = button["label"]

            emoji = api_emoji(button.get("emoji"))
            if emoji:
                b["emoji"] = emoji

            if style == 5:
                if not button.get("url"):
                    continue
                b["url"] = button["url"]
            else:
                b["custom_id"] = button.get("custom_id") or button.get("id") or "template_button"

            if "disabled" in button:
                b["disabled"] = bool(button["disabled"])

            api_buttons.append(b)

        if api_buttons:
            api_rows.append({"type": 1, "components": api_buttons})

    return api_rows or None


def to_discord_api_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Convert rendered payload into raw Discord API JSON.

    Use this for scripts that post with requests/aiohttp:

        payload = to_discord_api_payload(render_message(...))
        requests.post(url, headers=headers, json=payload)

    Supports both:
      - classic content/embed/button payloads
      - Components v2 payloads with mode = "components_v2"
    """
    out = copy.deepcopy(payload)
    mode = str(out.pop("mode", "classic") or "classic").strip().lower()

    if mode == "components_v2":
        # Discord Components v2 requires IS_COMPONENTS_V2 flag.
        # Important: do NOT run api_components() here. V2 containers/sections/media
        # must pass through exactly as the TOML rendered them.
        out["flags"] = int(out.get("flags", 0)) | 32768
    else:
        components = api_components(out.pop("components", None))
        if components:
            out["components"] = components

    allowed = {
        "content",
        "embeds",
        "components",
        "allowed_mentions",
        "flags",
        "tts",
        "message_reference",
    }

    return {
        k: v
        for k, v in out.items()
        if k in allowed and v not in (None, "")
    }
