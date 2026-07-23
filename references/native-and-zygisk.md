# 原生 payload、Zygisk 兼容与复杂模块

## 选择实现层

优先用 KernelSU 自身的模块能力完成需求：生命周期 shell、`system.prop`、`sepolicy.rule`、
`system/`（配合 metamodule）、`initrc/`、WebUI 和配置 API。只有在 shell 不足以满足性能、
协议、长期守护、二进制解析或 app/zygote 进程注入时，才引入原生 payload 或 Zygisk。

| 需求 | 首选 | 额外前提 |
|---|---|---|
| 启动时设置属性/写 sysfs/固定命令 | `service.sh` 或 `boot-completed.sh` | 避免早期阻塞 |
| 重复、性能敏感或持续守护 | 模块私有 native binary + 受控 service | ABI、SELinux、重启/退出管理 |
| 替换系统文件 | regular module `system/` + compatible metamodule | 挂载、A/B、回滚 |
| 注册非常早的 init service | `initrc/*.rc` | 标准启动模式；late-load 不可用 |
| 注入 zygote/app/system_server | Zygisk module payload | KernelSU 没有内建 Zygisk，需独立兼容实现 |

不要为了“通用性”同时启动多份 shell、native daemon 和 Zygisk；每一层都会扩大启动失败、
SELinux 和兼容性风险。

## 原生 binary 的包内约定

将每个 ABI 的可执行文件放在可预测且模块私有的位置，例如：

```text
module-root/
  module.prop
  bin/
    arm64/modulectl
    armeabi-v7a/modulectl
    x86_64/modulectl
  service.sh
  uninstall.sh
```

`service.sh` 根据 `getprop ro.product.cpu.abi` 或安装阶段的 `ARCH` 选择**明确的** ABI，验证
文件存在、可执行、哈希/版本符合预期，再以绝对路径启动。不要从网络下载可执行文件，也不要
把可写配置目录加入 `PATH`。编译时固定 NDK/toolchain/依赖版本，记录 ABI 与最小 API；发布 ZIP
中只放最终需要的 stripped payload，不放私钥、构建缓存、host binary 或 `target/`。

初始脚本可遵循：

```sh
MODDIR=${0%/*}
abi=$(getprop ro.product.cpu.abi)
case "$abi" in
  arm64-v8a) bin="$MODDIR/bin/arm64/modulectl" ;;
  armeabi-v7a) bin="$MODDIR/bin/armeabi-v7a/modulectl" ;;
  x86_64) bin="$MODDIR/bin/x86_64/modulectl" ;;
  *) echo "unsupported ABI: $abi" >&2; exit 64 ;;
esac
[ -x "$bin" ] || { echo "missing payload" >&2; exit 65; }
exec "$bin" --module-dir "$MODDIR" run
```

示例的参数本身仍要被 native 程序严格处理；模块路径不要从 UI 或可写文件直接取值。若 binary
需要 root，仅让它执行最少权限的固定工作；审计其文件权限、socket、pidfile、日志轮转及退出
行为。不可假定所有 OEM 内核、SELinux policy 或 mount namespace 一致。

Rust/C/C++ 都可行。Rust 项目可用 `cargo-ndk`，C/C++ 可用 Android NDK + CMake；两者均须在
每个发行 ABI 的真实 Android 环境进行 smoke test。`meta-hybrid_mount` 和
`meta-magic_mount-rs` 是 Rust/NDK 的复杂挂载样本，但不要复制其 mount 权限模型到普通模块。

## Native service 的生命周期

- 正常后台工作放 `service.sh`；它是非阻塞阶段。启动前处理旧 pidfile、崩溃残留与重复启动，
  并在必要时记录版本化、限量的日志。
- 仅在确实需要比 zygote 更早的准备工作时使用 `post-fs-data.sh` 或 `late-load.sh`；它们阻塞，
  不能做网络、长扫描或等待 daemon；`post-fs-data.sh` 不可用 `setprop`。
- 要先于 framework 注册 Android init service 时使用模块 `initrc/*.rc`，并显式配置 user/group/
  seclabel；late-load 下该机制不可用，须提供降级或明确拒绝。
- `uninstall.sh` 仅清理本模块创建的外部资源。让 daemon 能在 `disable`、`remove`、升级和异常
  中安全退出；不要 `killall` 他人的进程或删除共享 `/data/adb` 目录。
- 可执行文件、socket 与数据的 SELinux label 必须在目标 ROM 实测。遇到 `avc: denied`，先最小化
  权限/路径和调用，再经 `sepolicy.rule` 做最小规则，而不是普遍 permissive 或 broad allow。

## Zygisk：KernelSU 的边界与正确集成

KernelSU 的官方模块文档明确写明：核心**没有内建 Zygisk**。因此一个 Zygisk module 在 KernelSU
上需要用户先安装且启用兼容 Zygisk 实现（例如其自带文档声明支持 KernelSU 的实现）。模块作者
必须在说明、安装前检查和错误信息中把它列为依赖；不能把 `KSU=true` 当作 Zygisk 已可用的证明。

要制作 Zygisk payload 时，遵循所选 Zygisk 实现和上游 Zygisk module sample 的 ABI/目录/入口合约；
不要凭 Magisk 的内部实现猜测。把 Zygisk payload 当成一个**兼容层模块**发布：

1. 保留标准 `module.prop` 和可恢复 `customize.sh`；不依赖 Recovery 安装。
2. 在安装期检测 CPU ABI、Android API、所需 Zygisk 实现/版本；信息不足时中止并写出检查命令，
   不注入“试试看”。
3. 只将需要的 `.so`、DEX 和配置加入 ZIP；每个 ABI/进程分支显式管理；不要把 payload 或资源
   放到 `system/` 作为注入手段。
4. 在 Manager/KSU、Zygisk 实现、Android 版本、ABI 和目标进程的组合矩阵中实测加载、禁用、
   卸载、更新和 crash recovery。
5. 保持 Zygisk payload、普通启动脚本和 WebUI 的配置 schema 一致；如果 Zygisk 不可用，选择
   scripts-only 降级或有解释地拒绝，而不是半安装。

Sui、device_faker、PlayIntegrityFork 的公开说明展示“KernelSU + 独立 Zygisk 实现”的依赖关系；
它们是复杂 Zygisk module 的架构参考，不是 KernelSU 原生 API 的证据。ZygiskNext 当前本地样本
README 标注为保留权利，不能把其源码当成可复制/再发布的开源模板，只能作为兼容目标。

## 复杂模块的测试矩阵

每次 release 至少覆盖：

| 维度 | 最少样本 |
|---|---|
| CPU ABI | 所有打包 ABI；无对应 ABI 时应干净失败 |
| KernelSU runtime | 标准 LKM/所支持 runtime；如声明 late-load，专测 late-load |
| Android/ROM | 最低支持 API、一台接近最新 API 的设备、至少一个非同 OEM ROM |
| 生命周期 | 初装、覆盖更新、禁用、启用、卸载、A/B OTA（若使用挂载/早期启动） |
| 安全 | enforcing SELinux、无网络、损坏配置、无 Zygisk 依赖、目标进程崩溃 |
| Zygisk | 支持的 loader/version、DenyList/排除策略、目标 app/system_server 各一条 |

收集 Manager/ksud 日志、module logs、`logcat`、相关 `dmesg`/`avc` 和 `/proc/*/mountinfo`；不要因
“模块已安装”或 issue 被关闭就宣称注入或挂载成功。

## 参考依据

- `website/docs/zh_CN/guide/module.md`：模块功能边界、Zygisk 提示、安装变量和启动阶段。
- `website/docs/zh_CN/guide/faq.md`：普通脚本/属性/policy 不需要 metamodule。
- `ksu-research/modules/Sui/README.zh-CN.md`、`device_faker/docs/README.md`、
  `PlayIntegrityFork/README.md`：公开的 KernelSU + Zygisk 兼容要求。
- `ksu-research/modules/meta-hybrid_mount`、`meta-magic_mount-rs`：复杂 native/mount 项目的
  构建、测试和分层组织样本。
