#!/usr/bin/env python3
"""Find AArch64 ADR/ADRP+ADD references to path-like UTF-8 strings."""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Any, Iterable


ELF_MAGIC = b"\x7fELF"
PATH_MARKERS = (
    "/data/", "/sdcard/", "/storage/", "/cache/", "/dev/", "/proc/",
    "/sys/", "/system/", "/vendor/", "/apex/", "/usr/",
)
SUFFIXES = (
    ".json", ".txt", ".tmp", ".ini", ".log", ".mp4", ".png", ".ttf",
    ".otf", ".zip", ".apk", ".sh", ".so",
)
EXACT_NAMES = {"iswht", "卡密储存", "分辨率x", "分辨率y"}


def sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def iter_nul_strings(data: bytes, min_bytes: int) -> Iterable[tuple[int, str]]:
    start = 0
    for raw in data.split(b"\0"):
        if len(raw) >= min_bytes:
            try:
                value = raw.decode("utf-8")
            except UnicodeDecodeError:
                pass
            else:
                if value and sum(char.isprintable() for char in value) / len(value) >= 0.9:
                    yield start, value
        start += len(raw) + 1


def is_candidate(value: str) -> bool:
    stripped = value.strip()
    if any(marker in stripped for marker in PATH_MARKERS):
        return True
    if stripped.endswith(SUFFIXES):
        return True
    return stripped in EXACT_NAMES


def parse_load_segments(data: bytes) -> list[dict[str, int]]:
    if len(data) < 64 or not data.startswith(ELF_MAGIC):
        return []
    if data[4] != 2 or data[5] != 1:
        return []
    try:
        fields = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    except struct.error:
        return []
    machine = fields[1]
    phoff = fields[4]
    phentsize = fields[8]
    phnum = fields[9]
    if machine != 183 or phentsize < 56 or phnum > 4096:
        return []
    segments: list[dict[str, int]] = []
    for index in range(phnum):
        offset = phoff + index * phentsize
        if offset + 56 > len(data):
            break
        p_type, flags, file_offset, vaddr, _, filesz, memsz, align = struct.unpack_from(
            "<IIQQQQQQ", data, offset
        )
        if p_type != 1:
            continue
        segments.append({
            "flags": flags,
            "file_offset": file_offset,
            "vaddr": vaddr,
            "filesz": min(filesz, max(0, len(data) - file_offset)),
            "declared_filesz": filesz,
            "memsz": memsz,
            "align": align,
        })
    return segments


def offset_to_vaddr(offset: int, segments: list[dict[str, int]]) -> int | None:
    for segment in segments:
        start = segment["file_offset"]
        end = start + segment["filesz"]
        if start <= offset < end:
            return segment["vaddr"] + offset - start
    return None


def executable_ranges(data: bytes, segments: list[dict[str, int]], scan_all: bool) -> list[tuple[int, int, int]]:
    if not scan_all:
        ranges = []
        for segment in segments:
            if not segment["flags"] & 1:
                continue
            start = segment["file_offset"]
            end = start + segment["filesz"]
            ranges.append((start, end, segment["vaddr"]))
        if ranges:
            return ranges
    return [(0, len(data) - (len(data) % 4), 0)]


def decode_adr(insn: int, pc: int) -> tuple[int, int] | None:
    kind = insn & 0x9F000000
    if kind not in {0x10000000, 0x90000000}:
        return None
    immlo = (insn >> 29) & 0x3
    immhi = (insn >> 5) & 0x7FFFF
    immediate = sign_extend((immhi << 2) | immlo, 21)
    register = insn & 0x1F
    if kind == 0x90000000:
        target = (pc & ~0xFFF) + (immediate << 12)
    else:
        target = pc + immediate
    return register, target


def decode_add_immediate(insn: int) -> tuple[int, int, int] | None:
    if (insn & 0x7F000000) != 0x11000000:
        return None
    if (insn >> 30) & 1 or (insn >> 29) & 1:
        return None
    destination = insn & 0x1F
    source = (insn >> 5) & 0x1F
    immediate = (insn >> 10) & 0xFFF
    if (insn >> 22) & 1:
        immediate <<= 12
    return destination, source, immediate


def scan_xrefs(
    data: bytes,
    ranges: list[tuple[int, int, int]],
    targets: dict[int, dict[str, Any]],
    max_distance: int,
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for file_start, file_end, vaddr_start in ranges:
        states: dict[int, tuple[int, int, int]] = {}
        aligned_start = file_start + ((4 - (file_start % 4)) % 4)
        for file_offset in range(aligned_start, file_end - 3, 4):
            pc = vaddr_start + file_offset - file_start
            insn = struct.unpack_from("<I", data, file_offset)[0]
            for register, (_, previous_pc, _) in list(states.items()):
                if pc - previous_pc > max_distance:
                    del states[register]
            adr = decode_adr(insn, pc)
            if adr is not None:
                register, target = adr
                if target in targets:
                    item = targets[target]
                    found.append({
                        "xref_vaddr": pc,
                        "xref_file_offset": file_offset,
                        "target_vaddr": target,
                        "target_file_offset": item["file_offset"],
                        "value": item["value"],
                        "sequence": "adr",
                    })
                states[register] = (target, pc, file_offset)
                continue
            add = decode_add_immediate(insn)
            if add is None:
                continue
            destination, source, immediate = add
            if source not in states:
                continue
            base, base_pc, base_file_offset = states[source]
            target = base + immediate
            states[destination] = (target, pc, file_offset)
            if target not in targets:
                continue
            item = targets[target]
            found.append({
                "xref_vaddr": pc,
                "xref_file_offset": file_offset,
                "base_vaddr": base_pc,
                "base_file_offset": base_file_offset,
                "target_vaddr": target,
                "target_file_offset": item["file_offset"],
                "value": item["value"],
                "sequence": "adrp_add",
            })
    unique: dict[tuple[int, int, str], dict[str, Any]] = {}
    for item in found:
        unique[(item["xref_vaddr"], item["target_vaddr"], item["value"])] = item
    return sorted(unique.values(), key=lambda item: (item["xref_vaddr"], item["target_vaddr"]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find ARM64 references to embedded path and filename strings."
    )
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--contains", help="Only include strings containing this text.")
    parser.add_argument("--min-bytes", type=int, default=3)
    parser.add_argument("--max-distance", type=int, default=64)
    parser.add_argument(
        "--scan-all",
        action="store_true",
        help="Treat the whole file as raw AArch64 instead of ELF executable segments.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.artifact.is_file():
        print(f"error: not a regular file: {args.artifact}", file=sys.stderr)
        return 2
    data = args.artifact.read_bytes()
    segments = parse_load_segments(data)
    target_map: dict[int, dict[str, Any]] = {}
    unmapped: list[dict[str, Any]] = []
    for file_offset, value in iter_nul_strings(data, args.min_bytes):
        if not is_candidate(value):
            continue
        if args.contains and args.contains not in value:
            continue
        vaddr = offset_to_vaddr(file_offset, segments)
        if vaddr is None:
            if args.scan_all:
                vaddr = file_offset
            else:
                unmapped.append({"file_offset": file_offset, "value": value})
                continue
        target_map[vaddr] = {
            "file_offset": file_offset,
            "vaddr": vaddr,
            "value": value,
        }
    ranges = executable_ranges(data, segments, args.scan_all)
    xrefs = scan_xrefs(data, ranges, target_map, args.max_distance)
    referenced = {item["target_vaddr"] for item in xrefs}
    report = {
        "artifact": str(args.artifact.resolve()),
        "arm64_elf_segments_found": bool(segments),
        "candidate_string_count": len(target_map),
        "xref_count": len(xrefs),
        "xrefs": xrefs,
        "unreferenced_candidates": [
            item for address, item in sorted(target_map.items()) if address not in referenced
        ],
        "unmapped_candidates": unmapped,
        "notes": [
            "ADRP+ADD/ADR matches are static leads; inspect surrounding calls before classifying file behavior.",
            "A missing xref does not prove a string is unused because pointers may pass through tables.",
        ],
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Artifact: {report['artifact']}")
        print(f"Candidate strings: {report['candidate_string_count']}")
        print(f"Xrefs: {report['xref_count']}")
        for item in xrefs:
            print(
                f"- 0x{item['xref_vaddr']:x} -> 0x{item['target_vaddr']:x} "
                f"{item['value']!r} ({item['sequence']})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
