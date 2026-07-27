# Full static-analysis workflow

## Contents

1. Intake and preservation
2. APK and app analysis
3. Remote configuration and downloads
4. Disguised Shell and protected ELF analysis
5. Zstandard unpacking and ELF reconstruction
6. ARM64 path and file-I/O tracing
7. Embedded shell and embedded ELF analysis
8. New-version comparison
9. Evidence checklist

## 1. Intake and preservation

Work from the uploaded file, not its display name.

1. Resolve the exact input path and record:
   - byte size
   - MD5, SHA-1, and SHA-256
   - file magic and file-description output
   - ZIP validity
   - ELF class, machine, entry point, and program headers
2. Never grant execute permission and never launch the sample.
3. Put carved artifacts in a task-specific temporary directory created with mktemp -d or in a user-approved workspace directory.
4. Hash every carved artifact and record its source offset and length.
5. Preserve the distinction between:
   - the uploaded outer wrapper
   - a downloaded payload
   - a decompressed image
   - a reconstructed ELF
   - each embedded ELF or shell script

Run the general inventory first:

    python3 "$SKILL_DIR/scripts/triage_artifact.py" INPUT

Use the JSON output for repeatable comparison:

    python3 "$SKILL_DIR/scripts/triage_artifact.py" INPUT \
      --json --output TRIAGE_JSON

## 2. APK and app analysis

### Archive inventory

Inspect:

- AndroidManifest.xml
- classes.dex and classesN.dex
- resources.arsc
- res/
- assets/
- lib/ABI/*.so
- signing metadata under META-INF/

The triage script decompresses and scans ZIP members without installing the APK. Use unzip -l as an independent listing check.

### Manifest and code

Use the strongest read-only tool already available:

1. jadx for Java or Kotlin call chains.
2. apktool for resources and smali.
3. apkanalyzer or aapt2 for manifest/package metadata.
4. Raw DEX strings only as a fallback.

Do not treat a URL found in a dependency, Android XML namespace, compiler build string, public-suffix database, or documentation message as an application endpoint.

Trace important strings to:

- OkHttp or URLConnection requests
- download-manager calls
- JSON parsing models
- destination-file construction
- shell execution
- native JNI methods

When obfuscation prevents decompilation, search the DEX string table and inspect methods that reference the relevant string identifier.

### Native libraries

For every APK library:

1. Run file and readelf -lW.
2. Record SONAME and DT_NEEDED entries when available.
3. Scan URL, path, command, and packer markers.
4. Trace JNI exports and native registration tables.
5. Recursively inspect embedded ELF and compressed frames.

## 3. Remote configuration and downloads

An APK may embed one stable bootstrap URL while all payload links remain server-controlled.

### Inspect the bootstrap document

Run:

    python3 "$SKILL_DIR/scripts/probe_remote_config.py" CONTROL_URL \
      --probe-links --output CONTROL_REPORT_JSON

Record:

- requested and final URL
- retrieval date and timezone
- application, kernel, driver, material-table, font, and cleanup-script versions
- every URL-bearing JSON field
- Content-Type, Content-Length, Content-Disposition, Last-Modified, ETag, and redirect chain

The probe percent-encodes Unicode URL paths before requesting them. It first requires strict JSON. If strict parsing fails only because a keyed value uses an invalid unquoted dotted version such as `2.3.4`, it quotes that value and records the repair in `json_parse_mode` and `json_repairs`. Treat any other parse failure as unresolved instead of silently applying broad JSON5 cleanup.

Describe live JSON values as mutable. Do not present them as permanently embedded in the APK.

### Download only when requested

When the user explicitly asks to download a payload:

1. Resolve headers first with curl -fSIL --location.
2. Download to an explicit task-scoped path with curl -fSL.
3. Record final filename, size, SHA-256, and real type.
4. Compare the downloaded payload against any separately uploaded artifact with cmp and SHA-256.
5. Do not execute it.

Never let a remote Content-Disposition filename determine a broad or destructive output path.

## 4. Disguised Shell and protected ELF analysis

Files ending in .sh may be:

- real shell text
- Android ARM64 PIE executable
- shared library
- ZIP or APK
- encrypted wrapper

Identify from magic bytes. If ELF:

1. Parse all PT_LOAD segments and note truncated or unusual mappings.
2. Search for known and custom packer, protector, encryption, and loader markers. Treat marker absence as inconclusive.
3. Compare program-header claims with actual file length.
4. Search for compression frame magic, embedded ELF headers, interpreter strings, and large high-entropy regions.
5. Do not trust section headers in protected or reconstructed files; program headers and code references are stronger.

Use both UTF-8 NUL strings and ASCII strings. Preserve offsets. Chinese filenames are often invisible to the default strings utility unless decoded explicitly.

## 5. Zstandard unpacking and ELF reconstruction

### Validate frames

Run:

    python3 "$SKILL_DIR/scripts/carve_zstd.py" INPUT

The script uses libzstd to validate each frame instead of accepting magic bytes alone. When extraction is needed:

    python3 "$SKILL_DIR/scripts/carve_zstd.py" INPUT --output-dir EXTRACT_DIR

Record:

- frame start
- frame end
- compressed size
- decompressed size
- compressed and decompressed SHA-256

### Reconstruct carefully

Do not apply offsets, mappings, keys, or reconstruction formulas from any other artifact without proof.

Derive reconstruction from:

- the outer or recovered ELF program headers
- loader copy loops
- mmap/mprotect sizes
- decompressor destination addresses
- explicit zero-filled gaps
- file-offset to virtual-address mapping

State the exact reconstruction formula in the analysis notes. Validate the result with:

- ELF header checks
- program-header bounds
- expected ARM64 code at the entry point
- path-string cross references
- consistent virtual addresses

If only an executable memory range is available, label it as a memory image rather than a complete ELF.

## 6. ARM64 path and file-I/O tracing

Run:

    python3 "$SKILL_DIR/scripts/arm64_path_xrefs.py" RECOVERED_ELF

Filter high-value targets when needed:

    python3 "$SKILL_DIR/scripts/arm64_path_xrefs.py" RECOVERED_ELF \
      --contains 熊大

The scanner finds direct ADR and ADRP+ADD references. Inspect surrounding instructions manually to establish:

- which argument register receives the path
- whether the call is mkdir, fopen, open, rename, unlink, access, stat, opendir, or a C++ stream constructor
- the mode or flags
- the success/failure cleanup
- the feature condition guarding the call

Map PLT stubs or indirect import-table slots before naming calls. Infer a function only when its argument pattern and multiple call sites agree.

Use call-site evidence for:

- fopen modes r, rb, w, wb, a, and variants
- open flags including O_CREAT, O_TRUNC, O_APPEND, and access mode
- mkdir mode values such as 0755 or 0700
- rename source and destination
- temporary-file cleanup
- C++ ios openmode bits
- shell redirection

Read file-io-classification.md before classifying results.

## 7. Embedded shell and embedded ELF analysis

### Shell

Run:

    python3 "$SKILL_DIR/scripts/scan_embedded_shell.py" RECOVERED_ELF

The output is candidate-oriented. Manually verify:

- whether a defined function is actually called
- whether a command is commented out
- whether a path is a source, destination, mount point, or delete target
- whether an if condition requires an existing file or directory
- whether a shell redirection can create an ordinary file on that filesystem
- whether cgroupfs, procfs, or sysfs supplies a virtual node automatically

Extract candidate text only when useful:

    python3 "$SKILL_DIR/scripts/scan_embedded_shell.py" RECOVERED_ELF \
      --extract-dir SHELL_DIR

Never execute extracted shell.

### Embedded ELF

For every validated embedded ELF:

1. Derive the exact byte extent from ELF program or section headers.
2. Extract to a task-specific path.
3. Hash it and record SONAME.
4. Inspect imports, constructors, JNI exports, direct system calls, and path strings.
5. Trace open flags and fopen modes.
6. Check anonymous mmap and prctl names; do not mistake them for filesystem files.
7. Repeat recursively if the payload contains another ELF or compressed frame.

Distinguish a file that the outer program writes to disk from behavior performed later by the loaded payload.

## 8. New-version comparison

Create one triage JSON per artifact and run:

    python3 "$SKILL_DIR/scripts/compare_triage.py" OLD_JSON NEW_JSON

Then compare behavioral evidence manually. Offset drift is expected. Focus on:

- new and removed URLs
- changed JSON keys and versions
- renamed downloads
- new storage roots
- new write primitives
- new shell commands
- embedded payload size and hash changes
- packer or compression changes
- injection target changes
- newly reachable destructive branches

Prefer the immediately preceding same-role artifact supplied by the user. If no prior artifact exists, complete a standalone analysis and say that no version diff was possible. Read the dated historical snapshot only when it provides useful hypotheses; never treat it as required or current truth.

## 9. Evidence checklist

Before answering, confirm:

- Real type and hash are stated.
- APK bootstrap URLs and live links are separated.
- Every created path has a write-side call site.
- Read-only resources are not listed as created.
- Temporary files and normal cleanup are explained.
- Rename or migration behavior is not described as generating new content.
- Virtual kernel nodes are separated from ordinary persistent files.
- Conditional scripts are not described as unconditional startup behavior.
- Embedded payloads have been audited recursively.
- Destructive strings have call-site context.
- Static-analysis limitations are stated.
