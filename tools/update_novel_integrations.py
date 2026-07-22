#!/usr/bin/env python3
"""Update novel-specific config in related Discord repositories.

The target repositories and paths are derived from config/integrations.json:

- personal/default Discord role map:
    primary_discord.integration -> paths.novel_discord_map
- selected host Discord role map (when that host has one):
    host_discord_targets.<host>.integration -> paths.novel_discord_map
- selected host per-novel destination:
    host_discord_targets.<host>.routes.forum_post

Repository owner/name/branch are parsed from each integration's existing
raw.githubusercontent.com raw_base. No second repository registry is needed.
"""

from __future__ import annotations

import argparse
import base64
import difflib
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import requests

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
INTEGRATIONS_PATH = ROOT / "config" / "integrations.json"
GITHUB_API = "https://api.github.com"


class ScriptError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitHubFileTarget:
    integration: str
    owner: str
    repo: str
    branch: str
    path: str

    @property
    def repo_full_name(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def label(self) -> str:
        return f"{self.repo_full_name}:{self.branch}/{self.path}"


@dataclass
class PendingUpdate:
    target: GitHubFileTarget
    original_text: str
    updated_text: str
    sha: str
    message: str


def clean(value: Any) -> str:
    return str(value or "").strip()


def normalize_config_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", clean(value)).casefold()
    text = text.replace("&", " and ")
    text = "".join(ch if ch.isalnum() else "_" for ch in text)
    return "_".join(part for part in text.split("_") if part)


def positive_code(value: Any) -> str:
    code = clean(value).upper()
    if not code:
        raise ScriptError("short_code is required.")
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]*", code):
        raise ScriptError("short_code should use letters/numbers/underscore/hyphen only, e.g. AMLWC.")
    return code


def load_integrations() -> dict[str, Any]:
    try:
        data = json.loads(INTEGRATIONS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ScriptError(f"Missing integrations config: {INTEGRATIONS_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise ScriptError(f"Invalid JSON in {INTEGRATIONS_PATH}: {exc}") from exc
    if not isinstance(data, dict):
        raise ScriptError(f"Expected an object in {INTEGRATIONS_PATH}.")
    return data


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def parse_raw_github_base(raw_base: str) -> tuple[str, str, str]:
    """Return owner, repo, branch from a raw.githubusercontent.com base URL."""
    parsed = urlparse(clean(raw_base).rstrip("/"))
    if parsed.scheme != "https" or parsed.netloc.casefold() != "raw.githubusercontent.com":
        raise ScriptError(
            "Writable integrations must use a raw GitHub base URL in the form "
            "https://raw.githubusercontent.com/<owner>/<repo>/<branch>."
        )

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 3:
        raise ScriptError(f"Incomplete raw GitHub base URL: {raw_base!r}")

    owner, repo = parts[0], parts[1]
    branch = "/".join(parts[2:])
    return owner, repo, branch


def resolve_file_target(
    config: dict[str, Any],
    integration_name: str,
    path_key: str,
    *,
    default_path: str = "",
) -> GitHubFileTarget:
    integration_name = clean(integration_name)
    if not integration_name:
        raise ScriptError("Integration name is missing from config/integrations.json.")

    integration = as_dict(config.get(integration_name))
    if not integration:
        raise ScriptError(f"Unknown integration {integration_name!r} in config/integrations.json.")

    raw_base = clean(integration.get("raw_base"))
    if not raw_base:
        raise ScriptError(f"Integration {integration_name!r} has no raw_base.")

    paths = as_dict(integration.get("paths"))
    path = clean(paths.get(path_key) or default_path).lstrip("/")
    if not path:
        raise ScriptError(
            f"Integration {integration_name!r} has no paths.{path_key} and no default path was configured."
        )

    owner, repo, branch = parse_raw_github_base(raw_base)
    return GitHubFileTarget(
        integration=integration_name,
        owner=owner,
        repo=repo,
        branch=branch,
        path=path,
    )


def github_headers(token: str = "") -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "rss-feed-novel-onboarding",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def contents_api_url(target: GitHubFileTarget) -> str:
    encoded_path = quote(target.path, safe="/")
    return f"{GITHUB_API}/repos/{target.owner}/{target.repo}/contents/{encoded_path}"


def fetch_remote_file(target: GitHubFileTarget, token: str) -> tuple[str, str]:
    url = f"{contents_api_url(target)}?{urlencode({'ref': target.branch})}"
    response = requests.get(url, headers=github_headers(token), timeout=30)

    if response.status_code == 404:
        raise ScriptError(f"Remote config file not found: {target.label}")
    if response.status_code in {401, 403}:
        raise ScriptError(
            f"GitHub denied access to {target.label}. Check that PAT_GITHUB can read and write this repository."
        )
    if not response.ok:
        raise ScriptError(f"GitHub GET failed for {target.label}: HTTP {response.status_code}: {response.text[:500]}")

    payload = response.json()
    if not isinstance(payload, dict) or payload.get("type") != "file":
        raise ScriptError(f"GitHub path is not a file: {target.label}")

    encoded = clean(payload.get("content")).replace("\n", "")
    sha = clean(payload.get("sha"))
    if not encoded or not sha:
        raise ScriptError(f"GitHub returned incomplete file data for {target.label}.")

    try:
        raw = base64.b64decode(encoded, validate=True)
        text = raw.decode("utf-8")
    except Exception as exc:
        raise ScriptError(f"Could not decode UTF-8 content from {target.label}: {exc}") from exc

    return text, sha


def commit_remote_file(update: PendingUpdate, token: str) -> None:
    if not token:
        raise ScriptError("PAT_GITHUB is required to write downstream repositories.")

    payload = {
        "message": update.message,
        "content": base64.b64encode(update.updated_text.encode("utf-8")).decode("ascii"),
        "sha": update.sha,
        "branch": update.target.branch,
        "committer": {
            "name": "github-actions[bot]",
            "email": "41898282+github-actions[bot]@users.noreply.github.com",
        },
    }
    response = requests.put(
        contents_api_url(update.target),
        headers=github_headers(token),
        json=payload,
        timeout=30,
    )

    if response.status_code in {401, 403}:
        raise ScriptError(
            f"GitHub denied the write to {update.target.label}. "
            "Check PAT_GITHUB Contents: read and write access."
        )
    if response.status_code == 409:
        raise ScriptError(
            f"GitHub reported a conflict while writing {update.target.label}. "
            "Rerun the workflow so it fetches the newest file SHA."
        )
    if not response.ok:
        raise ScriptError(
            f"GitHub PUT failed for {update.target.label}: HTTP {response.status_code}: {response.text[:500]}"
        )


def validate_role_inputs(role_id: str, custom_emoji: str, role_url: str, *, label: str) -> bool:
    supplied = bool(role_id or custom_emoji or role_url)
    if not supplied:
        return False
    if not role_id or not custom_emoji:
        raise ScriptError(f"{label}: role_id and custom_emoji must be supplied together. role_url is optional.")
    return True


def latest_role_url(toml_text: str) -> str:
    try:
        data = tomllib.loads(toml_text)
    except Exception as exc:
        raise ScriptError(f"Could not parse remote novel_discord_map TOML: {exc}") from exc

    latest = ""
    for value in data.values():
        if isinstance(value, dict):
            candidate = clean(value.get("role_url"))
            if candidate:
                latest = candidate
    return latest


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def role_section_text(short_code: str, role_id: str, custom_emoji: str, role_url: str) -> str:
    return (
        f"[{short_code}]\n"
        f"role_id = {toml_string(role_id)}\n"
        f"custom_emoji = {toml_string(custom_emoji)}\n"
        f"role_url = {toml_string(role_url)}\n"
    )


def update_novel_discord_toml(
    original: str,
    *,
    short_code: str,
    role_id: str,
    custom_emoji: str,
    role_url: str,
    overwrite: bool,
) -> str:
    try:
        data = tomllib.loads(original)
    except Exception as exc:
        raise ScriptError(f"Could not parse remote novel_discord_map TOML: {exc}") from exc

    resolved_url = clean(role_url) or latest_role_url(original)
    if not resolved_url:
        raise ScriptError(
            "role_url was blank and the target novel_discord_map has no earlier non-empty role_url to inherit."
        )

    new_values = {
        "role_id": role_id,
        "custom_emoji": custom_emoji,
        "role_url": resolved_url,
    }
    existing = data.get(short_code)
    if isinstance(existing, dict):
        existing_values = {key: clean(existing.get(key)) for key in new_values}
        if existing_values == new_values:
            return original
        if not overwrite:
            raise ScriptError(
                f"[{short_code}] already exists in novel_discord_map with different values. "
                "Enable overwrite only if replacing it is intentional."
            )

        table_pattern = re.compile(
            rf"(?ms)^\[{re.escape(short_code)}\][ \t]*\r?\n.*?(?=^\[[^\r\n]+\][ \t]*\r?\n|\Z)"
        )
        replacement = role_section_text(short_code, role_id, custom_emoji, resolved_url)
        updated, count = table_pattern.subn(replacement, original, count=1)
        if count != 1:
            raise ScriptError(f"Could not locate the [{short_code}] section for replacement.")
        return updated.rstrip() + "\n"

    suffix = "" if not original.strip() else "\n\n"
    return original.rstrip() + suffix + role_section_text(short_code, role_id, custom_emoji, resolved_url)


def update_id_map_json(original: str, *, short_code: str, destination_id: str, overwrite: bool) -> str:
    try:
        data = json.loads(original)
    except json.JSONDecodeError as exc:
        raise ScriptError(f"Could not parse remote destination map JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ScriptError("Remote destination map JSON must contain an object.")

    existing = clean(data.get(short_code))
    if existing:
        if existing == destination_id:
            return original
        if not overwrite:
            raise ScriptError(
                f"{short_code} already exists in the host destination map with ID {existing}. "
                "Enable overwrite only if replacing it is intentional."
            )

    data[short_code] = destination_id
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def unified_diff(label: str, original: str, updated: str) -> str:
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{label}",
            tofile=f"b/{label}",
        )
    )


def merge_pending_update(pending: dict[tuple[str, str, str, str], PendingUpdate], update: PendingUpdate) -> None:
    key = (
        update.target.owner,
        update.target.repo,
        update.target.branch,
        update.target.path,
    )
    previous = pending.get(key)
    if previous is None:
        pending[key] = update
        return

    # This can occur when primary_discord and the selected host intentionally
    # point to the same integration/file. Apply the second transformation to
    # the first update rather than committing the same file twice.
    if previous.updated_text != update.original_text:
        update.original_text = previous.original_text
    previous.updated_text = update.updated_text
    previous.message = update.message


def prepare_role_update(
    *,
    pending: dict[tuple[str, str, str, str], PendingUpdate],
    config: dict[str, Any],
    token: str,
    integration_name: str,
    short_code: str,
    role_id: str,
    custom_emoji: str,
    role_url: str,
    overwrite: bool,
    label: str,
) -> None:
    target = resolve_file_target(config, integration_name, "novel_discord_map")
    key = (target.owner, target.repo, target.branch, target.path)
    previous = pending.get(key)
    if previous:
        original, sha = previous.updated_text, previous.sha
    else:
        original, sha = fetch_remote_file(target, token)

    updated = update_novel_discord_toml(
        original,
        short_code=short_code,
        role_id=role_id,
        custom_emoji=custom_emoji,
        role_url=role_url,
        overwrite=overwrite,
    )
    merge_pending_update(
        pending,
        PendingUpdate(
            target=target,
            original_text=previous.original_text if previous else original,
            updated_text=updated,
            sha=sha,
            message=f"config: add {short_code} novel Discord mapping",
        ),
    )
    print(f"Prepared {label}: {target.label}")


def find_host_target(config: dict[str, Any], host: str) -> tuple[str, dict[str, Any]]:
    host_targets = as_dict(config.get("host_discord_targets"))
    host_key = normalize_config_key(host)
    target = as_dict(host_targets.get(host_key))
    return host_key, target


def prepare_host_destination_update(
    *,
    pending: dict[tuple[str, str, str, str], PendingUpdate],
    config: dict[str, Any],
    token: str,
    host: str,
    short_code: str,
    destination_id: str,
    overwrite: bool,
) -> None:
    host_key, host_target = find_host_target(config, host)
    if not host_target:
        raise ScriptError(
            f"Host destination ID was supplied, but host_discord_targets has no entry for {host_key!r}."
        )

    integration_name = clean(host_target.get("integration"))
    routes = as_dict(host_target.get("routes"))
    route = as_dict(routes.get("forum_post"))
    if not route:
        raise ScriptError(
            f"Host {host!r} has no host_discord_targets.{host_key}.routes.forum_post route."
        )

    route_type = normalize_config_key(route.get("type"))
    if route_type == "channel":
        raise ScriptError(
            f"Host {host!r} uses a shared channel for forum_post, so host_destination_id should be left blank."
        )
    if route_type not in {"thread_map", "channel_map"}:
        raise ScriptError(
            f"Host {host!r} forum_post route type {route.get('type')!r} is not a supported per-novel ID map."
        )

    map_key = clean(route.get("map_key"))
    default_path = clean(route.get("default_path"))
    if not map_key:
        raise ScriptError(f"Host {host!r} forum_post route has no map_key.")

    target = resolve_file_target(config, integration_name, map_key, default_path=default_path)
    key = (target.owner, target.repo, target.branch, target.path)
    previous = pending.get(key)
    if previous:
        original, sha = previous.updated_text, previous.sha
    else:
        original, sha = fetch_remote_file(target, token)

    updated = update_id_map_json(
        original,
        short_code=short_code,
        destination_id=destination_id,
        overwrite=overwrite,
    )
    merge_pending_update(
        pending,
        PendingUpdate(
            target=target,
            original_text=previous.original_text if previous else original,
            updated_text=updated,
            sha=sha,
            message=f"config: add {short_code} host Discord destination",
        ),
    )
    print(f"Prepared host destination ({route_type}): {target.label}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update downstream novel Discord maps using integrations.json.")
    parser.add_argument("--host", required=True, help="Hosting site name, e.g. Mistmint Haven")
    parser.add_argument("--short-code", required=True, help="Stable novel short code, e.g. AMLWC")

    parser.add_argument("--personal-role-id", default="")
    parser.add_argument("--personal-custom-emoji", default="")
    parser.add_argument("--personal-role-url", default="")

    parser.add_argument("--host-role-id", default="")
    parser.add_argument("--host-custom-emoji", default="")
    parser.add_argument("--host-role-url", default="")

    parser.add_argument("--host-destination-id", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    short_code = positive_code(args.short_code)

    personal_role_id = clean(args.personal_role_id)
    personal_custom_emoji = clean(args.personal_custom_emoji)
    personal_role_url = clean(args.personal_role_url)
    host_role_id = clean(args.host_role_id)
    host_custom_emoji = clean(args.host_custom_emoji)
    host_role_url = clean(args.host_role_url)
    host_destination_id = clean(args.host_destination_id)

    has_personal_role = validate_role_inputs(
        personal_role_id,
        personal_custom_emoji,
        personal_role_url,
        label="Personal Discord mapping",
    )
    has_host_role = validate_role_inputs(
        host_role_id,
        host_custom_emoji,
        host_role_url,
        label="Host Discord mapping",
    )

    if not has_personal_role and not has_host_role and not host_destination_id:
        print("No downstream Discord config inputs supplied; nothing to update.")
        return 0

    config = load_integrations()
    token = clean(os.getenv("PAT_GITHUB"))
    pending: dict[tuple[str, str, str, str], PendingUpdate] = {}

    if has_personal_role:
        primary = as_dict(config.get("primary_discord"))
        primary_integration = clean(primary.get("integration"))
        if not primary_integration:
            raise ScriptError("primary_discord.integration is missing from config/integrations.json.")
        prepare_role_update(
            pending=pending,
            config=config,
            token=token,
            integration_name=primary_integration,
            short_code=short_code,
            role_id=personal_role_id,
            custom_emoji=personal_custom_emoji,
            role_url=personal_role_url,
            overwrite=args.overwrite,
            label="personal Discord role mapping",
        )

    host_key, host_target = find_host_target(config, args.host)
    if has_host_role:
        if not host_target:
            raise ScriptError(
                f"Host role inputs were supplied, but host_discord_targets has no entry for {host_key!r}."
            )
        host_integration = clean(host_target.get("integration"))
        if not host_integration:
            raise ScriptError(f"host_discord_targets.{host_key}.integration is missing.")
        prepare_role_update(
            pending=pending,
            config=config,
            token=token,
            integration_name=host_integration,
            short_code=short_code,
            role_id=host_role_id,
            custom_emoji=host_custom_emoji,
            role_url=host_role_url,
            overwrite=args.overwrite,
            label="host Discord role mapping",
        )

    if host_destination_id:
        prepare_host_destination_update(
            pending=pending,
            config=config,
            token=token,
            host=args.host,
            short_code=short_code,
            destination_id=host_destination_id,
            overwrite=args.overwrite,
        )

    changed = [update for update in pending.values() if update.updated_text != update.original_text]
    unchanged = [update for update in pending.values() if update.updated_text == update.original_text]

    for update in unchanged:
        print(f"Already up to date: {update.target.label}")

    if args.dry_run:
        if not changed:
            print("Dry run: no downstream config changes.")
            return 0
        for update in changed:
            print(unified_diff(update.target.label, update.original_text, update.updated_text), end="")
        print(f"Dry run: would update {len(changed)} downstream config file(s).")
        return 0

    if not token:
        raise ScriptError("PAT_GITHUB is required because downstream config changes were requested.")

    for update in changed:
        commit_remote_file(update, token)
        print(f"Updated {update.target.label}")

    if not changed:
        print("All requested downstream mappings were already up to date.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except ScriptError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        raise SystemExit(1)
