#!/usr/bin/env python3
"""Locate, validate, and optionally decompress embedded Zstandard frames."""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


MAGIC = b"\x28\xb5\x2f\xfd"
CONTENTSIZE_UNKNOWN = (1 << 64) - 1
CONTENTSIZE_ERROR = (1 << 64) - 2


class Zstd:
    def __init__(self) -> None:
        library_name = ctypes.util.find_library("zstd")
        if not library_name:
            raise RuntimeError("libzstd was not found")
        self.lib = ctypes.CDLL(library_name)
        self.lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
        self.lib.ZSTD_isError.restype = ctypes.c_uint
        self.lib.ZSTD_getErrorName.argtypes = [ctypes.c_size_t]
        self.lib.ZSTD_getErrorName.restype = ctypes.c_char_p
        self.lib.ZSTD_findFrameCompressedSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        self.lib.ZSTD_findFrameCompressedSize.restype = ctypes.c_size_t
        self.lib.ZSTD_getFrameContentSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        self.lib.ZSTD_getFrameContentSize.restype = ctypes.c_ulonglong
        self.lib.ZSTD_decompress.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        self.lib.ZSTD_decompress.restype = ctypes.c_size_t
        self.has_bound = hasattr(self.lib, "ZSTD_decompressBound")
        if self.has_bound:
            self.lib.ZSTD_decompressBound.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            self.lib.ZSTD_decompressBound.restype = ctypes.c_ulonglong

    def check(self, code: int) -> int:
        if self.lib.ZSTD_isError(code):
            name = self.lib.ZSTD_getErrorName(code)
            raise RuntimeError(name.decode("utf-8", "replace"))
        return code

    @staticmethod
    def buffer(data: bytes) -> ctypes.Array[Any]:
        return ctypes.create_string_buffer(data, len(data))

    def frame_size(self, data: bytes) -> int:
        source = self.buffer(data)
        return self.check(self.lib.ZSTD_findFrameCompressedSize(source, len(data)))

    def content_size(self, frame: bytes) -> int | None:
        source = self.buffer(frame)
        value = int(self.lib.ZSTD_getFrameContentSize(source, len(frame)))
        if value == CONTENTSIZE_ERROR:
            raise RuntimeError("not a valid Zstandard frame")
        if value == CONTENTSIZE_UNKNOWN:
            return None
        return value

    def decompress(self, frame: bytes, max_output: int) -> bytes:
        source = self.buffer(frame)
        expected = self.content_size(frame)
        if expected is None:
            if not self.has_bound:
                raise RuntimeError("unknown frame size and ZSTD_decompressBound unavailable")
            expected = int(self.lib.ZSTD_decompressBound(source, len(frame)))
        if expected < 0 or expected > max_output:
            raise RuntimeError(
                f"decompressed size {expected} exceeds limit {max_output}"
            )
        destination = ctypes.create_string_buffer(max(expected, 1))
        actual = self.check(
            self.lib.ZSTD_decompress(destination, expected, source, len(frame))
        )
        return destination.raw[:actual]


def find_magic(data: bytes, start: int = 0) -> int:
    return data.find(MAGIC, start)


def scan(path: Path, library: Zstd, max_output: int, decompress: bool) -> list[dict[str, Any]]:
    data = path.read_bytes()
    frames: list[dict[str, Any]] = []
    cursor = 0
    while True:
        offset = find_magic(data, cursor)
        if offset < 0:
            break
        remaining = data[offset:]
        try:
            compressed_size = library.frame_size(remaining)
            frame = remaining[:compressed_size]
            content_size = library.content_size(frame)
            record: dict[str, Any] = {
                "offset": offset,
                "end_offset": offset + compressed_size,
                "compressed_size": compressed_size,
                "content_size": content_size,
                "compressed_sha256": hashlib.sha256(frame).hexdigest(),
                "valid": True,
            }
            if decompress:
                payload = library.decompress(frame, max_output)
                record["decompressed_size"] = len(payload)
                record["decompressed_sha256"] = hashlib.sha256(payload).hexdigest()
                record["_payload"] = payload
            frames.append(record)
            cursor = offset + max(compressed_size, 1)
        except RuntimeError as exc:
            frames.append({"offset": offset, "valid": False, "error": str(exc)})
            cursor = offset + 1
    return frames


def serializable(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in record.items() if key != "_payload"}
        for record in records
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find and optionally extract embedded Zstandard frames."
    )
    parser.add_argument("artifact", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Write each successfully decompressed frame to this directory.",
    )
    parser.add_argument(
        "--max-output",
        type=int,
        default=1024 * 1024 * 1024,
        help="Maximum decompressed bytes per frame.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.artifact.is_file():
        print(f"error: not a regular file: {args.artifact}", file=sys.stderr)
        return 2
    try:
        library = Zstd()
        records = scan(
            args.artifact,
            library,
            args.max_output,
            decompress=bool(args.output_dir),
        )
    except (OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for index, record in enumerate(records):
            payload = record.get("_payload")
            if payload is None:
                continue
            output = args.output_dir / f"frame-{index:03d}-off-{record['offset']:x}.bin"
            output.write_bytes(payload)
            record["output_path"] = str(output.resolve())
    clean = serializable(records)
    if args.json:
        print(json.dumps(clean, ensure_ascii=False, indent=2))
    else:
        if not clean:
            print("No Zstandard frame magic found.")
        for index, record in enumerate(clean):
            if not record["valid"]:
                print(f"[{index}] offset=0x{record['offset']:x} invalid: {record['error']}")
                continue
            content = record["content_size"]
            content_text = "unknown" if content is None else str(content)
            print(
                f"[{index}] offset=0x{record['offset']:x} "
                f"end=0x{record['end_offset']:x} compressed={record['compressed_size']} "
                f"content={content_text}"
            )
            if record.get("output_path"):
                print(f"    output={record['output_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
