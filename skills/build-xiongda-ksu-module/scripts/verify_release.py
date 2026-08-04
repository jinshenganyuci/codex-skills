#!/usr/bin/env python3
"""Verify a 熊大 or derived KernelSU module without executing its payloads."""

from __future__ import annotations

import argparse
import hashlib
import re
import shlex
import stat
import zipfile
from pathlib import Path, PurePosixPath


DEFAULT_MODULE_ID = "A.xiongda-onekey-start"
MODES = ("no-driver", "manual-driver", "prelaunch-driver")
PROFILES = ("xiongda-full", "minimal-action-manual-driver")
FORBIDDEN_PARTS = {".git", "__pycache__", "tests", "analysis", "node_modules"}
RUNTIME_ROOT_SCRIPTS = {
    "action.sh",
    "boot-completed.sh",
    "game_monitor.sh",
    "late-load.sh",
    "post-fs-data.sh",
    "post-mount.sh",
    "service.sh",
    "uninstall.sh",
}


def normalize_member(raw_name: str) -> tuple[str, bool]:
    if not raw_name or "\x00" in raw_name or "\\" in raw_name or raw_name.startswith("/"):
        raise ValueError(f"unsafe ZIP member name: {raw_name!r}")
    is_dir = raw_name.endswith("/")
    stripped = raw_name[:-1] if is_dir else raw_name
    parts = stripped.split("/")
    if not stripped or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe ZIP member path: {raw_name!r}")
    return "/".join(parts), is_dir


def read_zip(path: Path) -> tuple[dict[str, bytes], dict[str, int]]:
    files: dict[str, bytes] = {}
    modes: dict[str, int] = {}
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            name, is_dir = normalize_member(info.filename)
            if name in files or name in modes:
                raise ValueError(f"duplicate ZIP member: {name}")
            raw_mode = (info.external_attr >> 16) & 0xFFFF
            kind = stat.S_IFMT(raw_mode)
            if kind == stat.S_IFLNK:
                raise ValueError(f"ZIP contains symbolic link: {name}")
            if kind not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise ValueError(f"ZIP contains special file: {name}")
            if is_dir:
                modes[name] = raw_mode & 0o777
                continue
            files[name] = archive.read(info)
            modes[name] = raw_mode & 0o777
    return files, modes


def read_source(path: Path) -> tuple[dict[str, bytes], dict[str, int]]:
    files: dict[str, bytes] = {}
    modes: dict[str, int] = {}
    for item in sorted(path.rglob("*")):
        relative = item.relative_to(path).as_posix()
        if item.is_symlink():
            raise ValueError(f"source contains symbolic link: {relative}")
        if item.is_dir():
            continue
        if not item.is_file():
            raise ValueError(f"source contains special file: {relative}")
        files[relative] = item.read_bytes()
        modes[relative] = item.stat().st_mode & 0o777
    return files, modes


def parse_properties(data: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in data.decode("utf-8", "strict").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid module.prop line: {raw_line!r}")
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def as_text(files: dict[str, bytes], name: str) -> str:
    data = files.get(name)
    if data is None:
        return ""
    return data.decode("utf-8", "replace")


def is_executable(mode: int) -> bool:
    return bool(mode & 0o111)


def parse_octal_mode(value: str) -> int | None:
    if not re.fullmatch(r"0?[0-7]{3,4}", value):
        return None
    try:
        return int(value, 8)
    except ValueError:
        return None


def module_relative_path(value: str) -> str | None:
    prefixes = ("$MODPATH/", "${MODPATH}/")
    relative = next((value[len(prefix) :] for prefix in prefixes if value.startswith(prefix)), None)
    if relative is None:
        return None
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.as_posix()


def parse_install_permission_rules(customize: str) -> list[tuple[bool, str, bool]]:
    """Read narrow, non-executing set_perm rules in source order.

    KernelSU extracts ordinary module files as 0644 before sourcing customize.sh.
    Only explicit set_perm/set_perm_recursive calls count as post-install execute
    permission proof. The verifier never executes customize.sh.
    """

    rules: list[tuple[bool, str, bool]] = []
    logical_text = customize.replace("\\\r\n", " ").replace("\\\n", " ")
    for raw_line in logical_text.splitlines():
        try:
            tokens = shlex.split(raw_line, comments=True, posix=True)
        except ValueError:
            continue
        if not tokens:
            continue
        if tokens[0] == "set_perm" and len(tokens) == 5:
            relative = module_relative_path(tokens[1])
            mode = parse_octal_mode(tokens[4])
            if relative is not None and mode is not None:
                rules.append((False, relative, is_executable(mode)))
        elif tokens[0] == "set_perm_recursive" and len(tokens) == 6:
            relative = module_relative_path(tokens[1])
            file_mode = parse_octal_mode(tokens[5])
            if relative is not None and file_mode is not None:
                rules.append((True, relative.rstrip("/"), is_executable(file_mode)))
    return rules


def installed_executable(relative: str, rules: list[tuple[bool, str, bool]]) -> bool:
    executable = False  # KernelSU default for ordinary module files is 0644.
    for recursive, target, target_executable in rules:
        matches = relative == target or (recursive and relative.startswith(f"{target}/"))
        if matches:
            executable = target_executable
    return executable


def runtime_executable_files(files: dict[str, bytes]) -> list[str]:
    return sorted(
        name
        for name in files
        if name in RUNTIME_ROOT_SCRIPTS or name.startswith("bin/")
    )


def bridge_first_arguments(app: str) -> list[str]:
    arguments: list[str] = []
    pattern = re.compile(r"window\.ksu\.(?:exec|spawn)\(\s*([^,\n)]+)")
    for raw_line in app.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(("//", "*")):
            continue
        match = pattern.search(raw_line)
        if match:
            arguments.append(match.group(1).strip())
    return arguments


def has_shell_webui_command(app: str, helper: str, subcommand: str) -> bool:
    expected = f"{helper} {subcommand}"
    return any(
        "/system/bin/sh" in line and expected in line
        for line in app.splitlines()
        if not line.lstrip().startswith(("//", "*"))
    )


def webui_bin_helpers(app: str) -> set[str]:
    without_android_shell = app.replace("/system/bin/sh", "")
    return set(re.findall(r"\bbin/([A-Za-z0-9._-]+)", without_android_shell))


def normalized_delta(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise argparse.ArgumentTypeError(f"unsafe delta path: {value!r}")
    return path.as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--zip", dest="release_zip", type=Path, required=True)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--profile", choices=PROFILES, default="xiongda-full")
    parser.add_argument(
        "--action-helper",
        type=normalized_delta,
        help="module-relative Shell helper invoked by action.sh",
    )
    parser.add_argument("--driver", type=Path)
    parser.add_argument("--base-zip", type=Path)
    parser.add_argument("--expected-base-delta", action="append", default=[], type=normalized_delta)
    parser.add_argument("--module-id", default=DEFAULT_MODULE_ID)
    parser.add_argument("--autostart-default", choices=("0", "1", "any"), default="0")
    args = parser.parse_args()

    source = args.source.resolve()
    release_zip = args.release_zip.resolve()
    errors: list[str] = []
    passes: list[str] = []

    if not source.is_dir():
        parser.error(f"source directory does not exist: {source}")
    if not release_zip.is_file():
        parser.error(f"release ZIP does not exist: {release_zip}")
    if args.mode != "no-driver" and args.driver is None:
        parser.error("--driver is required for driver modes")
    if args.mode == "no-driver" and args.driver is not None:
        parser.error("--driver is not valid with no-driver mode")
    if args.expected_base_delta and args.base_zip is None:
        parser.error("--expected-base-delta requires --base-zip")
    if args.profile == "minimal-action-manual-driver" and args.mode != "manual-driver":
        parser.error("minimal-action-manual-driver profile requires --mode manual-driver")
    if args.profile == "minimal-action-manual-driver" and args.action_helper is None:
        parser.error("minimal-action-manual-driver profile requires --action-helper")

    action_helper = args.action_helper
    if action_helper is None and args.profile == "xiongda-full":
        action_helper = "bin/download-and-run"

    try:
        source_files, source_modes = read_source(source)
        zip_files, zip_modes = read_zip(release_zip)
    except (OSError, UnicodeError, ValueError, zipfile.BadZipFile) as exc:
        print(f"ERROR {exc}")
        return 1

    if source_files.keys() != zip_files.keys():
        missing = sorted(source_files.keys() - zip_files.keys())
        extra = sorted(zip_files.keys() - source_files.keys())
        errors.append(f"source/ZIP file set differs; missing={missing}, extra={extra}")
    else:
        passes.append(f"source and ZIP contain the same {len(source_files)} files")

    differing = sorted(name for name in source_files.keys() & zip_files.keys() if source_files[name] != zip_files[name])
    if differing:
        errors.append(f"source/ZIP bytes differ: {differing}")
    else:
        passes.append("every packaged member is byte-identical to source")

    if "module.prop" not in source_files:
        errors.append("module.prop is missing from module root")
        props: dict[str, str] = {}
    else:
        try:
            props = parse_properties(source_files["module.prop"])
        except (UnicodeError, ValueError) as exc:
            errors.append(str(exc))
            props = {}

    if props.get("id") != args.module_id:
        errors.append(f"module id is {props.get('id')!r}, expected {args.module_id!r}")
    version_code = props.get("versionCode", "")
    if not version_code.isdigit() or int(version_code or "0") <= 0:
        errors.append(f"invalid versionCode: {version_code!r}")
    else:
        passes.append(f"module id/versionCode accepted: {args.module_id}/{version_code}")
    passes.append(f"verification profile={args.profile}, driver mode={args.mode}")

    for marker in ("disable", "remove"):
        if marker in source_files:
            errors.append(f"release must not package {marker}")

    forbidden = sorted(
        name for name in source_files if FORBIDDEN_PARTS.intersection(PurePosixPath(name).parts)
    )
    if forbidden:
        errors.append(f"release contains development files: {forbidden}")

    if args.profile == "xiongda-full":
        config = source_files.get("autostart_enabled")
        allowed_config = {b"0\n", b"1\n"}
        if config not in allowed_config:
            errors.append("autostart_enabled must contain exactly 0 or 1 plus LF")
        elif args.autostart_default != "any" and config != f"{args.autostart_default}\n".encode():
            errors.append(
                f"autostart_enabled is {config.decode().strip()}, expected {args.autostart_default}"
            )
        else:
            passes.append(f"autostart default is {config.decode().strip()}")

        control = as_text(source_files, "bin/control")
        monitor = as_text(source_files, "game_monitor.sh")
        required_states = ("enabled-running", "enabled-stopped", "disabled-ready", "disabled-stopped")
        for state_name in required_states:
            if state_name not in control:
                errors.append(f"bin/control is missing state {state_name}")
        if "IFS= read -r" not in monitor or "autostart_enabled" not in monitor:
            errors.append("game_monitor.sh does not use the local built-in 0/1 read pattern")
        if "ksud module config" in monitor:
            errors.append("hot monitor loop must not call ksud module config")
    else:
        forbidden_full_files = (
            "autostart_enabled",
            "bin/control",
            "game_monitor.sh",
            "service.sh",
        )
        leaked = [name for name in forbidden_full_files if name in source_files]
        if leaked:
            errors.append(f"minimal profile contains unrequested full-Xiongda controls: {leaked}")
        else:
            passes.append("minimal profile omits auto-start, game monitor, service, and control switch")

    if action_helper is not None:
        action = as_text(source_files, "action.sh")
        if action_helper not in source_files:
            errors.append(f"Action helper is missing: {action_helper}")
        if action_helper not in action:
            errors.append(f"action.sh does not reference fixed helper: {action_helper}")
        elif not any(
            "/system/bin/sh" in line and action_helper in line
            for line in action.splitlines()
            if not line.lstrip().startswith("#")
        ):
            errors.append(
                f"action.sh must invoke {action_helper} through /system/bin/sh; "
                "direct module helper execution can fail after KernelSU installs it as 0644"
            )
        direct_action = re.compile(
            r"^\s*(?:exec\s+)?[\"']?\$(?:MODDIR|\{MODDIR\})/bin/"
        )
        if any(direct_action.search(line) for line in action.splitlines()):
            errors.append("action.sh directly executes a module bin helper instead of /system/bin/sh")
        elif action_helper in source_files and action_helper in action:
            passes.append(f"Action invokes {action_helper} through Android shell")

    for name, data in source_files.items():
        if not name.startswith("webroot/") or not name.endswith((".html", ".js", ".css")):
            continue
        text = data.decode("utf-8", "replace")
        if re.search(r"https?://", text, re.IGNORECASE):
            errors.append(f"remote URL found in WebUI asset: {name}")

    core_names = ("action.sh", "bin/download-and-run", "game_monitor.sh", "service.sh")
    core_text = "\n".join(as_text(source_files, name) for name in core_names)
    driver_reference = re.compile(
        r"driver-control|insmod|驱动一键刷入|DRIVER_(?:LOADER|SCRIPT)|--load",
        re.IGNORECASE,
    )

    if args.mode == "manual-driver":
        manual_error_count = len(errors)
        if driver_reference.search(core_text):
            errors.append("manual-driver mode leaked driver logic into manual/game launch chain")
        helper = as_text(source_files, "bin/driver-control")
        app = as_text(source_files, "webroot/app.js")
        page = as_text(source_files, "webroot/index.html")
        required_helper_tokens = (
            "EXPECTED_SHA256",
            "driver-webui.log",
            "mkfifo",
            "tee",
            "run)",
            "log)",
            "已执行 insmod",
            "已跳过",
        )
        for token in required_helper_tokens:
            if token not in helper:
                errors.append(f"manual driver helper is missing token: {token}")
        required_app_tokens = ("ksu.spawn", "stdout", "stderr", "exit", "error")
        for token in required_app_tokens:
            if token not in app:
                errors.append(f"WebUI streaming implementation is missing token: {token}")
        for subcommand in ("run", "log"):
            if not has_shell_webui_command(app, "bin/driver-control", subcommand):
                errors.append(
                    "WebUI must define fixed command "
                    f"/system/bin/sh <moduleDir>/bin/driver-control {subcommand}"
                )
        unsafe_bridge_arguments = [
            argument
            for argument in bridge_first_arguments(app)
            if "commands" not in argument and "/system/bin/sh" not in argument
        ]
        if unsafe_bridge_arguments:
            errors.append(
                "WebUI bridge directly receives a path/dynamic expression instead of a fixed "
                f"shell command: {unsafe_bridge_arguments}"
            )
        allowed_webui_helpers = {"driver-control"}
        if args.profile == "xiongda-full":
            allowed_webui_helpers.add("control")
            for subcommand in ("status", "enable", "disable"):
                if not has_shell_webui_command(app, "${control}", subcommand):
                    errors.append(
                        f"WebUI control command {subcommand} must invoke bin/control through /system/bin/sh"
                    )
        unexpected_webui_helpers = sorted(webui_bin_helpers(app) - allowed_webui_helpers)
        if unexpected_webui_helpers:
            errors.append(
                "WebUI references helpers outside the selected profile allowlist: "
                f"{unexpected_webui_helpers}"
            )
        if "刷入驱动" not in page:
            errors.append("WebUI page has no visible 刷入驱动 control")
        if "eval(" in helper or "sh -c" in helper:
            errors.append("manual driver helper exposes dynamic shell evaluation")
        if len(errors) == manual_error_count:
            passes.append("manual driver is isolated to a fixed WebUI helper with stream markers")

    elif args.mode == "prelaunch-driver":
        launcher = as_text(source_files, "bin/download-and-run")
        if not driver_reference.search(launcher):
            errors.append("prelaunch-driver mode has no driver call in bin/download-and-run")
        else:
            passes.append("prelaunch driver integration is present in shared launcher")

    else:
        packaged_driver_files = sorted(name for name in source_files if name.startswith("driver/"))
        if packaged_driver_files or "bin/driver-control" in source_files or driver_reference.search(core_text):
            errors.append("no-driver mode still contains a driver payload or integration")
        else:
            passes.append("no-driver mode contains no driver integration")

    if args.driver is not None:
        driver_path = args.driver.resolve()
        if not driver_path.is_file():
            parser.error(f"driver input does not exist: {driver_path}")
        driver_data = driver_path.read_bytes()
        matches = sorted(name for name in source_files if PurePosixPath(name).name == driver_path.name)
        if len(matches) != 1:
            errors.append(f"expected one packaged driver named {driver_path.name!r}, found {matches}")
        else:
            member = matches[0]
            if source_files[member] != driver_data or zip_files.get(member) != driver_data:
                errors.append("packaged driver is not byte-identical to current input")
            else:
                digest = hashlib.sha256(driver_data).hexdigest()
                passes.append(
                    f"driver is byte-identical: {member}, size={len(driver_data)}, sha256={digest}"
                )

    expected_exec = runtime_executable_files(zip_files)
    non_exec = [name for name in expected_exec if not is_executable(zip_modes.get(name, 0))]
    if non_exec:
        errors.append(f"archive metadata marks runtime scripts/helpers non-executable: {non_exec}")
    else:
        passes.append("archive metadata marks runtime scripts and bin helpers executable")

    customize = as_text(source_files, "customize.sh")
    permission_rules = parse_install_permission_rules(customize)
    missing_installed_exec = [
        name for name in runtime_executable_files(source_files) if not installed_executable(name, permission_rules)
    ]
    if missing_installed_exec:
        errors.append(
            "KernelSU installs ordinary files as 0644; customize.sh does not restore 0755 "
            f"for runtime scripts/helpers: {missing_installed_exec}"
        )
    else:
        passes.append(
            "customize.sh statically restores execute permission after KernelSU's 0644 default"
        )

    if args.base_zip is not None:
        base_path = args.base_zip.resolve()
        if not base_path.is_file():
            parser.error(f"base ZIP does not exist: {base_path}")
        try:
            base_files, _ = read_zip(base_path)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            errors.append(f"cannot read base ZIP: {exc}")
        else:
            actual_delta = {
                name
                for name in base_files.keys() | source_files.keys()
                if base_files.get(name) != source_files.get(name)
            }
            expected_delta = set(args.expected_base_delta)
            if actual_delta != expected_delta:
                errors.append(
                    "base delta mismatch; "
                    f"unexpected={sorted(actual_delta - expected_delta)}, "
                    f"missing={sorted(expected_delta - actual_delta)}"
                )
            else:
                passes.append(f"base delta matches exact approved set ({len(actual_delta)} paths)")

    release_sha = hashlib.sha256(release_zip.read_bytes()).hexdigest()
    passes.append(f"release sha256={release_sha}, size={release_zip.stat().st_size}")

    for message in passes:
        print(f"PASS {message}")
    for message in errors:
        print(f"ERROR {message}")
    if errors:
        print(f"FAIL errors={len(errors)}")
        return 1
    print("PASS KernelSU release verification complete (static only; no payload executed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
