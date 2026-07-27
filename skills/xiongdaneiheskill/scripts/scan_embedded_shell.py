#!/usr/bin/env python3
"""Extract probable NUL-terminated shell payloads without executing them."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable


SHELL_MARKERS = (
    "#!/", "if [[", "if [", "() {", "function ", "mkdir ", "rm ",
    "rmdir ", "echo ", "chmod ", "chattr ", "mount ", "umount ",
    "taskset ", "pgrep ", "/system/bin/sh",
)
FUNCTION_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(\s*\))?\s*\{")
ABSOLUTE_RE = re.compile(r"(?<![A-Za-z0-9_])(/[^\s\"';|&<>]+)")
REDIRECT_RE = re.compile(
    r"(?<![<>])(?P<fd>\d*)(?P<operator>>{1,2})\s*[\"']?"
    r"(?P<target>[^\"'\s;|&]+)"
)


def nul_regions(data: bytes, min_length: int, max_length: int) -> Iterable[tuple[int, bytes]]:
    start = 0
    for raw in data.split(b"\0"):
        if min_length <= len(raw) <= max_length:
            yield start, raw
        start += len(raw) + 1


def score_shell(text: str) -> tuple[int, list[str]]:
    matched = [marker for marker in SHELL_MARKERS if marker in text]
    score = len(matched)
    if text.startswith("#!"):
        score += 4
    if "\n" in text:
        score += 1
    return score, matched


def normalize_token(token: str) -> str:
    return token.strip().strip("\"'").rstrip(";")


def analyze_text(text: str) -> dict[str, Any]:
    definitions: set[str] = set()
    calls: set[str] = set()
    operations: list[dict[str, Any]] = []
    all_paths: set[str] = set()
    lines = text.splitlines()
    for number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        definition = FUNCTION_RE.match(raw_line)
        if definition:
            definitions.add(definition.group(1))
            continue
        for path in ABSOLUTE_RE.findall(line):
            all_paths.add(normalize_token(path))
        command = line.split(None, 1)[0] if line.split() else ""
        command = command.strip()
        if command in {"mkdir", "touch", "cp", "mv", "rm", "rmdir", "chmod", "chattr", "mount", "umount", "echo"}:
            if command == "mkdir":
                category = "create_directory_candidate"
            elif command == "touch":
                category = "create_file_candidate"
            elif command in {"cp", "mv"}:
                category = "create_or_move_candidate"
            elif command in {"rm", "rmdir"}:
                category = "delete"
            elif command == "echo" and ">" in line:
                category = "write_or_create_candidate"
            else:
                category = "modify_existing"
            operations.append({
                "line": number, "category": category,
                "command": command, "text": line,
            })
        redirect = REDIRECT_RE.search(line)
        if redirect and normalize_token(redirect.group("target")) != "/dev/null":
            operations.append({
                "line": number, "category": "redirection_write_candidate",
                "command": "redirection",
                "file_descriptor": redirect.group("fd") or "stdout",
                "operator": redirect.group("operator"),
                "target": normalize_token(redirect.group("target")), "text": line,
            })
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or FUNCTION_RE.match(raw_line):
            continue
        first = line.split(None, 1)[0]
        if first in definitions:
            calls.add(first)
    return {
        "defined_functions": sorted(definitions),
        "called_functions": sorted(calls),
        "defined_but_not_called": sorted(definitions - calls),
        "absolute_path_tokens": sorted(all_paths),
        "operations": operations,
    }


def scan(data: bytes, min_length: int, max_length: int, threshold: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for offset, raw in nul_regions(data, min_length, max_length):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        printable = sum(
            character.isprintable() or character in "\r\n\t" for character in text
        )
        if printable / max(len(text), 1) < 0.95:
            continue
        score, markers = score_shell(text)
        if score < threshold:
            continue
        candidates.append({
            "offset": offset, "length": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "score": score, "markers": markers,
            "analysis": analyze_text(text), "text": text,
        })
    return candidates


def clean_for_json(candidates: list[dict[str, Any]], include_text: bool) -> list[dict[str, Any]]:
    if include_text:
        return candidates
    return [
        {key: value for key, value in candidate.items() if key != "text"}
        for candidate in candidates
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find and inspect embedded shell scripts without running them."
    )
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--min-length", type=int, default=48)
    parser.add_argument("--max-length", type=int, default=2 * 1024 * 1024)
    parser.add_argument("--threshold", type=int, default=4)
    parser.add_argument("--include-text", action="store_true")
    parser.add_argument(
        "--extract-dir", type=Path,
        help="Write extracted candidate text only when explicitly requested.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.artifact.is_file():
        print(f"error: not a regular file: {args.artifact}", file=sys.stderr)
        return 2
    try:
        data = args.artifact.read_bytes()
        candidates = scan(data, args.min_length, args.max_length, args.threshold)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.extract_dir:
        args.extract_dir.mkdir(parents=True, exist_ok=True)
        for index, candidate in enumerate(candidates):
            path = args.extract_dir / f"shell-{index:03d}-off-{candidate['offset']:x}.sh"
            path.write_text(candidate["text"], encoding="utf-8")
            candidate["output_path"] = str(path.resolve())
    if args.json:
        print(json.dumps(clean_for_json(candidates, args.include_text), ensure_ascii=False, indent=2))
    else:
        print(f"Candidates: {len(candidates)}")
        for index, candidate in enumerate(candidates):
            analysis = candidate["analysis"]
            print(
                f"[{index}] offset=0x{candidate['offset']:x} length={candidate['length']} "
                f"score={candidate['score']} sha256={candidate['sha256']}"
            )
            print(f"    functions called: {', '.join(analysis['called_functions']) or 'none'}")
            print(
                "    functions defined but not called: "
                + (", ".join(analysis["defined_but_not_called"]) or "none")
            )
            for operation in analysis["operations"]:
                print(
                    f"    line {operation['line']}: {operation['category']}: "
                    f"{operation['text']}"
                )
            if candidate.get("output_path"):
                print(f"    output={candidate['output_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
