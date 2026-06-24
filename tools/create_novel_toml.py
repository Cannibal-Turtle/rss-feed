#!/usr/bin/env python3
"""
Create a new mappings/novels/<short_code>.toml from a configured host API.

Currently implemented host adapter:
- Mistmint Haven: uses mappings/hosts/mistmint_haven.toml novels_api_url

Designed for GitHub Actions workflow_dispatch inputs, but also works locally:

  python tools/create_novel_toml.py \
    --host "Mistmint Haven" \
    --title "She's Shy" \
    --short-code SS \
    --chapter-count "80 Chapters" \
    --last-chapter "Chapter 80" \
    --discord-color "#c90016" \
    --special-tag "quick transmigration" \
    --has-arcs false
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
HOSTS_DIR = ROOT / "mappings" / "hosts"
NOVELS_DIR = ROOT / "mappings" / "novels"

DEFAULT_TAG_ROLES_URL = (
    "https://raw.githubusercontent.com/Cannibal-Turtle/discord-webhook/"
    "main/config/tag_roles.json"
)

# Fallback if GitHub/raw URL is unavailable. Keep keys only; role IDs are not needed here.
FALLBACK_SUPPORTED_TAGS = {
    "chinese": "",
    "korean": "",
    "japanese": "",
    "quick transmigration": "",
    "infinite flow": "",
    "transmigration": "",
    "reincarnation": "",
    "regression": "",
    "wuxia/xianxia": "",
    "historical": "",
    "modern": "",
    "school life": "",
    "sci-fi": "",
    "romance": "",
    "bl": "",
    "np": "",
    "harem": "",
    "smut": "",
    "comedy": "",
    "horror": "",
    "supernatural": "",
    "angst": "",
    "slice of life": "",
}

TAG_PRIORITY = list(FALLBACK_SUPPORTED_TAGS.keys())

DIRECT_GENRE_ALIASES = {
    "comedy": "comedy",
    "harem": "harem",
    "historical": "historical",
    "horror": "horror",
    "modern": "modern",
    "reincarnation": "reincarnation",
    "romance": "romance",
    "school life": "school life",
    "sci-fi": "sci-fi",
    "shounen ai": "bl",
    "slice of life": "slice of life",
    "smut": "smut",
    "supernatural": "supernatural",
    "tragedy": "angst",
    "wuxia": "wuxia/xianxia",
    "xianxia": "wuxia/xianxia",
    "yaoi": "bl",
}

LANGUAGE_TAGS = {
    "chinese": "chinese",
    "korean": "korean",
    "japanese": "japanese",
}


class ScriptError(RuntimeError):
    pass


def eprint(*parts: object) -> None:
    print(*parts, file=sys.stderr)


def str_clean(value: Any) -> str:
    return str(value or "").strip()


def norm_key(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.casefold().strip()
    return re.sub(r"\s+", " ", value)


def yes_no(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    s = str(value).strip().casefold()
    if not s:
        return default
    if s in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise ScriptError(f"Expected yes/no true/false value, got: {value!r}")


def load_toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def quote_toml(value: Any) -> str:
    return json.dumps(str(value or ""), ensure_ascii=False)


def multiline_toml(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    # Keep existing repo style: custom_description = """..."""
    text = text.replace('"""', '\\"\\"\\"')
    return f'"""\n{text}\n"""'


def toml_bool(value: bool) -> str:
    return "true" if bool(value) else "false"


def set_query_param(url: str, **params: Any) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for k, v in params.items():
        query[k] = str(v)
    return urlunparse(parsed._replace(query=urlencode(query)))


def load_host_configs() -> dict[str, dict[str, Any]]:
    if not HOSTS_DIR.exists():
        raise ScriptError(f"Missing host config directory: {HOSTS_DIR}")

    hosts: dict[str, dict[str, Any]] = {}
    for path in sorted(HOSTS_DIR.glob("*.toml")):
        data = load_toml(path)
        name = str_clean(data.get("name") or data.get("host"))
        if not name:
            raise ScriptError(f"Missing host name in {path}")
        data["_path"] = path
        hosts[name] = data
    return hosts


def get_host_config(host_input: str) -> tuple[str, dict[str, Any]]:
    hosts = load_host_configs()
    wanted = norm_key(host_input)
    for name, cfg in hosts.items():
        if norm_key(name) == wanted:
            return name, cfg

    known = ", ".join(sorted(hosts))
    raise ScriptError(f"Unknown host {host_input!r}. Known hosts: {known}")


def resolve_auth_headers(host_cfg: dict[str, Any]) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36",
    }

    token_secret = str_clean(host_cfg.get("token_secret"))
    cookie = os.getenv("MISTMINT_COOKIE", "").strip()
    if not cookie and token_secret:
        cookie = os.getenv(token_secret, "").strip()

    bearer = os.getenv("MISTMINT_TOKEN", "").strip()

    if cookie:
        headers["Cookie"] = cookie
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    return headers


def fetch_json(url: str, headers: dict[str, str]) -> Any:
    r = requests.get(url, headers=headers, timeout=30)
    text = r.text or ""

    try:
        payload = r.json()
    except Exception:
        payload = None

    if r.status_code in (401, 403):
        raise ScriptError("AUTH_ERROR: host API rejected auth. Your cookie/token may be missing or expired.")

    if r.status_code // 100 != 2:
        raise ScriptError(f"HTTP {r.status_code} from host API: {text[:500]}")

    if payload is None:
        raise ScriptError(f"Host API returned non-JSON response: {text[:500]}")

    return payload


def fetch_mistmint_my_novels(host_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    raw_url = str_clean(host_cfg.get("novels_api_url"))
    if not raw_url:
        raise ScriptError("This host config has no novels_api_url.")

    headers = resolve_auth_headers(host_cfg)
    if not headers.get("Cookie") and not headers.get("Authorization"):
        token_secret = str_clean(host_cfg.get("token_secret")) or "MISTMINT_COOKIE"
        raise ScriptError(f"Missing Mistmint auth. Set {token_secret} or MISTMINT_TOKEN.")

    first_url = set_query_param(raw_url, skipPage=0, limit=100)
    payload = fetch_json(first_url, headers)

    data = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(data, list):
        raise ScriptError("Mistmint my-novels response does not have data: list.")

    novels = [x for x in data if isinstance(x, dict)]

    paging = payload.get("paging", {}) if isinstance(payload, dict) else {}
    total_pages = 1
    if isinstance(paging, dict):
        try:
            total_pages = int(paging.get("totalPages") or 1)
        except Exception:
            total_pages = 1

    for skip_page in range(1, max(total_pages, 1)):
        page_url = set_query_param(raw_url, skipPage=skip_page, limit=100)
        page_payload = fetch_json(page_url, headers)
        page_data = page_payload.get("data", []) if isinstance(page_payload, dict) else []
        if isinstance(page_data, list):
            novels.extend(x for x in page_data if isinstance(x, dict))

    return novels


def fetch_api_novels(host_name: str, host_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    # Adapter point for future hosts.
    if norm_key(host_name) == "mistmint haven":
        return fetch_mistmint_my_novels(host_cfg)
    raise ScriptError(
        f"Host {host_name!r} is configured, but create_novel_toml.py does not have a fetch adapter for it yet."
    )


def mistmint_slug_from_title(title: str) -> str:
    # Only used for matching fallback. Mistmint's actual slug comes from API.
    title = unicodedata.normalize("NFKD", title or "")
    title = re.sub(r"[’'`´]", "-", title)
    title = re.sub(r"[^A-Za-z0-9]+", "-", title)
    return re.sub(r"-+", "-", title).strip("-").casefold()


def novelupdates_slug_from_title(title: str) -> str:
    """
    NovelUpdates usually removes apostrophes instead of turning them into hyphens:
      She's Shy -> shes-shy
      Female Lead's Older Brother -> female-leads-older-brother
    """
    s = unicodedata.normalize("NFKD", title or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("&", " and ")
    s = re.sub(r"[’'`´]", "", s)
    s = re.sub(r"[^A-Za-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-").casefold()
    return s


def find_api_novel(novels: list[dict[str, Any]], title_input: str) -> dict[str, Any]:
    wanted_title = norm_key(title_input)
    wanted_nuish_slug = novelupdates_slug_from_title(title_input)
    wanted_mistmintish_slug = mistmint_slug_from_title(title_input)

    matches: list[dict[str, Any]] = []
    for novel in novels:
        api_title = str_clean(novel.get("title"))
        api_slug = str_clean(novel.get("slug")).casefold()
        if norm_key(api_title) == wanted_title:
            matches.append(novel)
            continue
        if api_slug and api_slug in {wanted_nuish_slug, wanted_mistmintish_slug}:
            matches.append(novel)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        titles = "\n".join(f"- {str_clean(x.get('title'))} ({str_clean(x.get('slug'))})" for x in matches)
        raise ScriptError(f"More than one API novel matched {title_input!r}:\n{titles}")

    # Helpful suggestions for typo / partial title.
    suggestions: list[str] = []
    for novel in novels:
        api_title = str_clean(novel.get("title"))
        if wanted_title and wanted_title in norm_key(api_title):
            suggestions.append(api_title)
        if len(suggestions) >= 10:
            break

    msg = f"Could not find novel title in host API: {title_input!r}"
    if suggestions:
        msg += "\nPossible matches:\n" + "\n".join(f"- {s}" for s in suggestions)
    raise ScriptError(msg)


def build_novel_url(host_name: str, api_novel: dict[str, Any]) -> str:
    slug = str_clean(api_novel.get("slug"))
    if not slug:
        return ""
    if norm_key(host_name) == "mistmint haven":
        return f"https://www.mistminthaven.com/novels/{slug}"
    return ""


def decode_possible_escaped_url(url: str) -> str:
    url = html.unescape(url or "")
    url = url.replace(r"\/", "/")
    try:
        url = bytes(url, "utf-8").decode("unicode_escape")
    except Exception:
        pass
    return url.strip()


def extract_og_image_from_html(page_html: str) -> str:
    text = page_html or ""

    # Real HTML meta tag path.
    meta_patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
    ]
    for pat in meta_patterns:
        m = re.search(pat, text, flags=re.I | re.S)
        if m:
            return decode_possible_escaped_url(m.group(1))

    # Next.js inline JSON / escaped RSC payload path.
    jsonish_patterns = [
        r'property\\?"\s*:\s*\\?"og:image\\?".*?content\\?"\s*:\s*\\?"(https?:.*?)(?<!\\)\\?"',
        r'name\\?"\s*:\s*\\?"twitter:image\\?".*?content\\?"\s*:\s*\\?"(https?:.*?)(?<!\\)\\?"',
    ]
    for pat in jsonish_patterns:
        m = re.search(pat, text, flags=re.I | re.S)
        if m:
            return decode_possible_escaped_url(m.group(1))

    return ""


def fetch_featured_image(novel_url: str, api_novel: dict[str, Any]) -> str:
    if novel_url:
        try:
            r = requests.get(
                novel_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                },
                timeout=30,
            )
            if r.ok:
                og_image = extract_og_image_from_html(r.text)
                if og_image:
                    return og_image
            else:
                eprint(f"Warning: novel page returned HTTP {r.status_code}; falling back to avatarUrl.")
        except Exception as exc:
            eprint(f"Warning: could not fetch novel page OG image: {exc}; falling back to avatarUrl.")

    return str_clean(api_novel.get("avatarUrl"))


def parse_iso_date_to_dmy(value: str) -> str:
    s = str_clean(value)
    if not s:
        return ""
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        d = dt.datetime.fromisoformat(s)
        return f"{d.day}/{d.month}/{d.year}"
    except Exception:
        return ""


def load_supported_tags(tag_roles_url: str) -> dict[str, str]:
    if not tag_roles_url:
        return dict(FALLBACK_SUPPORTED_TAGS)

    try:
        r = requests.get(tag_roles_url, timeout=20)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            return {norm_key(k): str(v) for k, v in data.items()}
    except Exception as exc:
        eprint(f"Warning: could not fetch tag roles from {tag_roles_url}: {exc}")

    return dict(FALLBACK_SUPPORTED_TAGS)


SPECIAL_TAG_CHOICES = {"", "quick transmigration", "infinite flow"}


def normalize_special_tag(value: str) -> str:
    """Optional world-hopping tag stored separately from normal tags."""
    tag = norm_key(value)
    aliases = {
        "qt": "quick transmigration",
        "quick-transmigration": "quick transmigration",
        "quick transmigration": "quick transmigration",
        "quick transmigration / world-hopping": "quick transmigration",
        "infinite-flow": "infinite flow",
        "infinite flow": "infinite flow",
        "if": "infinite flow",
    }
    tag = aliases.get(tag, tag)
    if tag not in SPECIAL_TAG_CHOICES:
        allowed = ", ".join(repr(x) for x in sorted(SPECIAL_TAG_CHOICES) if x) or "blank"
        raise ScriptError(f"Unknown special_tag {value!r}. Use blank, {allowed}.")
    return tag


def apply_special_tag(tags: list[str], special_tag: str) -> list[str]:
    """
    If a world-hopping special tag is explicitly chosen, keep it out of normal tags
    and remove plain transmigration so messages do not double-tag the novel.
    """
    if not special_tag:
        return tags
    blocked = {"transmigration", "quick transmigration", "infinite flow"}
    return [tag for tag in tags if norm_key(tag) not in blocked]


def infer_tags(api_novel: dict[str, Any], supported_tags: dict[str, str]) -> tuple[list[str], list[str]]:
    found: list[str] = []
    unmapped: list[str] = []

    def add(tag: str) -> None:
        tag = norm_key(tag)
        if tag and tag in supported_tags and tag not in found:
            found.append(tag)

    language = norm_key(str_clean(api_novel.get("nativeLanguage")))
    if language in LANGUAGE_TAGS:
        add(LANGUAGE_TAGS[language])

    genres = api_novel.get("genres") or []
    if isinstance(genres, list):
        for item in genres:
            if isinstance(item, dict):
                raw = str_clean(item.get("name"))
            else:
                raw = str_clean(item)
            key = norm_key(raw)
            if not key:
                continue

            if key == "transmigration":
                add("transmigration")
                continue

            mapped = DIRECT_GENRE_ALIASES.get(key)
            if mapped:
                add(mapped)
                continue

            if key in supported_tags:
                add(key)
                continue

            unmapped.append(raw)

    # Stable, neat order based on your Discord tag role config.
    priority = [tag for tag in TAG_PRIORITY if tag in supported_tags]
    priority_index = {tag: i for i, tag in enumerate(priority)}
    ordered = sorted(found, key=lambda tag: priority_index.get(tag, 999))
    return ordered, unmapped


def existing_mapping_paths() -> list[Path]:
    return sorted(NOVELS_DIR.glob("*.toml")) if NOVELS_DIR.exists() else []


def assert_not_duplicate(api_novel: dict[str, Any], short_code: str, target_path: Path, *, overwrite: bool) -> None:
    api_id = str_clean(api_novel.get("id")).casefold()
    api_slug = str_clean(api_novel.get("slug")).casefold()
    api_title = norm_key(str_clean(api_novel.get("title")))
    code = str_clean(short_code).casefold()

    for path in existing_mapping_paths():
        if overwrite and path.resolve() == target_path.resolve():
            continue
        data = load_toml(path)
        existing_code = str_clean(data.get("short_code")).casefold()
        existing_id = str_clean(data.get("novel_id")).casefold()
        existing_title = norm_key(str_clean(data.get("title")))
        existing_slug = str_clean(data.get("novel_url")).rstrip("/").split("/")[-1].casefold()

        reasons = []
        if existing_code and existing_code == code:
            reasons.append(f"short_code={short_code}")
        if api_id and existing_id == api_id:
            reasons.append(f"novel_id={api_id}")
        if api_slug and existing_slug == api_slug:
            reasons.append(f"slug={api_slug}")
        if api_title and existing_title == api_title:
            reasons.append("title")

        if reasons:
            raise ScriptError(
                f"Refusing to create duplicate mapping. {path.relative_to(ROOT)} already matches "
                + ", ".join(reasons)
                + ". Use --overwrite only if you intentionally want to replace the target file."
            )

    if target_path.exists() and not overwrite:
        raise ScriptError(f"Target file already exists: {target_path.relative_to(ROOT)}. Use --overwrite to replace it.")


def build_toml_text(
    *,
    host_name: str,
    api_novel: dict[str, Any],
    short_code: str,
    novelupdates_url: str,
    novel_url: str,
    featured_image: str,
    chapter_count: str,
    last_chapter: str,
    discord_color: str,
    tags: list[str],
    special_tag: str,
    history_file: str,
) -> str:
    title = str_clean(api_novel.get("title"))
    description = str_clean(api_novel.get("description"))

    lines: list[str] = []
    lines.append(f"host = {quote_toml(host_name)}")
    lines.append(f"title = {quote_toml(title)}")
    lines.append(f"short_code = {quote_toml(short_code.upper())}")
    lines.append("")
    lines.append(f"novelupdates_url = {quote_toml(novelupdates_url)}")
    lines.append(f"novel_url = {quote_toml(novel_url)}")
    lines.append(f"featured_image = {quote_toml(featured_image)}")
    lines.append(f"novel_id = {quote_toml(str_clean(api_novel.get('id')))}")
    lines.append("")
    lines.append(f"chapter_count = {quote_toml(chapter_count)}")
    lines.append(f"last_chapter = {quote_toml(last_chapter)}")
    lines.append(f"start_date = {quote_toml(parse_iso_date_to_dmy(str_clean(api_novel.get('createdAt'))))}")
    lines.append("has_free = true")
    lines.append("has_paid = true")
    lines.append(f"is_nsfw = {toml_bool(bool(api_novel.get('isMature', False)))}")
    lines.append("is_membership = false")
    lines.append("")
    lines.append(f"discord_color = {quote_toml(discord_color)}")
    lines.append("")
    tag_items = ", ".join(quote_toml(tag) for tag in tags)
    lines.append(f"tags = [{tag_items}]")
    lines.append(f"special_tag = {quote_toml(special_tag)}")
    lines.append(f"history_file = {quote_toml(history_file)}")
    lines.append("")
    lines.append(f"custom_description = {multiline_toml(description)}")
    lines.append("")
    return "\n".join(lines)


def write_history_file(history_file: str, *, dry_run: bool) -> Path | None:
    if not history_file:
        return None

    path = ROOT / history_file
    if dry_run:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("{}\n", encoding="utf-8")
    return path


def positive_code(value: str) -> str:
    code = str_clean(value).upper()
    if not code:
        raise ScriptError("short_code is required.")
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]*", code):
        raise ScriptError("short_code should use letters/numbers/underscore/hyphen only, e.g. AMLWC.")
    return code


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Create a new mappings/novels/<short_code>.toml from host API data.")
    p.add_argument("--host", required=True, help="Hosting site, e.g. Mistmint Haven")
    p.add_argument("--title", required=True, help="Novel title to find in the host API")
    p.add_argument("--short-code", required=True, help="Stable short code, e.g. AMLWC")
    p.add_argument("--chapter-count", default="", help='Optional display text, e.g. "93 Chapters"')
    p.add_argument("--last-chapter", default="", help='Optional target text, e.g. "Chapter 93"')
    p.add_argument("--discord-color", default="", help='Optional hex color, e.g. "#c90016"')
    p.add_argument(
        "--special-tag",
        default="",
        help='Optional world-hopping tag: "quick transmigration" or "infinite flow". Removes normal transmigration tag if set.',
    )
    p.add_argument("--has-arcs", default="false", help="true/false. If true, create arc_history/<short_code>_history.json")
    p.add_argument("--tag-roles-url", default=DEFAULT_TAG_ROLES_URL, help="Raw JSON URL for Discord tag role keys")
    p.add_argument("--dry-run", action="store_true", help="Print TOML but do not write files")
    p.add_argument("--overwrite", action="store_true", help="Allow replacing mappings/novels/<short_code>.toml")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    host_name, host_cfg = get_host_config(args.host)
    short_code = positive_code(args.short_code)
    target_path = NOVELS_DIR / f"{short_code.casefold()}.toml"

    api_novels = fetch_api_novels(host_name, host_cfg)
    api_novel = find_api_novel(api_novels, args.title)

    assert_not_duplicate(api_novel, short_code, target_path, overwrite=args.overwrite)

    novel_url = build_novel_url(host_name, api_novel)
    featured_image = fetch_featured_image(novel_url, api_novel)

    nu_slug = novelupdates_slug_from_title(str_clean(api_novel.get("title")))
    novelupdates_url = f"https://www.novelupdates.com/series/{nu_slug}" if nu_slug else ""

    supported_tags = load_supported_tags(args.tag_roles_url)
    tags, unmapped = infer_tags(api_novel, supported_tags)
    special_tag = normalize_special_tag(args.special_tag)
    tags = apply_special_tag(tags, special_tag)

    has_arcs = yes_no(args.has_arcs, default=False)
    history_file = f"arc_history/{short_code.casefold()}_history.json" if has_arcs else ""

    toml_text = build_toml_text(
        host_name=host_name,
        api_novel=api_novel,
        short_code=short_code,
        novelupdates_url=novelupdates_url,
        novel_url=novel_url,
        featured_image=featured_image,
        chapter_count=args.chapter_count,
        last_chapter=args.last_chapter,
        discord_color=args.discord_color,
        tags=tags,
        special_tag=special_tag,
        history_file=history_file,
    )

    if unmapped:
        eprint("Unmapped host genres skipped:", ", ".join(dict.fromkeys(unmapped)))

    if args.dry_run:
        print(toml_text)
        if history_file:
            print(f"# Would create {history_file}")
        return 0

    NOVELS_DIR.mkdir(parents=True, exist_ok=True)
    target_path.write_text(toml_text, encoding="utf-8")
    history_path = write_history_file(history_file, dry_run=False)

    print(f"Created {target_path.relative_to(ROOT)}")
    if history_path:
        print(f"Created/kept {history_path.relative_to(ROOT)}")
    print(f"NovelUpdates URL guess: {novelupdates_url}")
    print(f"Tags: {tags}")
    print(f"Special tag: {special_tag!r}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except ScriptError as exc:
        eprint(f"❌ {exc}")
        raise SystemExit(1)
