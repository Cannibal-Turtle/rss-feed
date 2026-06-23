#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
revenue/report.py

Monthly revenue report runner.

What this file does:
- imports revenue host adapters
- collects current lifetime totals
- shows only novels with has_paid/is_paid = true in Discord
- preserves old paid novels in state if they later move to all-free
- compares current totals with revenue/state.json
- builds one Discord embed announcement
- sends it to DISCORD_MOD_CHANNEL_ID using DISCORD_BOT_TOKEN
- saves current totals + monthly/date log back to revenue/state.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

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


def current_period_key() -> str:
    # User-facing state log key. Workflow runs by Malaysia time.
    return malaysia_now().strftime("%Y-%m-%d")


def current_period_label() -> str:
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


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def clean_short_code(value: Any) -> str:
    return str(value or "").strip().upper()


def is_paid_row(row: Mapping[str, Any]) -> bool:
    # Your novel TOMLs use has_paid = true.
    # is_paid = true is supported as a fallback alias.
    return as_bool(row.get("has_paid", row.get("is_paid", False)))


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


def previous_item(state: Mapping[str, Any], row: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    state_key = str(row.get("state_key") or "").strip()

    # Backward compatibility with old state shape:
    # {"items": {"mistmint_haven:AMLWC": {...}}}
    old_items = state.get("items", {})
    if isinstance(old_items, Mapping):
        old_item = old_items.get(state_key)
        if isinstance(old_item, Mapping):
            return old_item

    host_key, short_code = split_state_key(state_key)
    host_name = str(row.get("host_name") or host_key).strip()

    hosts = state.get("hosts", {})
    if not isinstance(hosts, Mapping):
        return None

    # Preferred state uses display host name:
    # {"hosts": {"Mistmint Haven": {"novels": {"AMLWC": {...}}}}}
    # Also supports the older generated state key "mistmint_haven".
    for possible_host_key in (host_name, host_key):
        host_bucket = hosts.get(possible_host_key, {})
        if not isinstance(host_bucket, Mapping):
            continue

        novels = host_bucket.get("novels", {})
        if not isinstance(novels, Mapping):
            continue

        item = novels.get(short_code)
        if isinstance(item, Mapping):
            return item

    return None


def saved_total_coins(item: Mapping[str, Any]) -> int:
    if "total_coins" in item:
        return as_int(item.get("total_coins"), 0)
    return as_int(item.get("coins"), 0)


def saved_total_tickets(item: Mapping[str, Any]) -> int:
    if "total_tickets" in item:
        return as_int(item.get("total_tickets"), 0)
    return as_int(item.get("tickets"), 0)


def host_bucket_for_state(next_state: Dict[str, Any], host_name: str) -> Dict[str, Any]:
    hosts = next_state.setdefault("hosts", {})
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


def copy_old_state_novels(
    next_state: Dict[str, Any],
    previous_state_data: Mapping[str, Any],
    touched: Set[Tuple[str, str]],
) -> None:
    """
    Preserve old novels that are no longer returned by the current fetch.
    This protects old monthly history if a novel is removed from mappings/API.
    """
    old_hosts = previous_state_data.get("hosts", {})
    if not isinstance(old_hosts, Mapping):
        return

    for host_name, old_host in old_hosts.items():
        if not isinstance(old_host, Mapping):
            continue

        old_novels = old_host.get("novels", {})
        if not isinstance(old_novels, Mapping):
            continue

        bucket = host_bucket_for_state(next_state, str(host_name))

        for short_code, old_item in old_novels.items():
            code = clean_short_code(short_code)
            if (str(host_name), code) in touched:
                continue
            if not isinstance(old_item, Mapping):
                continue

            preserved = dict(old_item)
            preserved["is_paid"] = False
            preserved["status"] = preserved.get("status") or "inactive"

            bucket["novels"][code] = preserved
            bucket["total_coins"] = as_int(bucket.get("total_coins"), 0) + saved_total_coins(preserved)
            bucket["total_tickets"] = as_int(bucket.get("total_tickets"), 0) + saved_total_tickets(preserved)


def build_next_state(rows: Iterable[Mapping[str, Any]], previous_state_data: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Builds the minimal state shape the user wanted.

    Rules:
    - Fresh never-paid novels are skipped.
    - Paid novels are tracked and shown in Discord.
    - A previously tracked novel that later becomes all-free is preserved in
      state as inactive, but not shown in Discord.
    - Monthly revenue still uses:
        current lifetime total - previous saved lifetime total
    """
    period_key = current_period_key()
    period_label = current_period_label()

    next_state: Dict[str, Any] = {
        "last_updated": iso_now(),
        "hosts": {},
    }
    touched: Set[Tuple[str, str]] = set()

    for row in rows:
        state_key = str(row.get("state_key") or "").strip()
        if not state_key:
            continue

        _, short_code = split_state_key(state_key)
        host_name = str(row.get("host_name") or "Unknown Host").strip()
        currently_paid = is_paid_row(row)

        prev = previous_item(previous_state_data, row)

        # Never-paid current all-free novels should not enter state.
        # Previously paid/currently inactive novels should stay preserved.
        if not currently_paid and prev is None:
            continue

        touched.add((host_name, short_code))

        current_coins = as_int(row.get("coins"), 0)
        current_tickets = as_int(row.get("tickets"), 0)

        if prev is None:
            period_delta_coins = 0
            period_delta_tickets = 0
            is_baseline = True
            old_history: Dict[str, Any] = {}
        else:
            period_delta_coins = current_coins - saved_total_coins(prev)
            period_delta_tickets = current_tickets - saved_total_tickets(prev)
            is_baseline = False
            old_history = (
                dict(prev.get("monthly_revenue", {}))
                if isinstance(prev.get("monthly_revenue"), Mapping)
                else {}
            )

        should_write_period = currently_paid or is_baseline or period_delta_coins != 0 or period_delta_tickets != 0

        if should_write_period:
            previous_period_entry = old_history.get(period_key, {})
            if isinstance(previous_period_entry, Mapping):
                accumulated_coins = as_int(previous_period_entry.get("coins"), 0) + period_delta_coins
                accumulated_tickets = as_int(previous_period_entry.get("tickets"), 0) + period_delta_tickets
                baseline_flag = bool(previous_period_entry.get("baseline", False)) or is_baseline
            else:
                accumulated_coins = period_delta_coins
                accumulated_tickets = period_delta_tickets
                baseline_flag = is_baseline

            period_entry: Dict[str, Any] = {
                "label": period_label,
                "coins": accumulated_coins,
                "tickets": accumulated_tickets,
            }
            if baseline_flag:
                period_entry["baseline"] = True

            old_history[period_key] = period_entry

        host_bucket = host_bucket_for_state(next_state, host_name)

        host_bucket["total_coins"] = as_int(host_bucket.get("total_coins"), 0) + current_coins
        host_bucket["total_tickets"] = as_int(host_bucket.get("total_tickets"), 0) + current_tickets

        # monthly_coins/monthly_tickets are this period's new deltas.
        if should_write_period:
            host_bucket["monthly_coins"] = as_int(host_bucket.get("monthly_coins"), 0) + period_delta_coins
            host_bucket["monthly_tickets"] = as_int(host_bucket.get("monthly_tickets"), 0) + period_delta_tickets

        novel_state: Dict[str, Any] = {
            "title": row.get("title", ""),
            "is_paid": currently_paid,
            "is_membership": bool(row.get("is_membership", False)),
            "total_coins": current_coins,
            "total_tickets": current_tickets,
            "monthly_revenue": old_history,
        }

        if not currently_paid:
            novel_state["status"] = "inactive"

        host_bucket["novels"][short_code] = novel_state

    copy_old_state_novels(next_state, previous_state_data, touched)
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

    coins_delta = as_int(row.get("coins"), 0) - saved_total_coins(prev)
    tickets_delta = as_int(row.get("tickets"), 0) - saved_total_tickets(prev)
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

        prev = previous_item(state, row)
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

    return chunks or ["_No paid revenue rows found._"]


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
        prev = previous_item(state, row)
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
    rows.sort(key=lambda r: (str(r.get("host_name") or ""), not is_paid_row(r), str(r.get("short_code") or "")))
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
        all_rows = collect_all_rows()
        paid_rows = [row for row in all_rows if is_paid_row(row)]

        if not all_rows:
            raise RuntimeError("No Mistmint revenue rows collected. Check mappings/novels and the Mistmint API response.")

        if not paid_rows:
            print("[warn] No paid revenue rows collected. Nothing will be sent to Discord.", file=sys.stderr)

        state = load_state(state_path)
        role_map = load_role_map()

        if paid_rows:
            embeds = build_embeds(paid_rows, state, role_map)
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
        else:
            if args.print_only:
                print(json.dumps({"content": "", "embeds": []}, ensure_ascii=False, indent=2))

        if not args.no_save:
            next_state = build_next_state(all_rows, state)
            save_state(next_state, state_path)
            print(f"[ok] State saved: {state_path}")
        else:
            print("[info] --no-save used; state not updated")

        return 0

    except Exception as exc:
        msg = str(exc)
        print(f"[error] {msg}", file=sys.stderr)
        send_error_to_discord(msg)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
