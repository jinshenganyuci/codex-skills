# Filesystem evidence classification

Use this reference before turning raw path strings into a filesystem-behavior report.

## Evidence order

Prefer evidence in this order:

1. A reachable call site with resolved arguments and flags.
2. A complete Shell command in a function that is actually called.
3. A downloader, archive extractor, serializer, or C++ stream whose destination is resolved.
4. A path cross-reference with an unresolved call target.
5. A standalone string.

Levels 4 and 5 remain candidates. Do not present them as created paths.

For every confirmed operation, retain the artifact, recovered-image offset or virtual address, function or command, mode or flags, reachability condition, and cleanup path.

## Primary classes

Assign each path exactly one primary class in the final inventory.

| Class | Minimum evidence | Report wording |
|---|---|---|
| Confirmed persistent creation or rewrite | Reachable `mkdir`, create-capable open, output stream, serializer, extractor, or redirection; no normal cleanup | “创建或截断重写” |
| Conditional creation | Creation evidence behind a feature, button, source-exists test, permission, successful download, or error branch | “满足条件时创建” and name the condition |
| Temporary creation followed by cleanup | Creation plus reachable rename or deletion on the normal path | “临时创建；成功后消失，异常时可能残留” |
| Rename or migration target | Destination of `rename` or `mv` using pre-existing source content | “迁移到此路径，不是凭空生成内容” |
| Read-only input | `fopen` read mode, `open` read-only, input stream, `stat`, `access`, symbol lookup, or resource load only | “只读取或检查” |
| Modification of an existing node | Write without create capability, `chmod`, `chattr`, bind mount, sysctl, procfs/sysfs/cgroup control write | “修改既有节点” |
| Deletion target | Reachable `unlink`, `remove`, `rmdir`, or `rm` | “删除目标” |
| Unresolved candidate | String or partial xref without a resolved write-side primitive | “候选，未证明创建” |

If one path has multiple behaviors, choose the class that best answers whether it is produced, then note the other operations. For example, a configuration file created by `wb` and later removable remains “confirmed persistent creation or rewrite,” with deletion noted separately.

## C and POSIX primitives

### `fopen`

- `r`, `rb`: existing file, read only; never create.
- `r+`, `rb+`, `r+b`: existing file, read/write; never create.
- `w`, `wb`, `w+`, `wb+`: create if absent and truncate if present.
- `a`, `ab`, `a+`, `ab+`: create if absent and append if present.
- `x` variants: exclusive creation where supported.

Prove that the path reaches the filename argument and that the mode reaches the same call.

### `open`, `openat`, and direct syscalls

- `O_CREAT`: create-capable. Resolve the mode argument and conditions.
- `O_EXCL | O_CREAT`: exclusive creation attempt.
- `O_TRUNC`: truncates an existing writable file; it does not create without `O_CREAT`.
- `O_APPEND`: appends; creation still requires `O_CREAT`.
- `O_WRONLY` or `O_RDWR` alone: modifies an existing file but cannot prove creation.
- `O_TMPFILE`: unnamed temporary inode, not the pathname supplied as a directory.

Decode numeric flags for the sample's Android ABI and headers instead of assuming host values when they differ.

### Directory and metadata calls

- `mkdir` or `mkdirat`: directory creation attempt. Preserve mode and parent-existence requirements.
- `chmod`, `chown`, `chattr`, `utime`, and `truncate`: modify an existing node unless a separate create operation exists.
- `stat`, `lstat`, `access`, `readlink`, `opendir`, and `readdir`: inspection only.
- `unlink`, `remove`, and `rmdir`: deletion only.

### Rename and atomic writes

`rename(source, destination)` can introduce the destination pathname, but its content comes from the source. Classify it as a migration target unless the source was created by the same atomic-write flow. For `file.tmp -> file`, report:

- temporary file: temporary creation followed by cleanup or rename;
- final file: persistent creation or rewrite through atomic replacement;
- failure behavior: whether `.tmp` can remain.

## C++ and framework primitives

- `std::ifstream`: input only unless paired with another writer.
- `std::ofstream`: normally create or truncate; resolve `app`, `ate`, and `trunc` bits.
- `std::fstream`: resolve the open mode before classifying.
- Android libc++ commonly uses `app=0x01`, `ate=0x02`, `binary=0x04`, `in=0x08`, `out=0x10`, and `trunc=0x20`; confirm against the recovered implementation before relying on numeric values.
- JSON serializers, ImGui settings, media encoders, download managers, and ZIP extractors can create files indirectly. Trace their resolved output path and the API's open policy.
- `mmap`, `ashmem`, `memfd_create`, and `prctl(PR_SET_VMA_ANON_NAME, ...)` describe memory unless a file descriptor backed by a named path is proven. Names such as `[anon:ParadiseGyroMem]` are not files.

## Shell primitives

Analyze defined functions and actual calls separately.

- `mkdir` or `install -d`: directory creation.
- `touch`: create if absent or update timestamps if present.
- `echo/printf > file`: create or truncate an ordinary file; for procfs, sysfs, or cgroupfs it usually writes an existing virtual node.
- `>> file`: create if absent or append if present.
- `cp source destination`: creates or overwrites the destination if its parent exists.
- `mv source destination`: migration target, with overwrite behavior depending on options.
- `rm` and `rmdir`: deletion targets.
- `mount --bind source target`: modifies mount state; it does not create the target.
- `2>/dev/null` is descriptor redirection to an existing device, not creation of `/dev/null`.

Ignore commented lines and function bodies that are never called. Expand variables only as far as values are statically known. Keep globs, command substitutions, and environment-dependent paths explicit.

## Filesystem type matters

Separate ordinary persistent storage from kernel-managed filesystems:

- `/data`, app-private data, and ordinary `/sdcard` files can persist.
- `/cache` is ordinary storage on some devices but may be cleared by the system or recovery.
- `/proc` and `/sys` nodes are kernel-provided; writes usually modify existing virtual state.
- `/dev/cpuset`, `/dev/cpuctl`, and other cgroup mounts create directories and kernel-generated control nodes that disappear at reboot or unmount.
- `/dev/null`, `/dev/urandom`, and similar device nodes are existing special files.
- bind mounts and debugfs mounts change the visible namespace without necessarily producing disk files.

When `mkdir` on cgroupfs causes `tasks`, `cgroup.procs`, `cpus`, or `mems` to appear, report the directory as created and the control files as kernel-generated virtual nodes.

## Conditions and reachability

Record all relevant guards:

- application start versus a user-selected feature;
- successful authentication or card-key save;
- source path already exists;
- root, SELinux, filesystem, or kernel-feature requirements;
- successful network response or extraction;
- normal path, retry path, cleanup path, or failure-only path;
- called versus merely defined Shell function;
- dynamically resolved function pointer or callback registration.

Destructive operations deserve a separate warning even if their branch is not proven reachable during normal startup. Do not claim they execute unconditionally unless control flow proves that.

## Common false positives

Do not call these created files without stronger evidence:

- APK member names and resource-table entries;
- DEX type descriptors that contain `/cache/` or `/data/` as package text;
- compiler source paths and NDK build paths;
- dependency licenses, public-suffix data, and documentation URLs;
- `DT_NEEDED` or SONAME strings;
- format strings such as `%s.so` or `/sdcard/%d.mp4` without a reachable writer;
- source paths passed to `dlopen`, image loaders, font loaders, `stat`, or read-only streams;
- anonymous memory-map labels;
- a path in an error message;
- embedded but uncalled Shell functions.

## Final audit

Before reporting “all created files,” verify:

- every created path has write-side evidence;
- dynamic filename ranges have exact bounds;
- temporary files have normal and abnormal cleanup stated;
- directory creation is not confused with a file at the same pathname;
- read-only resources are listed separately;
- procfs, sysfs, cgroupfs, debugfs, devices, and anonymous memory are labeled;
- deletion and destructive branches are not omitted;
- secrets such as stored card keys are named but never printed.
