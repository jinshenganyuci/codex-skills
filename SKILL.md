---
name: kernelsu-module-development
description: "Build, migrate, audit, package, and troubleshoot complete KernelSU Manager modules. Use when creating a KernelSU module ZIP, module.prop, lifecycle scripts, systemless system overlays, metamodules, WebUI/actions/configuration, native Android payloads, or KernelSU-compatible Zygisk modules; also use for validating module compatibility, installation, update, SELinux, mount, and boot behavior."
---

# KernelSU 模块开发

交付可由 KernelSU Manager 安装、验证、回滚和维护的模块源码与根目录 ZIP。覆盖常规模块、
`system/` 修改、metamodule、启动脚本、属性/SELinux、WebUI/Action/配置、native daemon、
initrc 以及依赖独立 loader 的 Zygisk 兼容模块。

不要把 KSU 模块等同于 Magisk 模块。先按当前 KernelSU/Manager/ksud/runtime、设备 ROM、内核/KMI
和已安装 metamodule/Zygisk loader 验证；不从旧教程、文件名或 closed issue 推断兼容性。

## 先选择资料

开始任一模块任务时先读 `references/core-contract.md` 和 `references/testing-and-release.md`。再按需求
加载下列资料，不要把所有资料都塞入一次上下文。

| 需求 | 必读资料 |
|---|---|
| `/system`、vendor/product/system_ext、OverlayFS、挂载 | `references/metamodule.md` |
| WebUI、Action、模块配置、HTTP/本地 API | `references/webui-config-security.md`；需要精确 Manager 行为时再读 `references/manager-webui-contract.md` |
| native binary、daemon、NDK/Rust、Zygisk | `references/native-and-zygisk.md` |
| 迁移旧模块、设备/内核/安装/白屏/挂载故障 | `references/issue-case-ledger.md`，再检索对应逐条台账 |
| 寻找成熟实现或代码组织方式 | `references/open-source-module-patterns.md` |

## 先做需求与架构判定

在写文件前明确：目标 Android/ROM/ABI、KernelSU runtime（含是否 late-load）、目标行为、是否需要
改系统文件、是否需要长驻 native、是否需要 WebUI、是否依赖 Zygisk、是否需支持 OTA/A/B、以及
禁用/卸载/救援方式。若用户没有给出这些信息，采用保守实现并把未知前提写入 README 以外的模块
发布说明或安装日志；不要假装“全设备通用”。

| 目标 | 推荐实现 | 必要前提 |
|---|---|---|
| 正常开机任务、sysfs/命令、配置应用 | `service.sh` 或 `boot-completed.sh` | 模块私有目录、幂等和可停止 |
| 极早期准备 | `post-fs-data.sh`；late-load 时改 `late-load.sh` | 阻塞、短时；post-fs-data 不得 `setprop` |
| 属性/最小 SELinux 规则 | `system.prop` / `sepolicy.rule` | enforcing 真机验证 |
| 修改 `/system` 文件 | 常规模块 `system/` + 已验证的 metamodule | OverlayFS、真实分区路径、回滚 |
| 极早 init 服务 | `initrc/*.rc` | 非 late-load；明确 seclabel/服务失败行为 |
| 用户设置/状态页 | `webroot/index.html` + config API + 固定 shell helper | WebUI 是 root 执行面 |
| 性能/常驻/复杂协议 | ABI 选择的 native binary + `service.sh` | NDK、SELinux、退出和升级 |
| zygote/app 注入 | Zygisk payload | 单独可用的兼容 Zygisk loader，非 KSU 内建功能 |
| 给所有模块提供挂载基础设施 | metamodule | 单一活动 meta、完整 mount/rollback 测试 |

## 不可违反的契约

- 根目录直接放 `module.prop`；稳定的 `id` 必须匹配 `^[A-Za-z][A-Za-z0-9._-]+$`，发布后不改 ID；
  `versionCode` 单调递增。ZIP 不能再包一层同名目录。
- 使用 `MODDIR=${0%/*}` 推导模块路径，绝不硬编码 `/data/adb/modules/<id>`；安装/更新先进入
  staging，重启才实际切换，不直接改活动模块目录。
- 只在要覆盖 `/system` 时要求 metamodule。脚本、`system.prop`、`sepolicy.rule` 不需要 meta。
  不假设 Magisk `.replace`、`overlay.d`、Recovery 安装、Magisk mirror 或 `MAGISK_VER*` 检测可用。
- 普通工作优先 `service.sh`；`post-fs-data.sh` 和 `late-load.sh` 是阻塞阶段，不能做网络、长扫描或
  无限等待。late-load 下无 initrc 注入，`late-load.sh` 是 early-script 的替代。
- 不写全局 `/data/adb/*.d` 脚本、不递归删共享 `/data/adb`、不 `curl | sh`、不 `setenforce 0`、
  不将安装后模块打包为 `disable` 或 `remove` 状态。
- 将 root、SELinux、mount namespace、OEM 内核限制与 Zygisk loader 当作独立前提。文件存在、
  Manager 卡片出现、issue 关闭或 `su` 成功均不能单独证明目标 app 已看到功能。

## 建立工作树

在 skill 根目录执行脚手架，输出到 skill 目录以外的干净工作区。除非已核对目标确为本脚手架生成的
目录，否则不要使用 `--force`。

```sh
python3 scripts/scaffold_module.py example-module --output ./work \
  --name "Example Module" --version 0.1.0 --version-code 1 \
  --webui --action --config
```

需要 early script 时添加 `--late-load`，而不是把 late-load 逻辑塞进 `post-fs-data.sh`。需要元模块时：

```sh
python3 scripts/scaffold_module.py my-metamodule --output ./work \
  --kind metamodule --name "My Metamodule"
```

脚手架产生的是安全、可打包的 stub，不是已实现的设备功能。逐项替换 stub，保留失败信息和恢复路径。
若从第三方模块迁移，先审计其安装器、`system/` 路径、Magisk 专用变量、远程下载、SELinux、root
命令语义和 license，再选择性迁移；不要整包复制。

## 实现模块功能

### 常规脚本、属性和策略

让 shell 在 BusyBox ash 下可运行，引用每个变量并只处理自身创建的数据。先判断前置条件，再执行，
最后记录能诊断但不泄露秘密的结果。将用户输入归一化为固定枚举/范围；配置读取后再次验证。

将启动时的 property 放进 `system.prop`。将最小化的 SELinux rule 放进 `sepolicy.rule`；先用 AVC
与实际访问证明需要它，绝不以全局 permissive 代替规则。必要的 native/service 资源须按目标 ROM
验证 SELinux label，而不是从别的设备照搬 `chcon`。

### 系统文件与 metamodule

将替换内容放到 regular module 的 `system/` 下。对于 `/system/vendor`、`/system/product`、
`/system/system_ext` 等符号链接，按当前真实挂载路径布置；删除系统文件使用 OverlayFS tombstone。
使用 opaque directory/`REPLACE` 前先核对当前源码与目标 metamodule 行为，逐机验证，不能把文档的
历史自动化描述当保证。

对这类 regular module，校验器的 `METAMODULE_REQUIRED` 是应被记录的前提而不是可忽略的噪声：确认
目标设备已安装兼容且启用的 meta 后，使用 `--strict --allow-warning METAMODULE_REQUIRED`；其他 warning
仍必须为零。没有该外部前提时停止打包/发布，不要以 `--skip-validate` 绕过。

普通模块不自行实现全局 mount orchestration。若需求真的是 metamodule，遵循
`references/metamodule.md`：只能有一个活动 meta，尊重每个 regular module 的 `disable`/
`skip_mount`，成功挂载后才通知 `ksud`，并在失败时完整回滚。

### WebUI、Action 和配置

将所有 WebUI 文件本地打包在 `webroot/`，入口必须为 `index.html`。可从 `assets/webui-starter/` 复制
本地 CSP 模板。不要加载 CDN、远程 JS/CSS 或给用户任意 root terminal；页面调用的每个 root 操作
都映射到模块内固定、白名单参数、可幂等的 shell/native helper。

用 `ksud module config` 管理用户设置和临时状态。使用持久值保存偏好、`--temp` 保存本次启动状态；
对 key/value 大小、schema 和命令参数双重验证。Action 应短小、可重复运行、明确显示成功或失败，
不要让它替代长驻服务。

### Native、initrc 和 Zygisk

按 ABI 打包并明确选择 native payload，固定 NDK/Rust 工具链和最小 API，拒绝不支持 ABI。让 daemon
有单实例、日志限额、disable/remove/升级后的退出策略。只在非 late-load 的早期 init 功能确有必要时
加入 `initrc/*.rc`；描述 seclabel 与启动失败的效果。

KernelSU 没有内建 Zygisk。制作 Zygisk 模块时，把独立 Zygisk loader 的名称/版本列为安装前提，按其
公开 ABI/目录合约构建，在缺失 loader 时安全降级或清晰中止；不要把 `KSU=true` 当成注入可用的检测。

## 静态验证、打包与验收

每次修改后先校验源目录；发布前打包并再校验 ZIP。默认把 error 当阻断；只有逐项评估过的 warning
才可暂时接受，不能用 `--skip-validate` 掩盖问题。

```sh
python3 scripts/validate_module.py ./work/example-module --strict
python3 scripts/pack_module.py ./work/example-module ./dist/example-module-v1.zip
python3 scripts/validate_module.py ./dist/example-module-v1.zip --strict
sha256sum ./dist/example-module-v1.zip
```

若这是一个已经确认外部 metamodule 前提的 `system/` regular module，在两次校验都附加
`--allow-warning METAMODULE_REQUIRED`；该例外不适用于任何其他 warning。

在真机按 `references/testing-and-release.md` 覆盖冷启动、旧版→新版、禁用、卸载、失败/救援、
target app namespace/SELinux，以及所声明的 late-load、metamodule、WebUI、ABI/Zygisk、OTA/OEM。
发布 `updateJson` 时使用 HTTPS、不可回退的 `versionCode`、稳定 ZIP URL、changelog 和独立 SHA-256。

## 诊断与修订

先用 `rg -n '#<issue>|关键词' references/issue-ledgers` 查 1,102 条已关闭 issue 的逐条经验，再回到
当前源码和真实日志验证。收集 KSU/Manager/ksud/runtime/ABI/KMI、模块 ZIP hash、安装日志、logcat、
AVC/dmesg、目标进程 mountinfo、最小复现和已禁用模块列表。

区分以下结果：模块安装成功、重启切换成功、脚本执行、挂载成功、目标进程可见、目标功能成功。若出错，
先最小化为无其他模块/无 WebUI/无 Zygisk 的对照，再分别检查 metamodule、loader、ROM、OEM 内核和
用户态版本。提供准确的降级/卸载步骤，绝不因一条 closed issue 或社区 workaround 声称永久修复。
