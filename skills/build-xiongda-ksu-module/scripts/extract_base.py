#!/usr/bin/env python3
"""Safely extract a root-layout 熊大 KernelSU base ZIP into a new worktree."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path


DEFAULT_MODULE_ID = "A.xiongda-onekey-start"


def parse_properties(data: bytes) -> dict[str, str]:
    text = data.decode("utf-8", "strict")
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid module.prop line: {raw_line!r}")
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def checked_name(raw_name: str) -> tuple[str, bool]:
    if not raw_name or "\x00" in raw_name or "\\" in raw_name:
        raise ValueError(f"unsafe ZIP member name: {raw_name!r}")
    if raw_name.startswith("/"):
        raise ValueError(f"absolute ZIP member path: {raw_name!r}")
    is_dir = raw_name.endswith("/")
    stripped = raw_name[:-1] if is_dir else raw_name
    parts = stripped.split("/")
    if not stripped or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe ZIP member path: {raw_name!r}")
    return "/".join(parts), is_dir


def member_kind(info: zipfile.ZipInfo) -> int:
    return stat.S_IFMT((info.external_attr >> 16) & 0xFFFF)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_zip", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--expected-id", default=DEFAULT_MODULE_ID)
    args = parser.parse_args()

    base_zip = args.base_zip.resolve()
    output_dir = args.output_dir.resolve()
    if not base_zip.is_file():
        parser.error(f"base ZIP does not exist: {base_zip}")
    if output_dir.exists():
        parser.error(f"output already exists; refusing to overwrite: {output_dir}")

    try:
        archive = zipfile.ZipFile(base_zip)
    except zipfile.BadZipFile as exc:
        parser.error(f"invalid ZIP: {exc}")

    entries: list[tuple[zipfile.ZipInfo, str, bool]] = []
    seen: set[str] = set()
    try:
        for info in archive.infolist():
            normalized, is_dir = checked_name(info.filename)
            if normalized in seen:
                raise ValueError(f"duplicate ZIP member: {normalized}")
            seen.add(normalized)

            kind = member_kind(info)
            if kind == stat.S_IFLNK:
                raise ValueError(f"symbolic links are not allowed: {normalized}")
            allowed_kinds = {0, stat.S_IFREG, stat.S_IFDIR}
            if kind not in allowed_kinds:
                raise ValueError(f"special ZIP member is not allowed: {normalized}")
            if is_dir != info.is_dir():
                raise ValueError(f"ambiguous ZIP directory member: {info.filename!r}")
            entries.append((info, normalized, is_dir))

        module_candidates = [
            info for info, name, is_dir in entries if name == "module.prop" and not is_dir
        ]
        if len(module_candidates) != 1:
            raise ValueError("module.prop must be directly at the ZIP root")
        module_info = module_candidates[0]
        props = parse_properties(archive.read(module_info))
        module_id = props.get("id", "")
        if module_id != args.expected_id:
            raise ValueError(f"expected module id {args.expected_id!r}, found {module_id!r}")

        output_dir.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{output_dir.name}.extract-", dir=output_dir.parent)
        )
        try:
            for info, normalized, is_dir in entries:
                target = temporary.joinpath(*normalized.split("/"))
                if is_dir:
                    target.mkdir(parents=True, exist_ok=True)
                    target.chmod(0o755)
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)

                archived_mode = (info.external_attr >> 16) & 0o777
                executable = bool(archived_mode & 0o111)
                target.chmod(0o755 if executable else 0o644)

            os.replace(temporary, output_dir)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
    except (OSError, UnicodeError, ValueError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}")
        return 1
    finally:
        archive.close()

    digest = hashlib.sha256(base_zip.read_bytes()).hexdigest()
    file_count = sum(1 for _, _, is_dir in entries if not is_dir)
    print(f"PASS extracted root-layout base: {output_dir}")
    print(f"module_id={module_id}")
    print(f"version={props.get('version', '')}")
    print(f"versionCode={props.get('versionCode', '')}")
    print(f"files={file_count}")
    print(f"base_sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
