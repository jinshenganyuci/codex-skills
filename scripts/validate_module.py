#!/usr/bin/env python3
"""Statically validate a KernelSU module directory or ZIP before flashing it."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable
from urllib.parse import urlparse


MODULE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]+$")
SCRIPTS = {
    "customize.sh",
    "post-fs-data.sh",
    "post-mount.sh",
    "service.sh",
    "boot-completed.sh",
    "late-load.sh",
    "action.sh",
    "uninstall.sh",
    "metamount.sh",
    "metainstall.sh",
    "metauninstall.sh",
}
META_HOOKS = {"metamount.sh", "metainstall.sh", "metauninstall.sh"}


@dataclass
class Finding:
    level: str
    code: str
    path: str
    message: str


class Source:
    def __init__(self, source: Path):
        self.source = source
        self.is_zip = source.is_file() and zipfile.is_zipfile(source)
        self._zip: zipfile.ZipFile | None = None
        if self.is_zip:
            self._zip = zipfile.ZipFile(source)
            self.names = {i.filename.rstrip("/") for i in self._zip.infolist() if not i.is_dir()}
        elif source.is_dir():
            self.names = {
                p.relative_to(source).as_posix()
                for p in source.rglob("*")
                if p.is_file() and ".git" not in p.parts
            }
        else:
            raise ValueError("path must be a module directory or a ZIP file")

    def close(self) -> None:
        if self._zip:
            self._zip.close()

    def read(self, name: str) -> bytes:
        if self.is_zip:
            assert self._zip
            return self._zip.read(name)
        return (self.source / name).read_bytes()

    def external_symlinks(self) -> Iterable[str]:
        if self.is_zip:
            assert self._zip
            return [
                item.filename
                for item in self._zip.infolist()
                if not item.is_dir() and stat.S_ISLNK(item.external_attr >> 16)
            ]
        result = []
        for p in self.source.rglob("*"):
            if p.is_symlink():
                result.append(p.relative_to(self.source).as_posix())
        return result


def parse_prop(raw: bytes) -> tuple[dict[str, str], list[str], bool, list[str]]:
    crlf = b"\r\n" in raw
    fields: dict[str, str] = {}
    malformed: list[str] = []
    duplicate_keys: list[str] = []
    for index, line in enumerate(raw.decode("utf-8", "replace").splitlines(), 1):
        if not line or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            malformed.append(f"line {index}: missing '='")
            continue
        key, value = line.split("=", 1)
        if not key:
            malformed.append(f"line {index}: empty key")
        else:
            if key in fields:
                duplicate_keys.append(f"line {index}: duplicate key '{key}'")
            fields[key] = value
    return fields, malformed, crlf, duplicate_keys


def looks_unsafe_zip_name(name: str) -> bool:
    path = PurePosixPath(name)
    return name.startswith("./") or path.is_absolute() or ".." in path.parts or "" in path.parts


def run_validation(source: Source) -> list[Finding]:
    findings: list[Finding] = []

    def add(level: str, code: str, path: str, message: str) -> None:
        findings.append(Finding(level, code, path, message))

    if source.is_zip:
        assert source._zip
        original_names = [item.filename for item in source._zip.infolist() if not item.is_dir()]
        if len(original_names) != len(set(original_names)):
            add("error", "ZIP_DUPLICATE", "ZIP", "ZIP has duplicate file names")
        for name in original_names:
            if looks_unsafe_zip_name(name):
                add("error", "ZIP_PATH", name, "ZIP entry is absolute or traverses outside the module root")

    for link in source.external_symlinks():
        kind = "ZIP" if source.is_zip else "local source tree"
        add("error", "SYMLINK", link, f"{kind} contains a symlink; do not package links that can escape module files")

    if "module.prop" not in source.names:
        nested = sorted(name for name in source.names if name.endswith("/module.prop"))
        if nested:
            add("error", "ROOT_LAYOUT", nested[0], "module.prop is nested; ZIP root must be module contents, not an outer folder")
        else:
            add("error", "MODULE_PROP", "module.prop", "module.prop is required at module root")
        return findings

    raw_prop = source.read("module.prop")
    props, malformed, crlf, duplicate_keys = parse_prop(raw_prop)
    if crlf:
        add("warning", "CRLF", "module.prop", "use Unix LF newlines for manager compatibility")
    for item in malformed:
        add("error", "PROP_FORMAT", "module.prop", item)
    for item in duplicate_keys:
        add("warning", "PROP_DUPLICATE", "module.prop", item)

    module_id = props.get("id", "")
    if not MODULE_ID_RE.fullmatch(module_id):
        add("error", "MODULE_ID", "module.prop", "id must match ^[A-Za-z][A-Za-z0-9._-]+$ and be at least two characters")
    for field in ("name", "version", "versionCode", "author", "description"):
        if not props.get(field):
            add("warning", "PROP_RECOMMENDED", "module.prop", f"recommended field is absent or empty: {field}")
    if props.get("versionCode") and not props["versionCode"].isdigit():
        add("error", "VERSION_CODE", "module.prop", "versionCode must be an integer")

    update_json = props.get("updateJson", "")
    if update_json:
        parsed_url = urlparse(update_json)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            add("error", "UPDATE_URL", "module.prop", "updateJson must be an absolute HTTP(S) URL")
        elif parsed_url.scheme != "https":
            add("warning", "UPDATE_HTTP", "module.prop", "use HTTPS for updateJson so release metadata cannot be modified in transit")

    for icon_field in ("actionIcon", "webuiIcon"):
        icon = props.get(icon_field)
        if not icon:
            continue
        icon_path = PurePosixPath(icon)
        if icon_path.is_absolute() or ".." in icon_path.parts:
            add("error", "ICON_PATH", "module.prop", f"{icon_field} must be a safe module-relative path")
        elif icon not in source.names:
            add("warning", "ICON_MISSING", icon, f"{icon_field} points to a missing file")

    hooks = META_HOOKS.intersection(source.names)
    is_meta = props.get("metamodule", "").lower() in {"1", "true"}
    if hooks and not is_meta:
        add("error", "META_FLAG", "module.prop", "metamodule hooks exist but metamodule=1/true is absent")
    if is_meta and "metamount.sh" not in source.names:
        add("warning", "META_MOUNT", "module.prop", "metamodule has no metamount.sh; it will not provide a mount strategy")
    if is_meta and "system" in {PurePosixPath(n).parts[0] for n in source.names}:
        add("warning", "META_SYSTEM", "system", "separate metamodule infrastructure from regular module payloads")

    top_dirs = {PurePosixPath(n).parts[0] for n in source.names if "/" in n}
    if "system" in top_dirs and not is_meta:
        add("warning", "METAMODULE_REQUIRED", "system", "system/ needs an installed compatible metamodule to be visible")
    if "system" in top_dirs and "skip_mount" in source.names:
        add("warning", "SKIP_MOUNT", "skip_mount", "system/ is present but skip_mount prevents it from being mounted")
    if "disable" in source.names:
        add("warning", "PACKAGED_DISABLED", "disable", "module will install disabled; omit this marker from a release ZIP")
    if "remove" in source.names:
        add("warning", "PACKAGED_REMOVE", "remove", "module will be removed on next boot; omit this marker from a release ZIP")
    if "webroot" in top_dirs and "webroot/index.html" not in source.names:
        add("error", "WEBUI_ENTRY", "webroot", "webroot exists but webroot/index.html is missing")
    if "initrc" in top_dirs:
        for name in source.names:
            if name.startswith("initrc/") and not name.endswith(".rc"):
                add("warning", "INITRC_SUFFIX", name, "only .rc files are injected")
        if "late-load.sh" in source.names:
            add("warning", "INITRC_LATE_LOAD", "initrc", "initrc injection is unavailable in late-load mode")

    if "install.sh" in source.names:
        add("warning", "LEGACY_INSTALLER", "install.sh", "install.sh selects legacy Magisk-style installer behavior; omit it for modern KernelSU packaging")
    for name in sorted(source.names):
        if PurePosixPath(name).name == ".replace":
            add("warning", "MAGISK_REPLACE", name, "KernelSU does not support Magisk .replace semantics")

    if "sepolicy.rule" in source.names:
        policy = source.read("sepolicy.rule").decode("utf-8", "replace")
        if re.search(r"^\s*permissive\b", policy, re.MULTILINE):
            add("warning", "SEPOLICY_PERMISSIVE", "sepolicy.rule", "avoid broad permissive policy; use the smallest rule set and test on enforcing devices")

    scan_paths = sorted(name for name in source.names if PurePosixPath(name).name in SCRIPTS or name.endswith((".sh", ".js", ".ts", ".html")))
    for name in scan_paths:
        text = source.read(name).decode("utf-8", "replace")
        if name == "post-fs-data.sh" and re.search(r"(^|[^A-Za-z_])setprop\s", text):
            add("warning", "POST_FS_SETPROP", name, "post-fs-data is blocking; use resetprop -n rather than setprop")
        if re.search(r"\bMAGISK_VER(?:_CODE)?\b", text):
            add("warning", "MAGISK_DETECT", name, "do not use MAGISK_VER* to detect KernelSU; use KSU=true")
        if module_id and f"/data/adb/modules/{module_id}" in text:
            add("warning", "HARDCODED_MODDIR", name, "derive MODDIR=${0%/*} instead of hardcoding this module path")
        if re.search(r"(?:curl|wget)[^\n|]*\|\s*(?:sh|bash)\b", text):
            add("warning", "REMOTE_EXEC", name, "do not execute downloaded content without verification")
        if re.search(r"\bsetenforce\s+0\b", text):
            add("warning", "SELINUX_DISABLE", name, "do not disable SELinux globally to make a module work")
        if re.search(r"rm\s+-[A-Za-z]*r[A-Za-z]*f?[A-Za-z]*\s+/data/adb(?:/|\s|$)", text):
            add("warning", "BROAD_DELETE", name, "do not recursively delete broad /data/adb paths from a module")
        if re.search(r"chmod\s+(?:777|[0-7]*7[0-7]*)\b", text):
            add("warning", "WORLD_WRITABLE", name, "avoid making module files world-writable")
        if re.search(r"(^|\s)REPLACE=", text):
            add("warning", "REPLACE_DRIFT", name, "current installer/source drift makes REPLACE unsafe; explicitly test opaque overlay behavior")
        if "/data/adb/service.d/" in text or "/data/adb/post-fs-data.d/" in text:
            add("warning", "GLOBAL_SCRIPT", name, "modules should not install global .d scripts; keep lifecycle scripts in the module")
        if name.startswith("webroot/") and re.search(r"https?://[^\"']+\.js", text):
            add("warning", "REMOTE_WEBUI_JS", name, "bundle and audit WebUI JavaScript locally; remote code runs beside root APIs")
        if name.startswith("webroot/") and re.search(r"<(?:script|link)\b[^>]+(?:src|href)\s*=\s*[\"']https?://", text, re.IGNORECASE):
            add("warning", "REMOTE_WEBUI_ASSET", name, "bundle WebUI assets locally; a remote asset can gain root-bridge access")

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="module directory or flashable ZIP")
    parser.add_argument("--strict", action="store_true", help="make warnings return non-zero")
    parser.add_argument(
        "--allow-warning",
        action="append",
        default=[],
        metavar="CODE",
        help="with --strict, explicitly allow one warning code (repeatable)",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable findings")
    args = parser.parse_args()

    try:
        source = Source(args.source.resolve())
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        findings = run_validation(source)
    finally:
        source.close()

    if args.json:
        print(json.dumps([asdict(item) for item in findings], ensure_ascii=False, indent=2))
    elif findings:
        for item in findings:
            print(f"{item.level.upper():7} {item.code:22} {item.path}: {item.message}")
    else:
        print("PASS: no static validation findings")

    errors = any(item.level == "error" for item in findings)
    allowed_warnings = set(args.allow_warning)
    disallowed_warnings = any(
        item.level == "warning" and item.code not in allowed_warnings for item in findings
    )
    return 1 if errors or (args.strict and disallowed_warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
