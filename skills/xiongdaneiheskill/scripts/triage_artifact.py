#!/usr/bin/env python3
"""Static triage for Android APK/ZIP, ELF, and disguised binary artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit


SCHEMA_VERSION = 2
ELF_MAGIC = b"\x7fELF"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
URL_RE = re.compile(rb"https?://[^\x00-\x20\x7f\"'<>\\]{4,1024}", re.I)
PATH_PREFIXES = (
    "/data/", "/sdcard/", "/storage/", "/cache/", "/dev/", "/proc/",
    "/sys/", "/system/", "/vendor/", "/apex/",
)
INTERESTING_SUFFIXES = (
    ".json", ".txt", ".tmp", ".ini", ".log", ".mp4", ".png", ".ttf",
    ".otf", ".zip", ".apk", ".sh", ".so",
)
PACKER_MARKERS = (
    b"Virbox Protector", b"UPX!", b"Bangcle", b"ijiami", b"libjiagu",
    b"SecShell", b"DexProtector", b"AppSealing",
)
NOISE_HOSTS = {
    "schemas.android.com", "ns.adobe.com", "android.googlesource.com",
    "github.com", "goo.gle", "youtrack.jetbrains.com", "www.w3.org",
    "apache.org", "www.apache.org", "projects.eclipse.org",
}
SUSPICIOUS_COMMANDS = (
    b"rm -rf /*", b"rm -rf /dev/*", b"reboot", b"chattr +i", b"mount --bind",
)


def hashes(path: Path) -> dict[str, str]:
    digests = {
        "md5": hashlib.md5(usedforsecurity=False),
        "sha1": hashlib.sha1(usedforsecurity=False),
        "sha256": hashlib.sha256(),
    }
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            for digest in digests.values():
                digest.update(chunk)
    return {name: digest.hexdigest() for name, digest in digests.items()}


def find_all(data: bytes, needle: bytes) -> list[int]:
    offsets: list[int] = []
    start = 0
    while True:
        offset = data.find(needle, start)
        if offset < 0:
            return offsets
        offsets.append(offset)
        start = offset + 1


def clean_url(raw: bytes) -> str | None:
    raw = raw.rstrip(b".,;:!?)]}")
    value = raw.decode("utf-8", "replace")
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value


def classify_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        path = parsed.path.lower()
    except ValueError:
        return "malformed"
    if host in NOISE_HOSTS:
        return "library_or_documentation"
    if host in {"t.me", "telegram.me"}:
        return "contact"
    if path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return "image"
    if path.endswith(".json"):
        return "remote_config"
    if "/down/" in path or path.endswith((".zip", ".apk", ".sh", ".so")):
        return "download"
    return "application_or_unknown"


def iter_utf8_nul_strings(data: bytes, min_length: int = 3) -> Iterable[tuple[int, str]]:
    start = 0
    for raw in data.split(b"\0"):
        if len(raw) >= min_length:
            try:
                value = raw.decode("utf-8")
            except UnicodeDecodeError:
                pass
            else:
                printable = sum(char.isprintable() for char in value)
                if value and printable / len(value) >= 0.90:
                    yield start, value
        start += len(raw) + 1


def iter_ascii_strings(data: bytes, min_length: int = 4) -> Iterable[tuple[int, str]]:
    pattern = re.compile(rb"[\x20-\x7e]{" + str(min_length).encode() + rb",}")
    for match in pattern.finditer(data):
        yield match.start(), match.group().decode("ascii", "replace")


def path_candidates(data: bytes, limit: int = 5000) -> list[tuple[int, str]]:
    found: dict[tuple[int, str], None] = {}
    sources = list(iter_utf8_nul_strings(data))
    sources.extend(iter_ascii_strings(data))
    for offset, value in sources:
        for prefix in PATH_PREFIXES:
            index = value.find(prefix)
            if index < 0:
                continue
            candidate = value[index:].strip().splitlines()[0]
            candidate = candidate.strip("\"'()[]{}<>,;")
            if 3 <= len(candidate) <= 512:
                found[(offset + index, candidate)] = None
        stripped = value.strip()
        if stripped.endswith(INTERESTING_SUFFIXES) and len(stripped) <= 256:
            found[(offset, stripped)] = None
        if len(found) >= limit:
            break
    return sorted(found)


def interesting_filenames(data: bytes, limit: int = 1000) -> list[tuple[int, str]]:
    found: dict[tuple[int, str], None] = {}
    for offset, value in iter_utf8_nul_strings(data):
        stripped = value.strip()
        if (
            stripped.endswith(INTERESTING_SUFFIXES)
            or stripped in {"分辨率x", "分辨率y", "卡密储存", "iswht"}
        ) and len(stripped) <= 256:
            found[(offset, stripped)] = None
        if len(found) >= limit:
            break
    return sorted(found)


def parse_elf(data: bytes) -> dict[str, Any] | None:
    if len(data) < 64 or not data.startswith(ELF_MAGIC):
        return None
    elf_class = data[4]
    endian_id = data[5]
    if elf_class not in {1, 2} or endian_id not in {1, 2}:
        return {"valid_header": False}
    endian = "<" if endian_id == 1 else ">"
    try:
        if elf_class == 2:
            fields = struct.unpack_from(endian + "HHIQQQIHHHHHH", data, 16)
            (
                elf_type, machine, version, entry, phoff, shoff, flags, ehsize,
                phentsize, phnum, shentsize, shnum, shstrndx,
            ) = fields
            ph_fmt = endian + "IIQQQQQQ"
        else:
            fields = struct.unpack_from(endian + "HHIIIIIHHHHHH", data, 16)
            (
                elf_type, machine, version, entry, phoff, shoff, flags, ehsize,
                phentsize, phnum, shentsize, shnum, shstrndx,
            ) = fields
            ph_fmt = endian + "IIIIIIII"
    except struct.error:
        return {"valid_header": False, "class": elf_class, "endian": endian_id}
    segments: list[dict[str, Any]] = []
    expected_ph_size = struct.calcsize(ph_fmt)
    if phentsize >= expected_ph_size and phnum <= 4096:
        for index in range(phnum):
            position = phoff + index * phentsize
            if position + expected_ph_size > len(data):
                break
            values = struct.unpack_from(ph_fmt, data, position)
            if elf_class == 2:
                p_type, p_flags, p_offset, p_vaddr, _, p_filesz, p_memsz, p_align = values
            else:
                p_type, p_offset, p_vaddr, _, p_filesz, p_memsz, p_flags, p_align = values
            segments.append({
                "index": index, "type": p_type, "flags": p_flags,
                "offset": p_offset, "vaddr": p_vaddr, "filesz": p_filesz,
                "memsz": p_memsz, "align": p_align,
                "truncated": p_offset + p_filesz > len(data),
            })
    return {
        "valid_header": True, "class": 64 if elf_class == 2 else 32,
        "endian": "little" if endian_id == 1 else "big",
        "type": elf_type, "machine": machine, "version": version, "entry": entry,
        "program_header_offset": phoff, "program_header_count": phnum,
        "section_header_offset": shoff, "section_header_count": shnum,
        "flags": flags, "segments": segments,
    }


def file_description(path: Path) -> str | None:
    executable = shutil.which("file")
    if not executable:
        return None
    result = subprocess.run(
        [executable, "-b", str(path)], check=False, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    return result.stdout.strip() or None


def scan_blob(data: bytes, source: str) -> dict[str, Any]:
    urls: list[dict[str, Any]] = []
    for match in URL_RE.finditer(data):
        value = clean_url(match.group())
        if value:
            urls.append({
                "offset": match.start(), "value": value,
                "category": classify_url(value), "source": source,
            })
    paths = [
        {"offset": offset, "value": value, "source": source}
        for offset, value in path_candidates(data)
    ]
    filenames = [
        {"offset": offset, "value": value, "source": source}
        for offset, value in interesting_filenames(data)
    ]
    markers = [
        {"offset": offset, "value": marker.decode("ascii", "replace"), "source": source}
        for marker in PACKER_MARKERS for offset in find_all(data, marker)
    ]
    commands = [
        {"offset": offset, "value": command.decode("utf-8", "replace"), "source": source}
        for command in SUSPICIOUS_COMMANDS for offset in find_all(data, command)
    ]
    return {
        "urls": urls, "paths": paths, "filenames": filenames,
        "packer_markers": markers, "suspicious_commands": commands,
        "embedded_elf_offsets": [
            {"source": source, "offset": offset}
            for offset in find_all(data, ELF_MAGIC)
        ],
        "zstd_magic_offsets": [
            {"source": source, "offset": offset}
            for offset in find_all(data, ZSTD_MAGIC)
        ],
    }


def merge_indicators(scans: Iterable[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {
        "urls": [], "paths": [], "filenames": [], "packer_markers": [],
        "suspicious_commands": [], "embedded_elf_offsets": [],
        "zstd_magic_offsets": [],
    }
    seen: dict[str, set[tuple[Any, ...]]] = defaultdict(set)
    for scan in scans:
        for key in ("urls", "paths", "filenames", "packer_markers", "suspicious_commands"):
            for item in scan[key]:
                identity = (item.get("source"), item.get("offset"), item.get("value"))
                if identity not in seen[key]:
                    seen[key].add(identity)
                    output[key].append(item)
        for key in ("embedded_elf_offsets", "zstd_magic_offsets"):
            for item in scan[key]:
                identity = (item.get("source"), item.get("offset"))
                if identity not in seen[key]:
                    seen[key].add(identity)
                    output[key].append(item)
    return output


def scan_zip(path: Path, max_entry_bytes: int, include_entries: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metadata: dict[str, Any] = {
        "entry_count": 0, "total_uncompressed_size": 0, "dex_entries": [],
        "native_libraries": [], "selected_entries": [], "skipped_entries": [],
    }
    scans: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        metadata["entry_count"] = len(infos)
        metadata["total_uncompressed_size"] = sum(info.file_size for info in infos)
        for info in infos:
            name = info.filename
            if re.fullmatch(r"classes\d*\.dex", name):
                metadata["dex_entries"].append(name)
            if name.startswith("lib/") and name.endswith(".so"):
                metadata["native_libraries"].append({
                    "name": name, "size": info.file_size,
                    "compressed_size": info.compress_size,
                })
            if include_entries:
                metadata["selected_entries"].append({
                    "name": name, "size": info.file_size,
                    "compressed_size": info.compress_size, "crc32": f"{info.CRC:08x}",
                })
            if info.is_dir():
                continue
            if info.file_size > max_entry_bytes:
                metadata["skipped_entries"].append({
                    "name": name, "size": info.file_size, "reason": "size_limit",
                })
                continue
            try:
                member = archive.read(info)
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                metadata["skipped_entries"].append({
                    "name": name, "size": info.file_size, "reason": str(exc),
                })
                continue
            scan = scan_blob(member, f"zip:{name}")
            if any(scan[key] for key in scan):
                scans.append(scan)
    metadata["dex_entries"].sort()
    metadata["native_libraries"].sort(key=lambda item: item["name"])
    return metadata, scans


def detect_kind(path: Path, data: bytes) -> str:
    if data.startswith(ELF_MAGIC):
        return "elf"
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
            if "AndroidManifest.xml" in names and any(
                re.fullmatch(r"classes\d*\.dex", name) for name in names
            ):
                return "apk"
        except zipfile.BadZipFile:
            pass
        return "zip"
    if data.startswith(b"dex\n"):
        return "dex"
    if data.startswith(b"#!"):
        return "script"
    return "other"


def deduplicate_urls(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        key = (record.get("value", ""), record.get("category", ""))
        if key not in grouped:
            grouped[key] = {
                "value": record.get("value"), "category": record.get("category"),
                "locations": [],
            }
        grouped[key]["locations"].append({
            "source": record.get("source"), "offset": record.get("offset"),
        })
    return sorted(grouped.values(), key=lambda item: (item["category"] or "", item["value"] or ""))


def normalize_path_for_display(value: str) -> str:
    value = value.strip()
    while value and ord(value[0]) < 0x20:
        value = value[1:].lstrip()
    positions = [value.find(prefix) for prefix in PATH_PREFIXES]
    positions = [position for position in positions if position >= 0]
    if positions and min(positions) > 0:
        value = value[min(positions):]
    if value.startswith("/"):
        value = value.split(None, 1)[0]
    return value.rstrip("\"'()[]{}<>,;。")


def noisy_path_for_human(value: str, source: str) -> bool:
    if not value:
        return True
    if any(marker in source for marker in (
        "zip:META-INF/", "zip:resources.arsc", "PublicSuffixDatabase.list",
    )):
        return True
    if value.startswith(("http://", "https://")):
        return True
    if re.fullmatch(r"\.[A-Za-z0-9]{1,8}", value):
        return True
    if re.fullmatch(
        r"(?:lib(?:c|m|dl|log|z|android|EGL|GLESv[23])|%s)\.so",
        value,
    ):
        return True
    if source.startswith("zip:classes") and value.startswith(("/cache/", "/system/")):
        leaf = value.rsplit("/", 1)[-1]
        if "$" in value or ";" in value or (leaf and leaf[0].isupper()):
            return True
    return False


def build_report(path: Path, args: argparse.Namespace) -> dict[str, Any]:
    data = path.read_bytes()
    kind = detect_kind(path, data)
    scans: list[dict[str, Any]] = []
    archive_metadata = None
    if kind in {"apk", "zip"}:
        archive_metadata, archive_scans = scan_zip(
            path, args.max_entry_bytes, args.include_entries
        )
        scans.extend(archive_scans)
    else:
        scans.append(scan_blob(data, "file"))
    indicators = merge_indicators(scans)
    indicators["urls_by_value"] = deduplicate_urls(indicators["urls"])
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact": {
            "path": str(path.resolve()), "name": path.name,
            "size": path.stat().st_size, "kind": kind,
            "description": file_description(path), "hashes": hashes(path),
        },
        "elf": parse_elf(data), "archive": archive_metadata,
        "indicators": indicators,
        "notes": [
            "Static inspection only; the artifact was not executed.",
            "Candidate paths are leads, not proof of file creation. Confirm with file-I/O call sites.",
        ],
    }


def print_human(report: dict[str, Any], include_noise: bool) -> None:
    artifact = report["artifact"]
    print(f"Artifact: {artifact['path']}")
    print(f"Kind: {artifact['kind']}")
    print(f"Size: {artifact['size']}")
    print(f"SHA-256: {artifact['hashes']['sha256']}")
    if artifact.get("description"):
        print(f"Description: {artifact['description']}")
    elf = report.get("elf")
    if elf:
        print(f"ELF: class={elf.get('class')} machine={elf.get('machine')} entry=0x{elf.get('entry', 0):x}")
    archive = report.get("archive")
    if archive:
        print(f"Archive entries: {archive['entry_count']} (uncompressed {archive['total_uncompressed_size']} bytes)")
        for library in archive["native_libraries"]:
            print(f"Native library: {library['name']} ({library['size']} bytes)")
    print("\nURLs:")
    shown = 0
    for item in report["indicators"]["urls_by_value"]:
        if not include_noise and item["category"] == "library_or_documentation":
            continue
        shown += 1
        locations = ", ".join(
            f"{entry['source']}@0x{entry['offset']:x}" for entry in item["locations"][:4]
        )
        print(f"- [{item['category']}] {item['value']} ({locations})")
    if not shown:
        print("- none")
    print("\nPacker markers:")
    for item in report["indicators"]["packer_markers"]:
        print(f"- {item['value']} at {item['source']}+0x{item['offset']:x}")
    if not report["indicators"]["packer_markers"]:
        print("- none")
    print("\nEmbedded containers:")
    embedded = report["indicators"]["embedded_elf_offsets"]
    zstd = report["indicators"]["zstd_magic_offsets"]
    format_location = lambda item: f"{item['source']}@0x{item['offset']:x}"
    print("- ELF locations: " + (", ".join(format_location(item) for item in embedded) or "none"))
    print("- Zstd locations: " + (", ".join(format_location(item) for item in zstd) or "none"))
    print("\nCandidate filesystem paths:")
    candidates: list[tuple[dict[str, Any], str]] = []
    seen_values: set[str] = set()
    hidden = 0
    for item in report["indicators"]["paths"]:
        value = normalize_path_for_display(item["value"])
        if not include_noise and noisy_path_for_human(value, item["source"]):
            hidden += 1
            continue
        if value in seen_values:
            continue
        seen_values.add(value)
        candidates.append((item, value))
    for item, value in candidates[:200]:
        print(f"- {value} ({item['source']}+0x{item['offset']:x})")
    if len(candidates) > 200:
        print(f"- ... {len(candidates) - 200} more unique candidates in JSON output")
    if hidden and not include_noise:
        print(f"- ... {hidden} noisy raw records hidden; use --include-noise to show them")
    if not candidates:
        print("- none")
    print("\nSuspicious command strings:")
    for item in report["indicators"]["suspicious_commands"]:
        print(f"- {item['value']} ({item['source']}+0x{item['offset']:x})")
    if not report["indicators"]["suspicious_commands"]:
        print("- none")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Statically triage an APK, ZIP, ELF, DEX, or disguised binary."
    )
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument("--output", type=Path, help="Write the full JSON report.")
    parser.add_argument("--max-entry-bytes", type=int, default=128 * 1024 * 1024)
    parser.add_argument("--include-entries", action="store_true")
    parser.add_argument("--include-noise", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.artifact.is_file():
        print(f"error: not a regular file: {args.artifact}", file=sys.stderr)
        return 2
    try:
        report = build_report(args.artifact, args)
    except (OSError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if args.json:
        print(rendered)
    else:
        print_human(report, args.include_noise)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
