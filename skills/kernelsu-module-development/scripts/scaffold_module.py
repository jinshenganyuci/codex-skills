#!/usr/bin/env python3
"""Create a conservative KernelSU module source tree.

The generated files are intentionally safe stubs.  They package correctly but
do not claim to implement a device-specific mount, SELinux policy, or root
feature until the developer supplies and tests that behavior.
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import sys
from pathlib import Path


MODULE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]+$")


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def write(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")
    if executable:
        path.chmod(0o755)


def standard_customise() -> str:
    return """#!/system/bin/sh
# Sourced by KernelSU's installer. Keep this file small and deterministic.
# Do not set SKIPUNZIP=1 unless this module really performs extraction and
# permission setup itself.

ui_print "- Installing ${MODID:-this KernelSU module}"

if [ "${KSU:-}" = "true" ]; then
    ui_print "- KernelSU userspace: ${KSU_VER:-unknown}; UAPI: ${KSU_UAPI_VER:-unknown}"
fi

# Add install-time compatibility checks here. Use abort "message" on failure.
# Do not create global /data/adb/*.d scripts from a module.
"""


def service_script() -> str:
    return """#!/system/bin/sh
# KernelSU runs this asynchronously in the late_start service phase.
MODDIR=${0%/*}

[ -d "$MODDIR" ] || exit 1

# Put the normal boot-time work here. Quote every path and user-controlled
# value. Do not assume a fixed /data/adb/modules/<id> path.
case "${KSU_RUNTIME_MODE:-unknown}" in
    late-load) echo "KernelSU late-load runtime detected" ;;
esac
"""


def uninstall_script() -> str:
    return """#!/system/bin/sh
# KernelSU invokes this during the next boot's staged uninstall.
MODDIR=${0%/*}

# Remove only data that this module created outside $MODDIR. Never delete a
# shared KernelSU data path. Add a narrowly scoped, tested cleanup command.
"""


def action_script() -> str:
    return """#!/system/bin/sh
MODDIR=${0%/*}

echo "Action invoked for $(basename "$MODDIR")"
# Keep actions short, auditable, and safe to run more than once.
"""


def late_load_script() -> str:
    return """#!/system/bin/sh
# This replaces post-fs-data.sh only in KernelSU late-load mode.
MODDIR=${0%/*}

if [ "${KSU_LATE_LOAD:-}" != "1" ]; then
    exit 0
fi

# Do only essential pre-mount work here. This phase is blocking.
"""


def initrc_stub() -> str:
    return """# KernelSU will merge enabled modules' initrc/*.rc files before boot.
# Keep init code minimal: a bad RC file can still run before safe mode helps.
# Add a tested Android init service or trigger below.
"""


def meta_mount_script() -> str:
    return """#!/system/bin/sh
# A metamodule owns systemless mounting for every enabled regular module.
MODDIR=${0%/*}

echo "metamount stub: implement and test a mount strategy before release" >&2

# Required design constraints:
# - honor disable and skip_mount markers for every regular module;
# - identify KernelSU-owned mounts with source/dev string "KSU";
# - mount successfully before running this notification:
#     /data/adb/ksud kernel notify-module-mounted
# - fail safely; a boot-critical mount error must not leave partial state.
exit 0
"""


def meta_install_script() -> str:
    return """#!/system/bin/sh
# Sourced by the installer for regular modules, not for this metamodule itself.
# Preflight regular-module input here, then retain the standard installer unless
# a fully tested alternate layout is required.

install_module
"""


def meta_uninstall_script() -> str:
    return """#!/system/bin/sh
# KernelSU sets MODULE_ID to the regular module being removed.
[ -n "${MODULE_ID:-}" ] || exit 0

# Release only this regular module's private mount/storage resources here.
exit 0
"""


def copy_webui(target: Path, module_name: str) -> None:
    """Copy the local-only WebUI starter, replacing its display-name placeholder."""
    starter = Path(__file__).resolve().parents[1] / "assets" / "webui-starter"
    for source in starter.rglob("*"):
        if not source.is_file():
            continue
        destination = target / source.relative_to(starter)
        content = source.read_text(encoding="utf-8")
        write(destination, content.replace("{{MODULE_NAME}}", html.escape(module_name)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module_id", help="Stable, letter-led KernelSU module ID")
    parser.add_argument("--output", type=Path, default=Path.cwd(), help="Parent output directory")
    parser.add_argument("--name", help="Display name (defaults to module ID)")
    parser.add_argument("--version", default="0.1.0")
    parser.add_argument("--version-code", default="1")
    parser.add_argument("--author", default="Your Name")
    parser.add_argument("--description", default="Describe this module in one line")
    parser.add_argument("--kind", choices=("standard", "metamodule"), default="standard")
    parser.add_argument("--webui", action="store_true", help="Add webroot/index.html")
    parser.add_argument("--action", action="store_true", help="Add action.sh")
    parser.add_argument("--config", action="store_true", help="Add a config API usage note")
    parser.add_argument("--late-load", action="store_true", help="Add late-load.sh")
    parser.add_argument("--initrc", action="store_true", help="Add a commented initrc/example.rc")
    parser.add_argument("--force", action="store_true", help="Replace an existing generated directory")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not MODULE_ID_RE.fullmatch(args.module_id):
        fail("module_id must match ^[A-Za-z][A-Za-z0-9._-]+$ and contain at least two characters")
    if not str(args.version_code).isdigit():
        fail("--version-code must be a non-negative integer")

    target = args.output.resolve() / args.module_id
    if target.exists():
        if not args.force:
            fail(f"{target} already exists; choose another --output or pass --force deliberately")
        if not target.is_dir():
            fail(f"refusing to replace non-directory {target}")
        shutil.rmtree(target)

    name = args.name or args.module_id
    lines = [
        f"id={args.module_id}",
        f"name={name}",
        f"version={args.version}",
        f"versionCode={args.version_code}",
        f"author={args.author}",
        f"description={args.description}",
    ]
    if args.kind == "metamodule":
        lines.append("metamodule=1")

    write(target / "module.prop", "\n".join(lines))
    write(target / "customize.sh", standard_customise(), executable=True)
    write(target / "service.sh", service_script(), executable=True)
    write(target / "uninstall.sh", uninstall_script(), executable=True)

    if args.action:
        write(target / "action.sh", action_script(), executable=True)
    if args.webui:
        copy_webui(target / "webroot", name)
    if args.config:
        write(
            target / "CONFIGURATION-NOTES.txt",
            "Use `ksud module config get|set|list|delete|clear` from module scripts.\n"
            "KSU_MODULE is set for module scripts; validate every value before use.\n",
        )
    if args.late_load:
        write(target / "late-load.sh", late_load_script(), executable=True)
    if args.initrc:
        write(target / "initrc" / "example.rc", initrc_stub())

    if args.kind == "metamodule":
        write(target / "metamount.sh", meta_mount_script(), executable=True)
        write(target / "metainstall.sh", meta_install_script(), executable=True)
        write(target / "metauninstall.sh", meta_uninstall_script(), executable=True)

    print(f"Created {target}")
    print("Next: implement behavior, then run validate_module.py and pack_module.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
