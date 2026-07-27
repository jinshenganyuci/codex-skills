#!/usr/bin/env python3
"""Compare two JSON reports produced by triage_artifact.py."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable


def load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or "artifact" not in value:
        raise ValueError(f"not a triage report: {path}")
    return value


def set_diff(
    old_items: list[Any],
    new_items: list[Any],
    key: Callable[[Any], str],
) -> dict[str, list[str]]:
    old = {key(item) for item in old_items}
    new = {key(item) for item in new_items}
    return {"added": sorted(new - old), "removed": sorted(old - new)}


def native_names(report: dict[str, Any]) -> list[dict[str, Any]]:
    archive = report.get("archive") or {}
    return archive.get("native_libraries") or []


def compare(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_indicators = old.get("indicators") or {}
    new_indicators = new.get("indicators") or {}
    return {
        "old": {
            "name": old["artifact"].get("name"),
            "sha256": (old["artifact"].get("hashes") or {}).get("sha256"),
            "size": old["artifact"].get("size"),
            "kind": old["artifact"].get("kind"),
        },
        "new": {
            "name": new["artifact"].get("name"),
            "sha256": (new["artifact"].get("hashes") or {}).get("sha256"),
            "size": new["artifact"].get("size"),
            "kind": new["artifact"].get("kind"),
        },
        "urls": set_diff(
            old_indicators.get("urls_by_value") or [],
            new_indicators.get("urls_by_value") or [],
            lambda item: str(item.get("value", "")),
        ),
        "paths": set_diff(
            old_indicators.get("paths") or [],
            new_indicators.get("paths") or [],
            lambda item: str(item.get("value", "")),
        ),
        "filenames": set_diff(
            old_indicators.get("filenames") or [],
            new_indicators.get("filenames") or [],
            lambda item: str(item.get("value", "")),
        ),
        "packer_markers": set_diff(
            old_indicators.get("packer_markers") or [],
            new_indicators.get("packer_markers") or [],
            lambda item: str(item.get("value", "")),
        ),
        "suspicious_commands": set_diff(
            old_indicators.get("suspicious_commands") or [],
            new_indicators.get("suspicious_commands") or [],
            lambda item: str(item.get("value", "")),
        ),
        "native_libraries": set_diff(
            native_names(old), native_names(new), lambda item: str(item.get("name", ""))
        ),
        "container_counts": {
            "embedded_elf": {
                "old": len(old_indicators.get("embedded_elf_offsets") or []),
                "new": len(new_indicators.get("embedded_elf_offsets") or []),
            },
            "zstd_magic": {
                "old": len(old_indicators.get("zstd_magic_offsets") or []),
                "new": len(new_indicators.get("zstd_magic_offsets") or []),
            },
        },
    }


def print_human(diff: dict[str, Any]) -> None:
    print(
        f"Old: {diff['old']['name']} size={diff['old']['size']} "
        f"sha256={diff['old']['sha256']}"
    )
    print(
        f"New: {diff['new']['name']} size={diff['new']['size']} "
        f"sha256={diff['new']['sha256']}"
    )
    for section in (
        "urls", "paths", "filenames", "packer_markers",
        "suspicious_commands", "native_libraries",
    ):
        values = diff[section]
        print(f"\n{section}:")
        for value in values["added"]:
            print(f"+ {value}")
        for value in values["removed"]:
            print(f"- {value}")
        if not values["added"] and not values["removed"]:
            print("  unchanged")
    print("\ncontainer_counts:")
    for name, values in diff["container_counts"].items():
        print(f"- {name}: {values['old']} -> {values['new']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two artifact triage JSON reports.")
    parser.add_argument("old_report", type=Path)
    parser.add_argument("new_report", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        old = load(args.old_report)
        new = load(args.new_report)
        diff = compare(old, new)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(diff, ensure_ascii=False, indent=2))
    else:
        print_human(diff)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
