# Unknown release reverse-engineering workflow

## Contents

1. Safety and identity
2. Wrapper recovery
3. UC verification discovery
4. Update verification discovery
5. Patch design
6. Profile creation
7. Destructive-behavior regression
8. Final acceptance

## 1. Safety and identity

Analyze every new release independently and never execute it. Inspect magic bytes
before trusting `.sh`: the file may be Shell plus a compressed ELF, a direct ELF,
or another container. Record path, size, SHA-256, real type, architecture, build
ID, wrapper header size, compression method, and every recovered payload hash.

Do not load kernel modules or run embedded curl. Do not use Android device testing
until static work and a reviewable minimal patch are complete. Audit the outer
Shell independently; a known inner ELF does not make an altered wrapper safe.

## 2. Wrapper recovery

Use the bundled script with `--inspect-only --extract-inner`. For an unsupported
wrapper, identify the extraction marker and compressor from Shell text, then
reproduce only the byte extraction/decompression operation in a host-side tool.
Never invoke the wrapper itself.

Validate the recovered object with `file`, `readelf -h -l`, SHA-256, and program
header bounds. Keep file offset and virtual address distinct; prove when they are
equal inside the executable LOAD segment before using a file offset as a branch VMA.

## 3. UC verification discovery

Start from current-sample strings only as hypotheses:

- UC package names such as `com.UCMobile` or variants;
- UC app-private databases and `file_download_record.db`;
- the UC download/help URL and nearby Chinese failure messages;
- package-manager commands, SQLite calls, path checks, and result flags.

Find every string cross-reference and trace callers. Separate independent checks:
package installation, download database existence, requested filename/version,
and any integrity or anti-tamper state derived from them.

Identify all failure assignments and the legitimate success continuation reached
when the user truly satisfies every UC condition. Prefer redirecting each proven
failure exit to that existing native success block. Do not invent a success value
without tracing how later flags, constants, and hashes are produced.

For each branch replacement:

1. Calculate the AArch64 immediate from the new instruction address.
2. Decode it independently and prove the exact destination.
3. Confirm that the destination initializes every value expected at the join.
4. Trace the result through UI and functional consumers.

Never reuse the historical offsets `0x8e0760`, `0x8e076c`, or target `0x8e0e38`
unless the complete inner SHA-256 matches its existing profile.

## 4. Update verification discovery

Find current references to `updateshow`, `updateurl`, version text, update-dialog
messages, and Android VIEW intents. Establish the exact server response field,
built-in version object, parser, parse-success flag, comparison direction, stored
current/server values, integrity hashes, and every downstream consumer.

Check for this common shape without assuming registers or offsets:

```text
parse(built_in_version, &current)
parse(server_updateshow, &server)
save(current, server, parse_ok, derived_hash)
update_required = (current < server) || !parse_ok
```

Search globally for loads of all saved values. A UI-only patch or a changed `cmp`
is insufficient when the server version was stored before that comparison or when
feature functions recompute `server <= current` and validate a hash.

Prefer changing the second parser input from the remote version object to the same
built-in version object already used by the first parser. This preserves parser
success, stored equality, original hash generation, UI state, and downstream
checks. Use this design only when current control flow proves those properties.

Confirm that `updateurl` is not automatically downloaded or executed. If it is
only used after a visible button via Android VIEW Intent, report that separately.
Do not delete shared network/authentication code merely to suppress updates.

## 5. Patch design

Use the smallest control-flow-complete patch. Preserve authentication, card key,
machine code, signature validation, network response parsing unrelated to update
gating, and all ordinary functionality.

Reject a proposed patch if any of these remain inconsistent:

- UI update-required flag;
- server-version parse-success flag;
- saved current and server versions;
- version-pair integrity hash and its complement;
- downstream feature comparisons;
- success constants or anti-tamper sentinels.

Record original/replacement bytes and disassembly. Compare the whole inner image
and require that only reviewed instruction sites differ.

## 6. Profile creation

Add a profile to `profiles.json` only after completing the analysis above.

Include:

- a unique profile ID and built-in version;
- exact inner size;
- every accepted, fully audited wrapper-header SHA-256;
- the original inner SHA-256 and expected fully patched SHA-256;
- each offset with exact original/replacement bytes and replacement disassembly;
- stable invariant bytes outside patch sites that prove the expected local layout.

Keep both inner and wrapper-header matching hash-locked. Do not add wildcard hashes,
fuzzy signatures, filename matching, or pattern-only automatic patching. If partial
patch states need support, calculate and name each complete inner SHA-256 explicitly.

Run:

```bash
python3 scripts/patch_duck_checks.py --validate-profiles
```

Then build from the original, rebuild from every accepted partial state, and prove
that all paths produce the same expected complete inner hash.

## 7. Destructive-behavior regression

Removing a gate makes the normal success path reachable, so audit that path rather
than only scanning the changed instruction. Cover main ELF, wrapper Shell, embedded
ELFs, embedded Shell, downloaded configuration, and any referenced external driver.

Explicitly search and trace:

- `mkfs`, `mke2fs`, `make_f2fs`, `wipefs`, `blkdiscard`, block ioctls;
- `dd` or writes targeting `/dev/block`, userdata, boot, recovery, or super;
- recovery wipe, factory reset, reboot and shutdown paths;
- recursive deletion, `/data` or shared-storage root deletion, globs and expansion;
- remote download followed by `chmod`, `exec`, `system`, `dlopen`, or module load;
- `remove`, `unlink`, `rmdir`, `rename`, and their resolved arguments;
- custom syscalls, `/proc/<pid>/mem`, `/dev/uinput`, SELinux changes, and `.ko` load.

Distinguish a confirmed call site from a string candidate. State the conditions,
scope, filesystem type, cleanup path, and unresolved dynamic argument. Compare the
unpatched and patched triage inventories; identical indicators plus an exact
instruction-only diff is strong regression evidence, not proof about missing
external drivers or custom kernel hooks.

## 8. Final acceptance

Independently verify all of the following:

1. Disassembly of every replacement matches the intended instruction.
2. Every UC branch reaches the legitimate native success continuation.
3. Remote newer versions cannot create inconsistent saved version state.
4. The update UI is skipped because its authoritative flag is false.
5. Downstream feature checks accept the same state and integrity hash.
6. Wrapper header bytes match the input exactly.
7. Independent decompression equals the patched inner byte-for-byte.
8. Inner differences equal only the reviewed patch byte offsets.
9. URL, path, command, import, ELF segment, and embedded-container inventories are unchanged.
10. The report states that future direct server rejection, an external `.ko`, and
    custom kernel syscall implementations remain outside the client patch proof.
