# Codex Skills

Personal collection of reusable Codex skills. Each directory under `skills/` is an independent skill and contains its own `SKILL.md` plus only the scripts, references, and assets it needs.

## Included skills

- [`kernelsu-module-development`](skills/kernelsu-module-development/) — create, validate, package, migrate, and troubleshoot KernelSU Manager modules.
- [`build-xiongda-ksu-module`](skills/build-xiongda-ksu-module/) — 构建、迁移并验证熊大及同类内核+驱动 KernelSU 模块，防止安装后权限失效。
- [`patch-duck-uc-update-checks`](skills/patch-duck-uc-update-checks/) — 静态分析鸭子公益内核，并在完整哈希匹配时移除 UC 浏览器与客户端强制更新验证。
- [`xiongdaneiheskill`](skills/xiongdaneiheskill/) — 通用静态分析任意版本的熊大 APP/APK、内核、驱动与伪 `.sh` 文件，定位下载网址、配置目录及完整文件落地行为。

## `build-xiongda-ksu-module` 中文说明

这个 Skill 用于从用户指定的基础版本构建、迁移、测试并发布熊大 KernelSU 一键启动模块，也支持“模块卡 Action 只启动内核、WebUI 只手动刷驱动”的精简派生模块。

主要能力：

- 保留基础版本未授权文件，精确校验允许修改的差异。
- 提供本地 `0/1` 自启开关、低耗游戏监测、在线下载和 ELF/Shell 分流启动。
- 在 KernelSU WebUI 中实时显示驱动输出，并区分实际加载、重复跳过、失败和结果不明。
- 按 KernelSU 安装后普通文件为 `0644` 的实际权限模型检查 `customize.sh`，要求所有运行入口和 `bin/` helper 恢复 `0755`。
- 强制 Action/WebUI 经 `/system/bin/sh` 调用固定 helper，拒绝裸路径执行与超出用户要求的 WebUI 功能。
- 使用假驱动、假下载器和假 payload 测试，验证源码、ZIP、内置驱动和可复现构建。
- 明确区分静态检查、模拟验证、真机启动与真实驱动加载证据。

调用示例：

```text
使用 $build-xiongda-ksu-module 制作一个模块卡 Action 启动内核、WebUI 只手动刷驱动的精简模块，并完成安装后权限验证。
```

## `patch-duck-uc-update-checks` 中文说明

这个 Skill 用于静态检查鸭子公益内核的 Shell 包装器和 ARM64 ELF 内层，并移除 UC 浏览器安装/下载验证及客户端强制更新门槛。它保留卡密、机器码、签名和服务端认证逻辑。

主要安全边界：

- 不执行上传的 SH、ELF、内嵌 curl、下载代码或驱动。
- 只有内层 ELF SHA-256 和已审计包装器头部 SHA-256 同时匹配时才自动补丁。
- 新版本、未知哈希、上下文变化、尾随载荷或架构不符都会失败关闭，必须重新静态分析。
- 自动验证精确修改字节、包装器头部不变、压缩载荷往返一致，并生成 `.patch.json` 证据。
- 客户端补丁不能绕过未来可能出现的服务端认证拒绝；外部驱动和自定义内核 syscall 也不在客户端补丁证明范围内。

调用示例：

```text
使用 $patch-duck-uc-update-checks 静态分析我上传的新版鸭子公益内核 SH，去掉 UC 验证和客户端强制更新验证，并交付验证证据。
```

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
