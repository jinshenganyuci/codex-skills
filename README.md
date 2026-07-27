# Codex Skills

Personal collection of reusable Codex skills. Each directory under `skills/` is an independent skill and contains its own `SKILL.md` plus only the scripts, references, and assets it needs.

## Included skills

- [`kernelsu-module-development`](skills/kernelsu-module-development/) — create, validate, package, migrate, and troubleshoot KernelSU Manager modules.
- [`xiongdaneiheskill`](skills/xiongdaneiheskill/) — 通用静态分析任意版本的熊大 APP/APK、内核、驱动与伪 `.sh` 文件，定位下载网址、配置目录及完整文件落地行为。

## `xiongdaneiheskill` 中文说明

这个 Skill 用来分析现在和以后更新的任意版本熊大 APP、APK、内核、驱动及 SH 文件。它不会写死某个版本，也不会默认沿用旧版本的网址、架构、加壳方式、压缩算法、解壳偏移或配置目录；每次都会从当前上传文件重新取证。

主要能力：

- 判断文件真实类型，例如识别扩展名为 `.sh`、实际却是 Android ELF 的文件。
- 扫描 APK 的 DEX、资源、原生库和内置控制网址，并只读探测实时远程配置及下载链接。
- 分析加壳、压缩流、内嵌 ELF、内嵌 Shell 和 ARM64 路径引用。
- 区分程序确认创建、条件创建、临时创建后删除、迁移、只读、修改现有节点和删除的目录或文件。
- 同时上传新旧同类版本时，比较网址、版本、payload、文件路径、危险命令和其他行为变化。
- 识别 `rm -rf`、重启、危险挂载等高风险分支，并说明它是正常路径、功能触发还是异常分支。

安全边界：默认只做静态分析，不执行上传的 APK、ELF、SH、内嵌库或提取出的脚本。远程控制文件只读获取；只有用户明确要求时才下载其链接指向的二进制文件。

调用示例：

```text
使用 $xiongdaneiheskill 分析我上传的新版熊大 APP 和内核 SH，找出下载网址、配置目录以及它们创建的全部目录和文件。
```

## Adding a skill

Create a new directory at `skills/<skill-name>/`. Keep the required `SKILL.md` at that directory's root; keep optional reusable resources in `scripts/`, `references/`, and `assets/` inside that skill directory.
