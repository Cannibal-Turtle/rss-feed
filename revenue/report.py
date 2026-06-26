#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
revenue/report.py

Monthly revenue report runner.

What this file does:
- imports revenue host adapters
- collects current lifetime totals
- compares them with revenue/state.json
- builds one Discord embed announcement
- sends it to DISCORD_MOD_CHANNEL_ID using DISCORD_BOT_TOKEN
- saves current lifetime totals + monthly revenue log back to revenue/state.json

Important behavior:
- only has_paid/is_paid novels show in Discord
- old novels that later become all-free are preserved in state as inactive
- bottom embed total only shows overall coins, not tickets
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import requests

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore


# File path expected: rss-feed/revenue/report.py
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from revenue.hosts.mistmint_haven import collect_revenue_rows as collect_mistmint_rows

from message_renderer import (
    load_template_settings,
    render_message,
    to_discord_api_payload,
)
from message_settings import (
    global_mention_from_settings,
    setting_color_int,
)

try:
    from config_loader import (
        get_discord_webhook_channel_id,
        get_discord_webhook_role_id,
        get_novel_discord_map_url,
    )
except Exception:
    def get_discord_webhook_channel_id(key: str, default: str = "") -> str:
        return default

    def get_discord_webhook_role_id(key: str, default: str = "") -> str:
        return default

    def get_novel_discord_map_url(default: str = "") -> str:
        return default


STATE_PATH = ROOT / "revenue" / "state.json"
DISCORD_API_BASE = "https://discord.com/api/v10"

_TEMPLATE_SETTINGS = load_template_settings("revenue_report")

EMBED_COLOR = setting_color_int(
    _TEMPLATE_SETTINGS,
    "embed_color",
    0xC9D3FF,
    env="REVENUE_EMBED_COLOR_HEX",
    fallback_env="EMBED_COLOR_HEX",
)

GLOBAL_MENTION = global_mention_from_settings(_TEMPLATE_SETTINGS)

NOVEL_DISCORD_MAP_URL = (
    os.environ.get("NOVEL_DISCORD_MAP_URL", "").strip()
    or get_novel_discord_map_url()
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def malaysia_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))


def current_report_key() -> str:
    # Example: 2026-06-23
    return malaysia_now().strftime("%Y-%m-%d")


def current_month_label() -> str:
    # Example: June 2026
    return malaysia_now().strftime("%B %Y")


def split_state_key(state_key: str) -> Tuple[str, str]:
    if ":" not in state_key:
        return state_key.strip(), ""
    host_key, short_code = state_key.split(":", 1)
    return host_key.strip(), short_code.strip().upper()


def plural(n: int, word: str) -> str:
    return word if abs(int(n)) == 1 else word + "s"


def fmt_total(n: int, word: str) -> str:
    n = int(n)
    return f"{n:,} total {plural(n, word)}"


def fmt_delta(delta: Optional[int], word: str) -> str:
    if delta is None:
        return "baseline saved"

    delta = int(delta)
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:,} {plural(delta, word)}"


def fmt_month_total(delta: int, word: str) -> str:
    delta = int(delta)
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:,} {plural(delta, word)}"


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(str(value).replace(",", "").strip()))
    except Exception:
        return default


def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default

    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "paid"}:
        return True
    if text in {"false", "0", "no", "n", "free"}:
        return False

    return default


def clean_short_code(value: Any) -> str:
    return str(value or "").strip().upper()


def row_is_paid(row: Mapping[str, Any]) -> bool:
    """
    Novel TOMLs currently use:
      has_paid = true

    Some drafts used:
      is_paid = true

    This supports both.
    """
    if "has_paid" in row:
        return as_bool(row.get("has_paid"), False)
    if "is_paid" in row:
        return as_bool(row.get("is_paid"), False)
    return False


def state_total_coins(item: Mapping[str, Any]) -> int:
    return as_int(item.get("total_coins", item.get("coins", 0)), 0)


def state_total_tickets(item: Mapping[str, Any]) -> int:
    return as_int(item.get("total_tickets", item.get("tickets", 0)), 0)


def clone_monthly_history(item: Mapping[str, Any]) -> Dict[str, Any]:
    history = item.get("monthly_revenue", {})
    return dict(history) if isinstance(history, Mapping) else {}


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def load_state(path: Path = STATE_PATH) -> Dict[str, Any]:
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        bad_path = path.with_suffix(path.suffix + ".bad")
        try:
            path.replace(bad_path)
            print(f"[warn] invalid state moved to {bad_path}: {exc}")
        except Exception:
            print(f"[warn] invalid state could not be moved: {exc}")
        return {}


def save_state(state: Mapping[str, Any], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


def previous_item(
    state: Mapping[str, Any],
    state_key: str,
    row: Optional[Mapping[str, Any]] = None,
) -> Optional[Mapping[str, Any]]:
    """
    Finds previous saved novel state.

    Supports old state:
      items["mistmint_haven:AMLWC"]

    Supports new state:
      hosts["Mistmint Haven"]["novels"]["AMLWC"]
    """
    old_items = state.get("items", {})
    if isinstance(old_items, Mapping):
        old_item = old_items.get(state_key)
        if isinstance(old_item, Mapping):
            return old_item

    host_key, short_code = split_state_key(state_key)
    hosts = state.get("hosts", {})
    if not isinstance(hosts, Mapping):
        return None

    candidate_host_names: List[str] = []

    if row is not None:
        host_name = str(row.get("host_name") or "").strip()
        row_host_key = str(row.get("host_key") or "").strip()
        if host_name:
            candidate_host_names.append(host_name)
        if row_host_key:
            candidate_host_names.append(row_host_key)

    if host_key:
        candidate_host_names.append(host_key)

    seen_hosts = set()
    for host_name in candidate_host_names:
        if not host_name or host_name in seen_hosts:
            continue
        seen_hosts.add(host_name)

        host_bucket = hosts.get(host_name, {})
        if not isinstance(host_bucket, Mapping):
            continue

        novels = host_bucket.get("novels", {})
        if not isinstance(novels, Mapping):
            continue

        item = novels.get(short_code)
        if isinstance(item, Mapping):
            return item

    # Last fallback: search all hosts by short_code.
    for host_bucket in hosts.values():
        if not isinstance(host_bucket, Mapping):
            continue
        novels = host_bucket.get("novels", {})
        if not isinstance(novels, Mapping):
            continue
        item = novels.get(short_code)
        if isinstance(item, Mapping):
            return item

    return None


def new_empty_state() -> Dict[str, Any]:
    return {
        "last_updated": iso_now(),
        "hosts": {},
    }


def get_or_create_host_bucket(state: Dict[str, Any], host_name: str) -> Dict[str, Any]:
    hosts = state.setdefault("hosts", {})
    bucket = hosts.setdefault(
        host_name,
        {
            "total_coins": 0,
            "monthly_coins": 0,
            "total_tickets": 0,
            "monthly_tickets": 0,
            "novels": {},
        },
    )
    return bucket


def upsert_month_entry(
    history: Dict[str, Any],
    *,
    report_key: str,
    month_label: str,
    coins_delta: int,
    tickets_delta: int,
    baseline: bool,
) -> None:
    old_entry = history.get(report_key, {})

    if isinstance(old_entry, Mapping):
        coins = as_int(old_entry.get("coins"), 0) + coins_delta
        tickets = as_int(old_entry.get("tickets"), 0) + tickets_delta
        baseline_flag = bool(old_entry.get("baseline", False)) or baseline
    else:
        coins = coins_delta
        tickets = tickets_delta
        baseline_flag = baseline

    entry: Dict[str, Any] = {
        "label": month_label,
        "coins": coins,
        "tickets": tickets,
    }

    if baseline_flag:
        entry["baseline"] = True

    history[report_key] = entry


def add_or_update_novel_state(
    next_state: Dict[str, Any],
    *,
    host_name: str,
    short_code: str,
    title: str,
    is_paid: bool,
    is_membership: bool,
    total_coins: int,
    total_tickets: int,
    monthly_revenue: Dict[str, Any],
    inactive: bool,
) -> None:
    host_bucket = get_or_create_host_bucket(next_state, host_name)
    novels = host_bucket.setdefault("novels", {})

    item: Dict[str, Any] = {
        "title": title,
        "is_paid": bool(is_paid),
        "is_membership": bool(is_membership),
        "total_coins": total_coins,
        "total_tickets": total_tickets,
        "monthly_revenue": monthly_revenue,
    }

    if inactive:
        item["status"] = "inactive"

    novels[short_code] = item


def recompute_host_totals(next_state: Dict[str, Any], month_label: str) -> None:
    hosts = next_state.get("hosts", {})
    if not isinstance(hosts, Mapping):
        return

    for host_bucket in hosts.values():
        if not isinstance(host_bucket, dict):
            continue

        novels = host_bucket.get("novels", {})
        if not isinstance(novels, Mapping):
            continue

        total_coins = 0
        total_tickets = 0
        monthly_coins = 0
        monthly_tickets = 0

        for novel in novels.values():
            if not isinstance(novel, Mapping):
                continue

            total_coins += state_total_coins(novel)
            total_tickets += state_total_tickets(novel)

            history = novel.get("monthly_revenue", {})
            if isinstance(history, Mapping):
                for entry in history.values():
                    if not isinstance(entry, Mapping):
                        continue
                    if str(entry.get("label") or "") != month_label:
                        continue
                    monthly_coins += as_int(entry.get("coins"), 0)
                    monthly_tickets += as_int(entry.get("tickets"), 0)

        host_bucket["total_coins"] = total_coins
        host_bucket["monthly_coins"] = monthly_coins
        host_bucket["total_tickets"] = total_tickets
        host_bucket["monthly_tickets"] = monthly_tickets


def preserve_old_unseen_novels(
    next_state: Dict[str, Any],
    previous_state_data: Mapping[str, Any],
    seen: set[Tuple[str, str]],
    seen_short_codes: set[str],
) -> None:
    """
    Preserves old novels that are no longer returned/selected.

    This protects history when a novel moves from paid to all-free.
    The short-code guard also prevents duplicate migration from old host keys like
    "mistmint_haven" to display host keys like "Mistmint Haven".
    """
    hosts = previous_state_data.get("hosts", {})
    if not isinstance(hosts, Mapping):
        return

    for raw_host_name, old_host in hosts.items():
        host_name = str(raw_host_name or "").strip()
        if not host_name or not isinstance(old_host, Mapping):
            continue

        novels = old_host.get("novels", {})
        if not isinstance(novels, Mapping):
            continue

        for raw_code, old_novel in novels.items():
            short_code = clean_short_code(raw_code)
            if not short_code:
                continue

            marker = (host_name, short_code)
            if marker in seen or short_code in seen_short_codes:
                continue

            if not isinstance(old_novel, Mapping):
                continue

            add_or_update_novel_state(
                next_state,
                host_name=host_name,
                short_code=short_code,
                title=str(old_novel.get("title") or "").strip(),
                is_paid=False,
                is_membership=as_bool(old_novel.get("is_membership"), False),
                total_coins=state_total_coins(old_novel),
                total_tickets=state_total_tickets(old_novel),
                monthly_revenue=clone_monthly_history(old_novel),
                inactive=True,
            )


def build_next_state(rows: Iterable[Mapping[str, Any]], previous_state_data: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Builds the new minimal state.

    Active paid novels:
      - updated
      - monthly delta is logged
      - shown in Discord

    Old novels that are no longer paid:
      - preserved in state
      - marked inactive
      - not shown in Discord
    """
    report_key = current_report_key()
    month_label = current_month_label()

    next_state = new_empty_state()
    seen: set[Tuple[str, str]] = set()
    seen_short_codes: set[str] = set()

    for row in rows:
        state_key = str(row.get("state_key") or "").strip()
        if not state_key:
            continue

        _host_key, short_code = split_state_key(state_key)
        if not short_code:
            continue

        host_name = str(row.get("host_name") or "").strip() or "Unknown Host"
        is_paid = row_is_paid(row)

        prev = previous_item(previous_state_data, state_key, row)

        # If it is not paid and was never tracked before, skip it completely.
        if not is_paid and prev is None:
            continue

        current_coins = as_int(row.get("coins"), 0)
        current_tickets = as_int(row.get("tickets"), 0)

        if prev is None:
            coins_delta = 0
            tickets_delta = 0
            baseline = True
            history: Dict[str, Any] = {}
        else:
            history = clone_monthly_history(prev)

            if is_paid:
                coins_delta = current_coins - state_total_coins(prev)
                tickets_delta = current_tickets - state_total_tickets(prev)
                baseline = False
            else:
                # Preserve inactive/all-free novel without counting new monthly revenue.
                coins_delta = 0
                tickets_delta = 0
                baseline = False

        if is_paid:
            upsert_month_entry(
                history,
                report_key=report_key,
                month_label=month_label,
                coins_delta=coins_delta,
                tickets_delta=tickets_delta,
                baseline=baseline,
            )

        add_or_update_novel_state(
            next_state,
            host_name=host_name,
            short_code=short_code,
            title=str(row.get("title") or "").strip(),
            is_paid=is_paid,
            is_membership=as_bool(row.get("is_membership"), False),
            total_coins=current_coins if is_paid else (state_total_coins(prev) if prev else current_coins),
            total_tickets=current_tickets if is_paid else (state_total_tickets(prev) if prev else current_tickets),
            monthly_revenue=history,
            inactive=not is_paid,
        )

        seen.add((host_name, short_code))
        seen_short_codes.add(short_code)

    preserve_old_unseen_novels(next_state, previous_state_data, seen, seen_short_codes)
    recompute_host_totals(next_state, month_label)

    return next_state


# ---------------------------------------------------------------------------
# Novel role map
# ---------------------------------------------------------------------------

def normalize_role_id(value: Any) -> str:
    match = re.search(r"\d{5,}", str(value or ""))
    return match.group(0) if match else ""


def load_role_map(url: Optional[str] = None) -> Dict[str, str]:
    """
    Loads novel role IDs from discord-webhook/config/novel_discord_map.toml.

    Supports TOML like:
      [AMLWC]
      role_id = "123..."

    Also supports simple string values:
      AMLWC = "123..."
    """
    url = NOVEL_DISCORD_MAP_URL if url is None else str(url).strip()
    if not url:
        return {}

    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        data = tomllib.loads(r.text)
    except Exception as exc:
        print(f"[warn] could not load novel Discord map: {exc}", file=sys.stderr)
        return {}

    out: Dict[str, str] = {}
    if not isinstance(data, Mapping):
        return out

    for raw_code, raw_value in data.items():
        code = clean_short_code(raw_code)
        if not code:
            continue

        role_id = ""
        if isinstance(raw_value, Mapping):
            role_id = normalize_role_id(raw_value.get("role_id") or raw_value.get("id"))
        else:
            role_id = normalize_role_id(raw_value)

        if role_id:
            out[code] = f"<@&{role_id}>"

    return out


def display_label(row: Mapping[str, Any], role_map: Mapping[str, str]) -> str:
    code = clean_short_code(row.get("short_code"))
    return role_map.get(code) or f"@{code or 'UNKNOWN'}"


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def row_deltas(row: Mapping[str, Any], prev: Optional[Mapping[str, Any]]) -> Tuple[Optional[int], Optional[int]]:
    if prev is None:
        return None, None

    coins_delta = as_int(row.get("coins"), 0) - state_total_coins(prev)
    tickets_delta = as_int(row.get("tickets"), 0) - state_total_tickets(prev)
    return coins_delta, tickets_delta


def render_template_text(variant: str, ctx: Optional[Mapping[str, Any]] = None) -> str:
    rendered = render_message("revenue_report", dict(ctx or {}), variant=variant)
    return str(rendered.get("text", "")).strip("\n")


def format_row(row: Mapping[str, Any], prev: Optional[Mapping[str, Any]], role_map: Mapping[str, str]) -> str:
    label = display_label(row, role_map)
    coins_total = as_int(row.get("coins"), 0)
    tickets_total = as_int(row.get("tickets"), 0)
    is_membership = as_bool(row.get("is_membership"), False)

    host_emoji = str(row.get("host_emoji") or "").strip()
    host_divider = f"꒰ა{host_emoji}໒꒱" if host_emoji else "꒰ა໒꒱"

    coin_emoji = str(row.get("coin_emoji") or "").strip()
    ticket_emoji = str(row.get("ticket_emoji") or "").strip()

    coins_delta, tickets_delta = row_deltas(row, prev)

    ctx = {
        "label": label,
        "host_divider": host_divider,
        "coins_total_text": fmt_total(coins_total, "coin"),
        "tickets_total_text": fmt_total(tickets_total, "ticket"),
        "coin_emoji": coin_emoji,
        "ticket_emoji": ticket_emoji,
        "coins_delta_text": fmt_delta(coins_delta, "coin"),
        "tickets_delta_text": fmt_delta(tickets_delta, "ticket"),
    }

    variant = "row_membership" if is_membership else "row_basic"
    return render_template_text(variant, ctx)

def monthly_totals(rows: Iterable[Mapping[str, Any]], state: Mapping[str, Any]) -> Tuple[int, int]:
    total_coins = 0
    total_tickets = 0

    for row in rows:
        key = str(row.get("state_key") or "")
        prev = previous_item(state, key, row)
        coins_delta, tickets_delta = row_deltas(row, prev)

        if coins_delta is not None:
            total_coins += coins_delta
        if tickets_delta is not None:
            total_tickets += tickets_delta

    return total_coins, total_tickets


def format_monthly_totals(rows: List[Mapping[str, Any]], state: Mapping[str, Any]) -> str:
    total_coins, _total_tickets = monthly_totals(rows, state)

    return render_template_text(
        "monthly_total",
        {"monthly_coins_text": fmt_month_total(total_coins, "coin")},
    )


def chunk_description(
    parts: List[str],
    summary: str,
    *,
    first_run: bool,
    month_label: str,
    max_chars: int = 3900,
) -> List[str]:
    chunks: List[str] = []

    if first_run:
        current = render_template_text("first_run")
    else:
        current = render_template_text("month_header", {"month_label_upper": month_label.upper()})

    for part in parts:
        add = part if not current.strip() else "\n" + part
        if len(current) + len(add) > max_chars and current.strip():
            chunks.append(current.strip())
            current = part
        else:
            current += add

    if summary:
        add = "\n\n" + summary if current.strip() else summary
        if len(current) + len(add) > max_chars and current.strip():
            chunks.append(current.strip())
            current = summary
        else:
            current += add

    if current.strip():
        chunks.append(current.strip())

    return chunks or [render_template_text("empty_report")]


def is_first_run_state(state: Mapping[str, Any]) -> bool:
    old_items = state.get("items", {})
    old_hosts = state.get("hosts", {})

    has_old_items = isinstance(old_items, Mapping) and bool(old_items)
    has_old_hosts = isinstance(old_hosts, Mapping) and bool(old_hosts)

    return not has_old_items and not has_old_hosts


def build_embeds(
    rows: List[Mapping[str, Any]],
    state: Mapping[str, Any],
    role_map: Mapping[str, str],
) -> List[Dict[str, Any]]:
    report_rows = [row for row in rows if row_is_paid(row)]

    if not report_rows:
        raise RuntimeError("No paid revenue rows collected. Check has_paid = true in novel TOMLs.")

    first_run = is_first_run_state(state)

    parts: List[str] = []
    for row in report_rows:
        key = str(row.get("state_key") or "")
        prev = previous_item(state, key, row)
        parts.append(format_row(row, prev, role_map))

    summary = format_monthly_totals(report_rows, state)

    descriptions = chunk_description(
        parts,
        summary,
        first_run=first_run,
        month_label=current_month_label(),
    )

    timestamp = iso_now()

    embeds: List[Dict[str, Any]] = []
    for i, description in enumerate(descriptions):
        title = (
            render_template_text("title_main")
            if i == 0
            else render_template_text("title_continued")
        )

        payload = render_message(
            "revenue_report",
            {
                "title": title,
                "description": description,
                "embed_color": EMBED_COLOR,
                "timestamp": timestamp,
            },
            variant="embed",
        )
        embed_items = payload.get("embeds") or []
        if not embed_items:
            raise RuntimeError("Revenue embed template rendered no embeds.")
        embeds.append(dict(embed_items[0]))

    return embeds


# ---------------------------------------------------------------------------
# Discord bot send/edit
# ---------------------------------------------------------------------------

def discord_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }


def send_discord_embeds(
    embeds: List[Mapping[str, Any]],
    *,
    token: str,
    channel_id: str,
    message_id: str = "",
) -> Optional[str]:
    if not token:
        raise RuntimeError("Missing DISCORD_BOT_TOKEN.")
    if not channel_id:
        raise RuntimeError("Missing DISCORD_MOD_CHANNEL_ID.")

    payload = render_message(
        "revenue_report",
        {"global_mention": GLOBAL_MENTION},
        variant="message",
    )
    payload["embeds"] = list(embeds)[:10]
    payload = to_discord_api_payload(payload)

    headers = discord_headers(token)

    if message_id:
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}"
        r = requests.patch(url, headers=headers, json=payload, timeout=30)
    else:
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        r = requests.post(url, headers=headers, json=payload, timeout=30)

    if r.status_code // 100 != 2:
        raise RuntimeError(f"Discord API failure {r.status_code}: {r.text[:1000]}")

    try:
        return str(r.json().get("id") or "")
    except Exception:
        return None


def send_error_to_discord(message: str) -> None:
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    channel_id = os.getenv("DISCORD_MOD_CHANNEL_ID", "").strip()

    if not token or not channel_id:
        return

    safe = message[:1800]
    payload = to_discord_api_payload(
        render_message(
            "revenue_report",
            {"safe_message": safe},
            variant="error",
        )
    )

    try:
        r = requests.post(
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            headers=discord_headers(token),
            json=payload,
            timeout=30,
        )
        if r.status_code // 100 != 2:
            print(f"[warn] failed to send Discord error: {r.status_code} {r.text}", file=sys.stderr)
    except Exception as exc:
        print(f"[warn] failed to send Discord error: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def collect_all_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    rows.extend(collect_mistmint_rows())
    rows.sort(
        key=lambda r: (
            str(r.get("host_name") or ""),
            str(r.get("short_code") or ""),
        )
    )
    return rows


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-only", action="store_true", help="Print the Discord payload but do not send it.")
    parser.add_argument("--no-save", action="store_true", help="Do not update revenue/state.json.")
    parser.add_argument("--state", default=str(STATE_PATH), help="State JSON path. Default: revenue/state.json")
    parser.add_argument("--channel", default="", help="Override DISCORD_MOD_CHANNEL_ID.")
    parser.add_argument("--message", default="", help="Optional Discord message id to edit instead of sending a new message.")
    args = parser.parse_args(argv)

    state_path = Path(args.state)

    try:
        rows = collect_all_rows()
        if not rows:
            raise RuntimeError("No revenue rows collected.")

        state = load_state(state_path)
        role_map = load_role_map()
        embeds = build_embeds(rows, state, role_map)

        payload_preview = render_message(
            "revenue_report",
            {"global_mention": GLOBAL_MENTION},
            variant="message",
        )
        payload_preview["embeds"] = embeds
        payload_preview = to_discord_api_payload(payload_preview)

        if args.print_only:
            print(json.dumps(payload_preview, ensure_ascii=False, indent=2))
        else:
            token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
            channel_id = (
                args.channel
                or os.getenv("DISCORD_MOD_CHANNEL_ID", "").strip()
                or get_discord_webhook_channel_id("mod")
            )
            message_id = args.message or os.getenv("DISCORD_REVENUE_MESSAGE_ID", "").strip()

            mid = send_discord_embeds(
                embeds,
                token=token,
                channel_id=channel_id,
                message_id=message_id,
            )
            print(f"[ok] Discord revenue report {'edited' if message_id else 'sent'}: id={mid}")

        if not args.no_save:
            next_state = build_next_state(rows, state)
            save_state(next_state, state_path)
            print(f"[ok] State saved: {state_path}")
        else:
            print("[info] --no-save used; state not updated")

        inactive_rows = [r for r in rows if not row_is_paid(r)]
        for row in inactive_rows:
            print(
                f"[info] not shown in report because not paid: "
                f"{row.get('host_name')} / {row.get('title')}",
                file=sys.stderr,
            )

        unmapped = [r for r in rows if not r.get("is_mapped", True)]
        for row in unmapped:
            print(f"[warn] unmapped novel: {row.get('host_name')} / {row.get('title')}", file=sys.stderr)

        return 0

    except Exception as exc:
        msg = str(exc)
        print(f"[error] {msg}", file=sys.stderr)
        send_error_to_discord(msg)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
