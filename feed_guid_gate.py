from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def read_guids(feed_path: str | Path) -> set[str]:
    path = Path(feed_path)
    if not path.exists():
        return set()

    root = ET.parse(path).getroot()
    return {
        (elem.text or "").strip()
        for elem in root.iter()
        if _local_name(elem.tag) == "guid" and (elem.text or "").strip()
    }


def snapshot(feed_path: str, snapshot_path: str) -> None:
    guids = sorted(read_guids(feed_path))
    Path(snapshot_path).write_text("\n".join(guids), encoding="utf-8")
    print(f"Snapshot saved: {len(guids)} GUID(s) from {feed_path}")


def detect(feed_path: str, snapshot_path: str) -> None:
    before_file = Path(snapshot_path)
    before = set(before_file.read_text(encoding="utf-8").splitlines()) if before_file.exists() else set()
    after = read_guids(feed_path)

    added = sorted(after - before)
    removed = sorted(before - after)
    new_items = "true" if added else "false"

    print(f"Before GUIDs: {len(before)}")
    print(f"After GUIDs:  {len(after)}")
    print(f"Added GUIDs:  {len(added)}")
    print(f"Removed GUIDs:{len(removed)}")
    print(f"new_items={new_items}")

    for guid in added[:20]:
        print(f"  + {guid}")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"new_items={new_items}\n")
            f.write(f"added_count={len(added)}\n")
            f.write(f"removed_count={len(removed)}\n")


def main() -> int:
    if len(sys.argv) != 4 or sys.argv[1] not in {"snapshot", "detect"}:
        print("Usage:")
        print("  python tools/feed_guid_gate.py snapshot <feed.xml> <snapshot.txt>")
        print("  python tools/feed_guid_gate.py detect   <feed.xml> <snapshot.txt>")
        return 2

    command, feed_path, snapshot_path = sys.argv[1:]
    if command == "snapshot":
        snapshot(feed_path, snapshot_path)
    else:
        detect(feed_path, snapshot_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())