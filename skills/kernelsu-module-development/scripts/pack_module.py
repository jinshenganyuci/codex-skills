#!/usr/bin/env python3
"""Create a root-layout KernelSU module ZIP from a validated source directory."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


SKIP_PARTS = {".git", "__pycache__", ".DS_Store"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".swp"}


def should_skip(path: Path) -> bool:
    return any(part in SKIP_PARTS for part in path.parts) or path.suffix in SKIP_SUFFIXES


def write_member(archive: zipfile.ZipFile, root: Path, path: Path) -> None:
    rel = path.relative_to(root).as_posix()
    info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
    mode = path.stat().st_mode
    executable = bool(mode & stat.S_IXUSR) or path.suffix == ".sh"
    info.external_attr = ((0o100755 if executable else 0o100644) << 16)
    archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("output_zip", type=Path)
    parser.add_argument("--force", action="store_true", help="replace output_zip if it already exists")
    parser.add_argument("--skip-validate", action="store_true", help="skip static validation deliberately")
    args = parser.parse_args()

    source = args.source_dir.resolve()
    output = args.output_zip.resolve()
    if not source.is_dir():
        print("error: source_dir must be a directory", file=sys.stderr)
        return 2
    if not (source / "module.prop").is_file():
        print("error: source_dir must contain module.prop at its root", file=sys.stderr)
        return 2
    if output.exists() and not args.force:
        print(f"error: {output} exists; pass --force to replace it", file=sys.stderr)
        return 2
    if output.parent == source or source in output.parents:
        print("error: output ZIP must be outside the source directory", file=sys.stderr)
        return 2

    if not args.skip_validate:
        validator = Path(__file__).with_name("validate_module.py")
        result = subprocess.run([sys.executable, str(validator), str(source)], check=False)
        if result.returncode:
            print("error: static validation failed; fix errors or explicitly use --skip-validate", file=sys.stderr)
            return result.returncode

    paths = sorted(p for p in source.rglob("*") if p.is_file() and not should_skip(p.relative_to(source)))
    for path in paths:
        if path.is_symlink():
            print(f"error: refusing to package symlink {path.relative_to(source)}", file=sys.stderr)
            return 2

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            for path in paths:
                write_member(archive, source, path)
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(f"Packed {len(paths)} files: {output}")
    print(f"SHA256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
