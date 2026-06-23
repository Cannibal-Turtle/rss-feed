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
- saves the new lifetime totals + monthly log back to revenue/state.json
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

from revenue.hosts.mistmint_haven import collect_revenue_rows as collect_mistmint_rows  # noqa: E402


STATE_PATH = ROOT / "revenue" / "state.json"
EMBED_COLOR = 0xC9D3FF
DISCORD_API_BASE = "https://discord.com/api/v10"

GLOBAL_MENTION = "||<@&1329392448798982214>||"

TITLE_BOX = (
    "╔══.·:·.☽✧    ✦    ✧☾.·:·.══╗\n"
    "            monthly revenue\n"
    "╚══.·:·.☽✧    ✦    ✧☾.·:·.══╝"
)

DEFAULT_NOVEL_DISCORD_MAP_URL = (
    "https://raw.githubusercontent.com/Cannibal-Turtle/discord-webhook/"
    "main/config/novel_discord_map.toml"
)

NOVEL_DISCORD_MAP_URL = (
    os.environ.get("NOVEL_DISCORD_MAP_URL", "").strip()
    or DEFAULT_NOVEL_DISCORD_MAP_URL
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


def current_month_key() -> str:
    return malaysia_now().strftime("%Y-%m")


def current_month_label() -> str:
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


def clean_short_code(value: Any) -> str:
    return str(value or "").strip().upper()


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


def previous_item(state: Mapping[str, Any], state_key: str) -> Optional[Mapping[str, Any]]:
    # Backward compatibility with old state shape:
    # {"items": {"mistmint_haven:AMLWC": {...}}}
    old_items = state.get("items", {})
    if isinstance(old_items, Mapping):
        old_item = old_items.get(state_key)
        if isinstance(old_item, Mapping):
            return old_item

    # New state shape:
    # {"hosts": {"mistmint_haven": {"novels": {"AMLWC": {...}}}}}
    host_key, short_code = split_state_key(state_key)
    hosts = state.get("hosts", {})
    if not isinstance(hosts, Mapping):
        return None

    host_bucket = hosts.get(host_key, {})
    if not isinstance(host_bucket, Mapping):
        return None

    novels = host_bucket.get("novels", {})
    if not isinstance(novels, Mapping):
        return None

    item = novels.get(short_code)
    return item if isinstance(item, Mapping) else None


def build_next_state(rows: Iterable[Mapping[str, Any]], previous_state_data: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Builds the new minimal state.

    It stores:
    - current lifetime totals per novel
    - current lifetime totals per host
    - current lifetime grand totals
    - permanent month-by-month revenue history

    Monthly revenue is calculated the same way as the embed:
      current lifetime total - previous saved lifetime total

    If you run the workflow more than once in the same month, this accumulates
    that month's JSON log instead of overwriting it.
    """
    month_key = current_month_key()
    month_label = current_month_label()

    next_state: Dict[str, Any] = {
        "last_updated": iso_now(),
        "hosts": {},
        "grand_totals": {
            "total_coins": 0,
            "total_tickets": 0,
            "monthly_totals": {},
        },
    }

    # Preserve old grand monthly totals first.
    old_grand = previous_state_data.get("grand_totals", {})
    if isinstance(old_grand, Mapping):
        old_grand_months = old_grand.get("monthly_totals", {})
        if isinstance(old_grand_months, Mapping):
            next_state["grand_totals"]["monthly_totals"] = dict(old_grand_months)

    old_hosts = previous_state_data.get("hosts", {})

    run_host_month_deltas: Dict[str, Dict[str, int]] = {}
    run_grand_month_delta = {"coins": 0, "tickets": 0}

    for row in rows:
        state_key = str(row.get("state_key") or "").strip()
        if not state_key:
            continue

        host_key, short_code = split_state_key(state_key)
        host_name = str(row.get("host_name") or host_key).strip()
        host_emoji = str(row.get("host_emoji") or "").strip()

        current_coins = as_int(row.get("coins"), 0)
        current_tickets = as_int(row.get("tickets"), 0)

        prev = previous_item(previous_state_data, state_key)

        if prev is None:
            month_delta_coins = 0
            month_delta_tickets = 0
            is_baseline = True
            old_history: Dict[str, Any] = {}
        else:
            month_delta_coins = current_coins - as_int(prev.get("coins"), 0)
            month_delta_tickets = current_tickets - as_int(prev.get("tickets"), 0)
            is_baseline = False
            old_history = (
                dict(prev.get("monthly_revenue", {}))
                if isinstance(prev.get("monthly_revenue"), Mapping)
                else {}
            )

        previous_month_entry = old_history.get(month_key, {})
        if isinstance(previous_month_entry, Mapping):
            accumulated_month_coins = as_int(previous_month_entry.get("coins"), 0) + month_delta_coins
            accumulated_month_tickets = as_int(previous_month_entry.get("tickets"), 0) + month_delta_tickets
            baseline_flag = bool(previous_month_entry.get("baseline", False)) or is_baseline
        else:
            accumulated_month_coins = month_delta_coins
            accumulated_month_tickets = month_delta_tickets
            baseline_flag = is_baseline

        month_entry: Dict[str, Any] = {
            "label": month_label,
            "coins": accumulated_month_coins,
            "tickets": accumulated_month_tickets,
        }
        if baseline_flag:
            month_entry["baseline"] = True

        old_history[month_key] = month_entry

        host_bucket = next_state["hosts"].setdefault(
            host_key,
            {
                "host_name": host_name,
                "host_emoji": host_emoji,
                "total_coins": 0,
                "total_tickets": 0,
                "novels": {},
                "monthly_totals": {},
            },
        )

        # Preserve old host monthly totals.
        if isinstance(old_hosts, Mapping):
            old_host = old_hosts.get(host_key, {})
            if isinstance(old_host, Mapping):
                old_monthly_totals = old_host.get("monthly_totals", {})
                if isinstance(old_monthly_totals, Mapping) and not host_bucket["monthly_totals"]:
                    host_bucket["monthly_totals"] = dict(old_monthly_totals)

        host_bucket["host_name"] = host_name
        host_bucket["host_emoji"] = host_emoji

        host_bucket["total_coins"] = as_int(host_bucket.get("total_coins"), 0) + current_coins
        host_bucket["total_tickets"] = as_int(host_bucket.get("total_tickets"), 0) + current_tickets

        host_bucket["novels"][short_code] = {
            "title": row.get("title", ""),
            "is_membership": bool(row.get("is_membership", False)),  # fresh from TOML every run
            "coins": current_coins,
            "tickets": current_tickets,
            "monthly_revenue": old_history,
        }

        host_delta = run_host_month_deltas.setdefault(host_key, {"coins": 0, "tickets": 0})
        host_delta["coins"] += month_delta_coins
        host_delta["tickets"] += month_delta_tickets

        run_grand_month_delta["coins"] += month_delta_coins
        run_grand_month_delta["tickets"] += month_delta_tickets

        next_state["grand_totals"]["total_coins"] += current_coins
        next_state["grand_totals"]["total_tickets"] += current_tickets

    # Update host monthly totals for this month.
    for host_key, delta in run_host_month_deltas.items():
        host_bucket = next_state["hosts"].get(host_key)
        if not isinstance(host_bucket, Mapping):
            continue

        old_month_entry = host_bucket["monthly_totals"].get(month_key, {})
        if isinstance(old_month_entry, Mapping):
            total_month_coins = as_int(old_month_entry.get("coins"), 0) + delta["coins"]
            total_month_tickets = as_int(old_month_entry.get("tickets"), 0) + delta["tickets"]
        else:
            total_month_coins = delta["coins"]
            total_month_tickets = delta["tickets"]

        host_bucket["monthly_totals"][month_key] = {
            "label": month_label,
            "coins": total_month_coins,
            "tickets": total_month_tickets,
        }

    # Update grand monthly totals for this month.
    old_grand_month_entry = next_state["grand_totals"]["monthly_totals"].get(month_key, {})
    if isinstance(old_grand_month_entry, Mapping):
        grand_month_coins = as_int(old_grand_month_entry.get("coins"), 0) + run_grand_month_delta["coins"]
        grand_month_tickets = as_int(old_grand_month_entry.get("tickets"), 0) + run_grand_month_delta["tickets"]
    else:
        grand_month_coins = run_grand_month_delta["coins"]
        grand_month_tickets = run_grand_month_delta["tickets"]

    next_state["grand_totals"]["monthly_totals"][month_key] = {
        "label": month_label,
        "coins": grand_month_coins,
        "tickets": grand_month_tickets,
    }

    return next_state


# ---------------------------------------------------------------------------
# Novel role map
# ---------------------------------------------------------------------------

def normalize_role_id(value: Any) -> str:
    match = re.search(r"\d{5,}", str(value or ""))
    return match.group(0) if match else ""


def load_role_map(url: str = NOVEL_DISCORD_MAP_URL) -> Dict[str, str]:
    """
    Loads novel role IDs from discord-webhook/config/novel_discord_map.toml.
    """
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

    coins_delta = as_int(row.get("coins"), 0) - as_int(prev.get("coins"), 0)
    tickets_delta = as_int(row.get("tickets"), 0) - as_int(prev.get("tickets"), 0)
    return coins_delta, tickets_delta


def format_row(row: Mapping[str, Any], prev: Optional[Mapping[str, Any]], role_map: Mapping[str, str]) -> str:
    label = display_label(row, role_map)
    coins_total = as_int(row.get("coins"), 0)
    tickets_total = as_int(row.get("tickets"), 0)
    is_membership = bool(row.get("is_membership", False))

    host_emoji = str(row.get("host_emoji") or "").strip()
    host_divider = f"꒰ა{host_emoji}໒꒱" if host_emoji else "꒰ა໒꒱"

    coin_emoji = str(row.get("coin_emoji") or "").strip()
    ticket_emoji = str(row.get("ticket_emoji") or "").strip()

    coins_delta, tickets_delta = row_deltas(row, prev)

    header = f"{label} {host_divider} ***{fmt_total(coins_total, 'coin')}***"
    if is_membership:
        header += f" · ***{fmt_total(tickets_total, 'ticket')}***"

    lines = [header]
    lines.append(f"> {coin_emoji} ̟ !! ***{fmt_delta(coins_delta, 'coin')}***")

    if is_membership:
        lines.append(f"> {ticket_emoji} ̟ !! ***{fmt_delta(tickets_delta, 'ticket')}***")

    return "\n".join(lines)


def monthly_totals(rows: Iterable[Mapping[str, Any]], state: Mapping[str, Any]) -> Tuple[int, int, str, str]:
    total_coins = 0
    total_tickets = 0
    coin_emoji = ""
    ticket_emoji = ""

    for row in rows:
        if not coin_emoji:
            coin_emoji = str(row.get("coin_emoji") or "").strip()
        if not ticket_emoji:
            ticket_emoji = str(row.get("ticket_emoji") or "").strip()

        key = str(row.get("state_key") or "")
        prev = previous_item(state, key)
        coins_delta, tickets_delta = row_deltas(row, prev)

        if coins_delta is not None:
            total_coins += coins_delta
        if tickets_delta is not None:
            total_tickets += tickets_delta

    return total_coins, total_tickets, coin_emoji, ticket_emoji


def format_monthly_totals(rows: List[Mapping[str, Any]], state: Mapping[str, Any]) -> str:
    total_coins, total_tickets, coin_emoji, ticket_emoji = monthly_totals(rows, state)

    return (
        "**Total earned coins this month:**\n"
        f"### {coin_emoji} ̟ !! ***{fmt_month_total(total_coins, 'coin')}***\n"
        "**Total tickets sold this month:**\n"
        f"### {ticket_emoji} ̟ !! ***{fmt_month_total(total_tickets, 'ticket')}***"
    )


def chunk_description(parts: List[str], summary: str, *, first_run: bool, max_chars: int = 3900) -> List[str]:
    chunks: List[str] = []
    current = ""

    if first_run:
        current = "_First run: baseline saved. Monthly deltas start next run._"

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

    return chunks or ["_No revenue rows found._"]


def build_embeds(
    rows: List[Mapping[str, Any]],
    state: Mapping[str, Any],
    role_map: Mapping[str, str],
) -> List[Dict[str, Any]]:
    old_items = state.get("items", {})
    old_hosts = state.get("hosts", {})
    first_run = (
        not (isinstance(old_items, Mapping) and bool(old_items))
        and not (isinstance(old_hosts, Mapping) and bool(old_hosts))
    )

    parts: List[str] = []
    for row in rows:
        key = str(row.get("state_key") or "")
        prev = previous_item(state, key)
        parts.append(format_row(row, prev, role_map))

    summary = format_monthly_totals(rows, state)
    descriptions = chunk_description(parts, summary, first_run=first_run)
    timestamp = iso_now()

    embeds: List[Dict[str, Any]] = []
    for i, description in enumerate(descriptions):
        embed: Dict[str, Any] = {
            "description": description,
            "color": EMBED_COLOR,
            "footer": {"text": "Data retrieved"},
            "timestamp": timestamp,
        }
        if i == 0:
            embed["title"] = TITLE_BOX
        else:
            embed["title"] = "monthly revenue — continued"
        embeds.append(embed)

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

    payload = {
        "content": f"{GLOBAL_MENTION}\n",
        "embeds": list(embeds)[:10],
        "allowed_mentions": {"parse": ["roles"]},
    }

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
    payload = {
        "content": f"⚠️ Mistmint revenue report failed:\n```text\n{safe}\n```",
        "allowed_mentions": {"parse": []},
    }

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
    rows.sort(key=lambda r: (str(r.get("host_name") or ""), str(r.get("short_code") or "")))
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

        payload_preview = {
            "content": f"{GLOBAL_MENTION}\n",
            "embeds": embeds,
        }

        if args.print_only:
            print(json.dumps(payload_preview, ensure_ascii=False, indent=2))
        else:
            token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
            channel_id = args.channel or os.getenv("DISCORD_MOD_CHANNEL_ID", "").strip()
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
