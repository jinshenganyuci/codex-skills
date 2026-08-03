---
name: patch-duck-uc-update-checks
description: Statically analyze, safely unpack, patch, rebuild, and verify current or future 鸭子公益内核 SH wrappers and ARM64 ELF payloads to remove UC Browser installation/download verification and client forced-update/version gating while preserving card-key authentication and auditing destructive behavior. Use when a user uploads or mentions 鸭子公益内核, asks for 免UC, 去掉UC验证, 去掉更新验证, 禁用强制更新, or wants the same patch migrated to a new release.
---

# Patch Duck UC and Update Checks

Treat every release as a new binary. Never assume that a filename, offset, byte
sequence, register, branch target, URL, or prior report still applies.

## Safety rules

- Never execute the wrapper, ARM64 ELF, embedded curl, downloaded code, or driver.
- Identify and hash every layer before modifying it.
- Use a known profile only when the complete inner SHA-256 and, for wrappers,
  the audited Shell-header SHA-256 both match exactly.
- Fail closed on unknown hashes, ambiguous matches, changed context, or wrong architecture.
- Preserve card-key, machine-code, signature, and server authentication logic.
- Do not call a UI-only bypass complete. Keep stored versions, integrity hashes,
  update flags, and downstream feature checks consistent.
- Do not claim that a client patch defeats a future server-side authentication refusal.

## Workflow

1. Resolve this directory as `SKILL_DIR`.
2. Inspect the artifact without writing or executing it:

   ```bash
   python3 "$SKILL_DIR/scripts/patch_duck_checks.py" INPUT --inspect-only
   ```

3. If a hash-locked profile matches, build the result:

   ```bash
   python3 "$SKILL_DIR/scripts/patch_duck_checks.py" INPUT --output OUTPUT
   ```

   Keep the emitted `.patch.json` evidence beside the result.

4. If no profile matches, extract the inner ELF for static analysis:

   ```bash
   python3 "$SKILL_DIR/scripts/patch_duck_checks.py" INPUT \
     --inspect-only --extract-inner EXTRACTED_ELF
   ```

   Read [references/reverse-engineering.md](references/reverse-engineering.md)
   completely. Re-identify both checks, prove all downstream consumers, audit
   dangerous paths, and add a new hash-locked profile only after the proof is complete.

5. Re-run the builder, disassemble every replacement, compare exact changed byte
   offsets, independently decompress the generated wrapper, and compare triage
   indicators between the unpatched and patched inner ELF.

6. Deliver the executable SH first, followed by SHA-256, evidence JSON, exact
   instruction differences, safety conclusion, and the server-side boundary.

## Required acceptance

- The UC failure exits reach the original legitimate UC-success continuation.
- A newer or malformed `updateshow` value cannot create a version mismatch in
  the client state used by the update UI and downstream feature gates.
- The wrapper header is byte-identical and its compressed payload round-trips.
- Only reviewed patch sites differ in the inner ELF.
- No URL, path, command, embedded payload, import, ELF segment, or destructive
  file-operation set changes unless separately explained and approved.
- Static analysis explicitly covers formatting, block-device writes, recovery
  wipe, root-directory deletion, remote-code execution, and external driver limits.

## Resources

- `scripts/patch_duck_checks.py`: inspect, extract, apply known profiles, rebuild,
  verify, and emit machine-readable evidence without executing the sample.
- `references/profiles.json`: inner- and wrapper-header-hash-locked patch
  profiles. Never weaken them to pattern-only matching.
- `references/reverse-engineering.md`: required process for an unknown/new release.
