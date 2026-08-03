#!/usr/bin/env python3
"""Safely patch hash-profiled 鸭子公益内核 wrappers without executing them."""

from __future__ import annotations

import argparse
import bz2
import hashlib
import json
import os
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PROFILES = SKILL_DIR / "references" / "profiles.json"
PAYLOAD_MARKER = b"\nPAYLOAD_BELOW\n"
MAX_INPUT_SIZE = 256 * 1024 * 1024
MAX_INNER_SIZE = 512 * 1024 * 1024
AARCH64_MACHINE = 183


class PatchError(RuntimeError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_offset(value: Any) -> int:
    if isinstance(value, int):
        result = value
    elif isinstance(value, str):
        result = int(value, 0)
    else:
        raise PatchError(f"invalid offset type: {type(value).__name__}")
    if result < 0:
        raise PatchError(f"negative offset: {result}")
    return result


def parse_hex(value: Any, label: str) -> bytes:
    if not isinstance(value, str):
        raise PatchError(f"{label} must be a hex string")
    try:
        result = bytes.fromhex(value)
    except ValueError as exc:
        raise PatchError(f"invalid hex for {label}: {exc}") from exc
    if not result:
        raise PatchError(f"{label} must not be empty")
    return result


def validate_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise PatchError(f"{label} must be a 64-character SHA-256")
    lowered = value.lower()
    if any(character not in "0123456789abcdef" for character in lowered):
        raise PatchError(f"{label} is not hexadecimal")
    return lowered


def load_profiles(path: Path) -> list[dict[str, Any]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PatchError(f"cannot load profiles {path}: {exc}") from exc
    if document.get("schema_version") != 1:
        raise PatchError("unsupported profiles schema_version")
    profiles = document.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise PatchError("profiles must be a non-empty list")

    profile_ids: set[str] = set()
    accepted_hashes: set[str] = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            raise PatchError("each profile must be an object")
        profile_id = profile.get("id")
        if not isinstance(profile_id, str) or not profile_id:
            raise PatchError("profile id must be a non-empty string")
        if profile_id in profile_ids:
            raise PatchError(f"duplicate profile id: {profile_id}")
        profile_ids.add(profile_id)
        if profile.get("architecture") != "aarch64":
            raise PatchError(f"{profile_id}: only aarch64 profiles are supported")
        if not isinstance(profile.get("inner_size"), int) or profile["inner_size"] <= 0:
            raise PatchError(f"{profile_id}: invalid inner_size")

        wrapper_headers = profile.get("accepted_wrapper_header_sha256")
        if not isinstance(wrapper_headers, list) or not wrapper_headers:
            raise PatchError(
                f"{profile_id}: accepted_wrapper_header_sha256 must be a non-empty list"
            )
        normalized_headers: set[str] = set()
        for index, digest in enumerate(wrapper_headers):
            normalized = validate_sha(digest, f"{profile_id}.wrapper_header[{index}]")
            if normalized in normalized_headers:
                raise PatchError(f"{profile_id}: duplicate wrapper-header SHA-256")
            normalized_headers.add(normalized)
            wrapper_headers[index] = normalized
        profile["_accepted_wrapper_headers"] = normalized_headers

        accepted = profile.get("accepted_inner_sha256")
        if not isinstance(accepted, dict) or not accepted:
            raise PatchError(f"{profile_id}: accepted_inner_sha256 must be an object")
        for state, digest in accepted.items():
            if not isinstance(state, str) or not state:
                raise PatchError(f"{profile_id}: invalid accepted state name")
            normalized = validate_sha(digest, f"{profile_id}.{state}")
            if normalized in accepted_hashes:
                raise PatchError(f"accepted SHA-256 appears more than once: {normalized}")
            accepted_hashes.add(normalized)
            accepted[state] = normalized
        expected_complete = validate_sha(
            profile.get("expected_complete_inner_sha256"),
            f"{profile_id}.expected_complete_inner_sha256",
        )
        if expected_complete not in accepted.values():
            raise PatchError(f"{profile_id}: complete hash is not an accepted state")
        profile["expected_complete_inner_sha256"] = expected_complete

        patches = profile.get("patches")
        if not isinstance(patches, list) or not patches:
            raise PatchError(f"{profile_id}: patches must be a non-empty list")
        patch_ids: set[str] = set()
        occupied: set[int] = set()
        for patch in patches:
            patch_id = patch.get("id")
            if not isinstance(patch_id, str) or not patch_id or patch_id in patch_ids:
                raise PatchError(f"{profile_id}: invalid or duplicate patch id")
            patch_ids.add(patch_id)
            offset = parse_offset(patch.get("offset"))
            original = parse_hex(patch.get("original_hex"), f"{profile_id}.{patch_id}.original")
            replacement = parse_hex(
                patch.get("replacement_hex"), f"{profile_id}.{patch_id}.replacement"
            )
            if len(original) != len(replacement):
                raise PatchError(f"{profile_id}.{patch_id}: patch length changes")
            if original == replacement:
                raise PatchError(f"{profile_id}.{patch_id}: patch has no effect")
            site = set(range(offset, offset + len(original)))
            if occupied & site:
                raise PatchError(f"{profile_id}.{patch_id}: overlapping patch")
            occupied |= site
            if offset + len(original) > profile["inner_size"]:
                raise PatchError(f"{profile_id}.{patch_id}: patch exceeds inner_size")
            patch["_offset"] = offset
            patch["_original"] = original
            patch["_replacement"] = replacement

        invariants = profile.get("invariants", [])
        if not isinstance(invariants, list):
            raise PatchError(f"{profile_id}: invariants must be a list")
        invariant_ids: set[str] = set()
        for invariant in invariants:
            invariant_id = invariant.get("id")
            if (
                not isinstance(invariant_id, str)
                or not invariant_id
                or invariant_id in invariant_ids
            ):
                raise PatchError(f"{profile_id}: invalid or duplicate invariant id")
            invariant_ids.add(invariant_id)
            offset = parse_offset(invariant.get("offset"))
            expected = parse_hex(
                invariant.get("expected_hex"), f"{profile_id}.{invariant_id}.expected"
            )
            if offset + len(expected) > profile["inner_size"]:
                raise PatchError(f"{profile_id}.{invariant_id}: invariant exceeds inner_size")
            if occupied & set(range(offset, offset + len(expected))):
                raise PatchError(f"{profile_id}.{invariant_id}: invariant overlaps a patch")
            invariant["_offset"] = offset
            invariant["_expected"] = expected
    return profiles


def validate_elf(data: bytes) -> dict[str, Any]:
    if len(data) < 64 or data[:4] != b"\x7fELF":
        raise PatchError("inner payload is not an ELF file")
    if data[4] != 2 or data[5] != 1:
        raise PatchError("inner ELF must be 64-bit little-endian")
    machine = struct.unpack_from("<H", data, 18)[0]
    if machine != AARCH64_MACHINE:
        raise PatchError(f"inner ELF machine is {machine}, not AArch64 ({AARCH64_MACHINE})")
    entry = struct.unpack_from("<Q", data, 24)[0]
    phoff = struct.unpack_from("<Q", data, 32)[0]
    phentsize = struct.unpack_from("<H", data, 54)[0]
    phnum = struct.unpack_from("<H", data, 56)[0]
    if phnum == 0 or phentsize < 56 or phoff + phentsize * phnum > len(data):
        raise PatchError("ELF program header table is invalid or truncated")
    return {
        "class": 64,
        "endian": "little",
        "machine": machine,
        "entry": entry,
        "program_header_offset": phoff,
        "program_header_entry_size": phentsize,
        "program_header_count": phnum,
    }


def decompress_wrapper(payload: bytes) -> bytes:
    if not payload.startswith(b"BZh"):
        raise PatchError("wrapper payload is not bzip2")
    try:
        decompressor = bz2.BZ2Decompressor()
        inner = decompressor.decompress(payload, max_length=MAX_INNER_SIZE + 1)
    except OSError as exc:
        raise PatchError(f"bzip2 payload cannot be decompressed: {exc}") from exc
    if len(inner) > MAX_INNER_SIZE:
        raise PatchError("decompressed inner exceeds the safety size limit")
    if not decompressor.eof:
        raise PatchError("bzip2 payload is truncated or exceeds the safety size limit")
    if decompressor.unused_data:
        raise PatchError("wrapper has a second stream or trailing payload data")
    return inner


def identify(data: bytes) -> tuple[str, bytes, bytes | None, int | None]:
    if data.startswith(b"\x7fELF"):
        return "inner_elf", data, None, None
    marker_count = data.count(PAYLOAD_MARKER)
    if marker_count != 1:
        raise PatchError(
            "unsupported input: expected AArch64 ELF or one PAYLOAD_BELOW marker"
        )
    payload_offset = data.index(PAYLOAD_MARKER) + len(PAYLOAD_MARKER)
    header = data[:payload_offset]
    inner = decompress_wrapper(data[payload_offset:])
    return "shell_bzip2_wrapper", inner, header, payload_offset


def match_profile(
    profiles: list[dict[str, Any]], digest: str, requested_id: str | None
) -> tuple[dict[str, Any] | None, str | None]:
    candidates = profiles
    if requested_id is not None:
        candidates = [profile for profile in profiles if profile["id"] == requested_id]
        if not candidates:
            raise PatchError(f"unknown profile id: {requested_id}")
    matches: list[tuple[dict[str, Any], str]] = []
    for profile in candidates:
        for state, accepted_digest in profile["accepted_inner_sha256"].items():
            if accepted_digest == digest:
                matches.append((profile, state))
    if not matches:
        return None, None
    if len(matches) != 1:
        raise PatchError("inner SHA-256 matches more than one profile/state")
    return matches[0]


def apply_profile(
    inner: bytes, profile: dict[str, Any]
) -> tuple[bytes, list[dict[str, Any]], list[int]]:
    if len(inner) != profile["inner_size"]:
        raise PatchError("profile matched hash but inner_size differs")
    for invariant in profile["invariants"]:
        offset = invariant["_offset"]
        expected = invariant["_expected"]
        if inner[offset : offset + len(expected)] != expected:
            raise PatchError(f"invariant failed: {invariant['id']}")

    result = bytearray(inner)
    patch_records: list[dict[str, Any]] = []
    expected_changed: list[int] = []
    for patch in profile["patches"]:
        offset = patch["_offset"]
        original = patch["_original"]
        replacement = patch["_replacement"]
        current = bytes(result[offset : offset + len(original)])
        if current == original:
            status = "applied"
            result[offset : offset + len(replacement)] = replacement
            expected_changed.extend(
                offset + index
                for index, (old_byte, new_byte) in enumerate(zip(original, replacement))
                if old_byte != new_byte
            )
        elif current == replacement:
            status = "already_present"
        else:
            raise PatchError(f"patch site has unexpected bytes: {patch['id']}")
        patch_records.append(
            {
                "id": patch["id"],
                "offset": f"{offset:#x}",
                "status": status,
                "original_hex": original.hex(" "),
                "replacement_hex": replacement.hex(" "),
                "replacement_disassembly": patch.get("replacement_disassembly", ""),
            }
        )

    output = bytes(result)
    actual_changed = [
        index
        for index, (old_byte, new_byte) in enumerate(zip(inner, output))
        if old_byte != new_byte
    ]
    if actual_changed != sorted(expected_changed):
        raise PatchError("changed byte offsets differ from the reviewed patch set")
    if sha256(output) != profile["expected_complete_inner_sha256"]:
        raise PatchError("patched inner SHA-256 is not the profiled complete hash")
    for patch in profile["patches"]:
        offset = patch["_offset"]
        replacement = patch["_replacement"]
        if output[offset : offset + len(replacement)] != replacement:
            raise PatchError(f"post-patch verification failed: {patch['id']}")
    return output, patch_records, actual_changed


def atomic_write(path: Path, data: bytes, mode: int, overwrite: bool) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise PatchError(f"output exists; choose another path or use --overwrite: {path}")
    temporary = path.with_name(f".{path.name}.building.{os.getpid()}")
    if temporary.exists():
        raise PatchError(f"temporary output already exists: {temporary}")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def default_output_path(input_path: Path, kind: str) -> Path:
    if kind == "shell_bzip2_wrapper":
        stem = input_path.stem
        if "免UC_禁用强制更新" in stem:
            stem += "_已验证"
        else:
            stem += "_免UC_禁用强制更新"
        return input_path.with_name(stem + input_path.suffix)
    return input_path.with_name(input_path.name + ".免UC_禁用强制更新")


def destination_preflight(input_path: Path, destinations: list[Path], overwrite: bool) -> None:
    input_resolved = input_path.resolve()
    seen: set[Path] = set()
    for destination in destinations:
        resolved = destination.resolve()
        if resolved == input_resolved:
            raise PatchError("refusing to overwrite the input artifact")
        if resolved in seen:
            raise PatchError(f"duplicate destination: {resolved}")
        seen.add(resolved)
        if resolved.exists() and not overwrite:
            raise PatchError(
                f"destination exists; choose another path or use --overwrite: {resolved}"
            )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect or patch hash-profiled 鸭子公益内核 artifacts without executing them."
    )
    parser.add_argument("input", nargs="?", type=Path)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--profile", help="require this exact profile id")
    parser.add_argument("--inspect-only", action="store_true")
    parser.add_argument("--extract-inner", type=Path, help="write the unmodified recovered inner ELF")
    parser.add_argument("--output", type=Path, help="patched wrapper or inner output")
    parser.add_argument("--save-inner", type=Path, help="also save the patched inner ELF")
    parser.add_argument("--evidence", type=Path, help="evidence JSON path")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--list-profiles", action="store_true")
    parser.add_argument("--validate-profiles", action="store_true")
    return parser


def main() -> int:
    args = build_argument_parser().parse_args()
    profiles = load_profiles(args.profiles.resolve())
    if args.list_profiles:
        for profile in profiles:
            states = ",".join(profile["accepted_inner_sha256"].keys())
            print(f"{profile['id']}\tversion={profile.get('built_in_version', '?')}\tstates={states}")
        return 0
    if args.validate_profiles:
        print(f"profiles_valid={len(profiles)}")
        return 0
    if args.input is None:
        raise PatchError("INPUT is required unless listing or validating profiles")

    input_path = args.input.resolve()
    try:
        input_size = input_path.stat().st_size
    except OSError as exc:
        raise PatchError(f"cannot stat input {input_path}: {exc}") from exc
    if input_size <= 0 or input_size > MAX_INPUT_SIZE:
        raise PatchError("input size is empty or exceeds the safety limit")
    try:
        input_data = input_path.read_bytes()
    except OSError as exc:
        raise PatchError(f"cannot read input {input_path}: {exc}") from exc

    kind, inner, header, payload_offset = identify(input_data)
    elf = validate_elf(inner)
    inner_digest = sha256(inner)
    profile, state = match_profile(profiles, inner_digest, args.profile)
    header_digest = None if header is None else sha256(header)
    wrapper_header_profile_match = (
        None
        if header is None or profile is None
        else header_digest in profile["_accepted_wrapper_headers"]
    )
    usable_profile_match = profile is not None and wrapper_header_profile_match is not False

    inspection = {
        "sample_executed": False,
        "input": {
            "path": str(input_path),
            "kind": kind,
            "size": len(input_data),
            "sha256": sha256(input_data),
        },
        "inner": {
            "size": len(inner),
            "sha256": inner_digest,
            "elf": elf,
        },
        "wrapper": None
        if header is None
        else {
            "payload_offset": payload_offset,
            "header_size": len(header),
            "header_sha256": header_digest,
            "compression": "bzip2",
        },
        "profile": None if not usable_profile_match else profile["id"],
        "inner_profile_candidate": None if profile is None else profile["id"],
        "profile_state": state,
        "wrapper_header_profile_match": wrapper_header_profile_match,
        "known_profile_match": usable_profile_match,
    }

    if args.extract_inner is not None:
        destination_preflight(input_path, [args.extract_inner], args.overwrite)
        atomic_write(args.extract_inner, inner, 0o600, args.overwrite)
        inspection["extracted_inner"] = str(args.extract_inner.resolve())

    if args.inspect_only:
        print(json.dumps(inspection, ensure_ascii=False, indent=2))
        return 0
    if profile is None:
        print(json.dumps(inspection, ensure_ascii=False, indent=2))
        raise PatchError(
            "unknown inner SHA-256; static re-analysis and a new hash-locked profile are required"
        )
    if wrapper_header_profile_match is False:
        print(json.dumps(inspection, ensure_ascii=False, indent=2))
        raise PatchError(
            "known inner ELF is inside an unknown Shell header; audit and profile the wrapper first"
        )

    output_path = (args.output or default_output_path(input_path, kind)).resolve()
    evidence_path = (
        args.evidence or output_path.with_name(output_path.name + ".patch.json")
    ).resolve()
    destinations = [output_path, evidence_path]
    if args.save_inner is not None:
        destinations.append(args.save_inner)
    destination_preflight(input_path, destinations, args.overwrite)

    patched_inner, patch_records, changed_offsets = apply_profile(inner, profile)
    if header is None:
        output_data = patched_inner
        output_mode = 0o600
    else:
        compressed = bz2.compress(patched_inner, compresslevel=9)
        output_data = header + compressed
        output_mode = 0o755
        if output_data[:payload_offset] != header:
            raise PatchError("wrapper header changed during rebuild")
        if decompress_wrapper(output_data[payload_offset:]) != patched_inner:
            raise PatchError("rebuilt wrapper payload does not round-trip")

    evidence = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_executed": False,
        "network_accessed": False,
        "input": inspection["input"],
        "input_inner": inspection["inner"],
        "input_profile_state": state,
        "profile_id": profile["id"],
        "patches": patch_records,
        "changed_inner_byte_offsets": [f"{offset:#x}" for offset in changed_offsets],
        "output": {
            "path": str(output_path),
            "kind": kind,
            "size": len(output_data),
            "sha256": sha256(output_data),
            "inner_size": len(patched_inner),
            "inner_sha256": sha256(patched_inner),
        },
        "wrapper_header_unchanged": header is not None,
        "payload_round_trip_verified": header is not None,
        "only_profiled_inner_offsets_changed": True,
        "server_side_boundary": (
            "This patch removes the profiled client gates only; it does not defeat a future "
            "server-side authentication refusal or audit external drivers/custom kernel hooks."
        ),
    }

    atomic_write(output_path, output_data, output_mode, args.overwrite)
    if args.save_inner is not None:
        atomic_write(args.save_inner, patched_inner, 0o600, args.overwrite)
    evidence_bytes = (
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    atomic_write(evidence_path, evidence_bytes, 0o644, args.overwrite)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
