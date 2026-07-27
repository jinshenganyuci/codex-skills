---
name: xiongdaneiheskill
description: Statically analyze any current or future version of 熊大 Android artifacts, including APK/app packages, files named .sh that may actually be ELF executables, kernel or driver payloads, remote control documents, built-in and live download URLs, packers and compressed streams, embedded ELF and Shell payloads, cross-artifact download or launch chains, version differences, and every directory or file they create, rewrite, move, read, modify, or delete. Use whenever a user uploads or mentions a 熊大 APP/APK, 熊大内核, 熊大驱动, 熊大 SH, asks for download links or configuration locations, wants a standalone analysis, or wants any two releases compared. Never require or assume a particular historical version, URL, architecture, packer, offset, or path layout.
---

# Analyze Any Xiongda App or Kernel Release

## Safety boundary

- Perform static analysis by default. Never execute an uploaded APK, ELF, disguised .sh, embedded library, or extracted shell payload.
- Treat extensions as untrusted labels. Identify content from magic bytes and file metadata first.
- Fetch a remote JSON control document only as a read-only inspection step. Download linked binaries only when the user explicitly asks.
- Hash every input and extracted payload. Keep input, extracted output, and conclusions distinguishable.
- Do not classify a path string as created until a write primitive, output stream, rename target, shell redirection, downloader destination, or equivalent call site supports it.
- Call out destructive branches separately even when the user asks only about created files.

## Treat every release as unknown

Derive facts from the current inputs. Do not assume that a future release keeps any previously seen:

- filename extension, package name, architecture, or real file format
- bootstrap URL, remote document schema, download host, version field, or payload filename
- packer, encryption, compression algorithm, frame offset, segment map, or reconstruction formula
- storage root, configuration names, injected-library path, recording range, or embedded Shell function

Use historical findings only as search hints. A missing match to an old sample never blocks standalone analysis.

## Start every analysis

Resolve this skill directory as SKILL_DIR. Run the following separately for every uploaded, downloaded, or extracted artifact:

    python3 "$SKILL_DIR/scripts/triage_artifact.py" INPUT
    python3 "$SKILL_DIR/scripts/triage_artifact.py" INPUT --json --output TRIAGE_JSON

Record the real type, size, SHA-256, packer markers, URLs, path candidates, embedded-container offsets, and recognized compression markers. Read references/workflow.md before deeper unpacking or decompilation. If the user supplies both an APP and an SH or payload, analyze each independently and then connect the proven download, extraction, launch, and filesystem paths between them.

## Route by artifact

### APK or app package

1. Scan every ZIP member, especially classes*.dex, resources.arsc, assets, and lib/*/*.so.
2. Separate application-control URLs from Android schemas, library documentation, public-suffix data, and compiler strings.
3. Inspect remote JSON with:

       python3 "$SKILL_DIR/scripts/probe_remote_config.py" URL --probe-links

   The probe supports Unicode URLs and records narrowly repaired invalid dotted version values such as unquoted `2.3.4`; never hide a repair.
4. Confirm whether URL strings are used by downloader code. If jadx, apktool, aapt2, or apkanalyzer is available, use it read-only and trace the call chain.
5. Report both the stable bootstrap URL embedded in the APK and the mutable download URLs returned by the live control document. Include the retrieval date.

### SH, ELF, or disguised payload

1. Confirm whether it is actually text, ELF, DEX, ZIP, or another format.
2. If it is Shell text, audit it as Shell without executing it. If it is ELF, identify its architecture, packer markers, and executable mappings. Do not assume strings from the outer wrapper describe the protected program.
3. Search for compression and encryption evidence. When Zstandard frames exist, validate and carve them:

       python3 "$SKILL_DIR/scripts/carve_zstd.py" INPUT
       python3 "$SKILL_DIR/scripts/carve_zstd.py" INPUT --output-dir EXTRACT_DIR

4. Reconstruct an ELF or memory image only from proven segment mappings. Document every copied range, zero-filled gap, and virtual-address conversion.
5. When the recovered code is AArch64, find direct ARM64 references to paths and filenames:

       python3 "$SKILL_DIR/scripts/arm64_path_xrefs.py" UNPACKED_ELF

6. Extract and audit embedded shell text:

       python3 "$SKILL_DIR/scripts/scan_embedded_shell.py" UNPACKED_ELF

7. Carve embedded ELF payloads, parse each program header table, hash each payload, and recursively audit its file I/O.

## Prove filesystem behavior

Read references/file-io-classification.md before issuing a final path list.

For each path, assign exactly one primary class:

- confirmed persistent creation or rewrite
- conditional creation
- temporary creation followed by cleanup
- rename or migration target
- read-only input
- modification of an existing node
- deletion target
- unresolved candidate

Preserve conditions such as button clicks, feature flags, source-node existence, permission requirements, successful downloads, or abnormal termination. Distinguish ordinary storage from procfs, sysfs, cgroupfs, debugfs, and anonymous memory mappings.

## Analyze or compare releases

Always support standalone analysis. A previous release is optional.

When a comparable older artifact or triage report is available, generate one JSON report per artifact and compare artifacts of the same role:

    python3 "$SKILL_DIR/scripts/compare_triage.py" OLD_TRIAGE_JSON NEW_TRIAGE_JSON

Prefer comparison sources in this order:

1. The immediately previous APP, SH, kernel, or driver supplied by the user.
2. A prior triage report whose artifact role and lineage are established.
3. The optional historical snapshot in references/historical-snapshot-2026-07-27.md, only as a hypothesis map.

Do not compare an APP directly with its downloaded kernel as though they were versions of the same artifact. Instead, analyze their producer-consumer relationship.

Compare more than hashes. Check:

- bootstrap and live download URLs
- versions and filenames in remote JSON
- packer and compression layout
- executable mappings and embedded payload hashes
- directory and file behavior
- shell commands and destructive branches
- API endpoints, authentication storage, and injection targets

Treat every offset and behavioral conclusion as artifact-specific. Re-prove behavior from the new code even when strings or hashes partially match.

## Deliver the result

Use the Chinese report structure in references/report-template.md. Lead with the user-facing answer: download URL, correct configuration directory, or complete created-file list. Then provide evidence and uncertainty.

Always state:

- input filename, real type, size, and SHA-256
- whether the sample was executed
- which findings are confirmed versus candidate-only
- which paths disappear after successful cleanup
- which files contain secrets such as stored card keys
- what changed from the selected comparison source, when one exists

## Resources

- scripts/triage_artifact.py: format, hash, APK member, URL, path, packer, embedded ELF, and Zstd inventory
- scripts/probe_remote_config.py: read-only JSON control and linked-URL metadata inspection
- scripts/carve_zstd.py: validated Zstandard frame listing and optional extraction
- scripts/arm64_path_xrefs.py: dependency-free ARM64 ADR and ADRP+ADD path-reference scanner
- scripts/scan_embedded_shell.py: embedded shell discovery and operation candidates
- scripts/compare_triage.py: new-version triage comparison
- references/workflow.md: full APK and protected ELF procedure
- references/file-io-classification.md: evidence rules and false-positive controls
- references/historical-snapshot-2026-07-27.md: optional older-sample hypothesis map; never a required input
- references/historical-apk-1.2-triage.json: optional machine-readable historical APK snapshot
- references/historical-kernel-1.4.2-triage.json: optional machine-readable historical ELF snapshot
- references/report-template.md: required Chinese output format
