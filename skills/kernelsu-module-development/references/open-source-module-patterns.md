# KernelSU 适用开源模块：源码模式库

本参考来自本机 `ksu-research/modules/` 的静态源码阅读，而非只读发布说明。它的目标是帮助制作 **合法、可维护、可救砖** 的 KernelSU 模块：借鉴项目结构、生命周期、配置迁移、日志和兼容性检测；不复制高风险的 root 隐藏、完整性规避、私钥处理或厂商专用 hack。

## 范围与判定

- 已深读的可读源码样本共 **14 个**；均有本机 git checkout、可读源码/脚本/构建描述或许可证证据。
- 另有 **2 个明确不是开放源码的兼容目标**：TrickyStore、Zygisk Next。它们只可作为运行环境/配置兼容对象，不能抽取、修改、再打包或复制实现。
- 本文不声称实时 GitHub star 排名。入选以本地源码完整性、KernelSU 生态代表性、发布/文档成熟度和实现类型覆盖为主。
- `module.prop`、`customize.sh`、`post-fs-data.sh`、`service.sh`、`action.sh` 是跨管理器模块常见生命周期入口；在目标 KernelSU 版本上实测后才能当作兼容结论。

## 样本项目清单

| 项目（仓库 / 本地路径） | 开源状态与用途 | 可复用的源码模式 | 不要照搬的风险与源码证据 |
| --- | --- | --- | --- |
| [FreePPS](https://github.com/Seyud/FreePPS) `ksu-research/modules/FreePPS` | GPL-3.0；Rust 原生 daemon，为特定米系设备切换 PPS 充电节点。 | `module/customize.sh` 按需安装配套 app、赋予二进制执行权限；`service.sh` 等开机/解锁后再启动 daemon；`action.sh` 用小状态文件实现可逆开关。`src/monitoring/` 用 uevent/epoll 监听。 | 节点和充电策略高度设备相关，错误写入可损伤充电/温控体验；不要把 `nohup` 当健康检查，也不要复用具体 sysfs 节点。 |
| [Device Faker](https://github.com/Seyud/device_faker) `ksu-research/modules/device_faker` | GPL-3.0；Rust `cdylib` Zygisk 模块，按包名读取 TOML 配置，带 CLI/WebUI。 | `module/customize.sh` 先检测 Zygisk provider、迁移/备份 `/data/adb/device_faker/config/config.toml`、设置权限/SELinux label；`src/config.rs` 是配置合并模型；`src/cpu_spoof.rs` 展示“在目标 app mount namespace 中创建并在退出时清理”的生命周期设计。 | 不要把属性伪装、`resetprop`、`setns`/bind mount 或反检测策略当普通模块模板；错误 namespace/清理会残留挂载或影响其它 app，且伪装用途可能违反服务条款。 |
| [bindhosts](https://github.com/bindhosts/bindhosts) `ksu-research/modules/bindhosts` | WTFPL；系统 hosts 管理，支持 KernelSU/APatch/Magisk 与 WebUI。 | `module/customize.sh` 将用户数据移至 `/data/adb/bindhosts`，升级不覆盖；`post-fs-data.sh` 探测 KSU、SUSFS、ksud 与 Zygisk 组合后选择运行模式；`service.sh` 用一个明确的 mode dispatcher 实施 bind/overlay/redirect。 | 不要无提示禁用其它 hosts 模块；hosts、DNS、hide/umount 组合冲突极多。须提供冲突报告、停用开关、回滚和真实 `mountinfo` 验证。 |
| [MoveCertificate](https://github.com/ys1231/MoveCertificate) `ksu-research/modules/MoveCertificate` | Apache-2.0；Android 7–16 的系统 CA 证书搬运模块。 | `customize.sh` 创建模块系统路径和 mode 配置；`post-fs-data.sh` 依 Android API 与 `builtin/compatible` mode 选择实现；把共享 shell 函数放在 `sh/`，入口只负责编排。 | 系统 CA 注入扩大 TLS 信任面，不能默认启用或静默收集证书；必须清楚说明来源、删除/卸载与 APEX/Conscrypt 兼容边界。 |
| [MakeFontsGreatAgain](https://github.com/Numbersf/MakeFontsGreatAgain) `ksu-research/modules/MakeFontsGreatAgain` | 公共源码脚本与 WebUI；字体资产在 `LICENSES.md` 按来源分别许可，**不是干净的可随意复制模板**。 | `script/customize.sh` 先做 KSU/Magisk 版本和 Android API gate，再处理 ROM 特例；`script/action.sh` 以显式用户确认执行破坏性 GMS 字体清理；`webroot/` 提供 WebUI。 | 字体覆盖、应用私有目录 chmod、GMS 字体删除都可能 bootloop、破坏 app 或触发完整性冲突；逐个字体资产核对许可，绝不批量复制字体或做无确认的 `rm -rf`。 |
| [MagicNet](https://github.com/LIghtJUNction/MagicNet) `ksu-research/modules/MagicNet` | MIT；KernelSU/Magisk/APatch root 网络编排模块，含 sing-box、CLI、WebUI、MCP。 | `src/MagicNet/customize.sh` 备份有限白名单配置、恢复而非覆盖；以 `lib/` 划分安装、网络、路由、DNS、监督器；`service.sh`/`action.sh` 是薄包装，统一交给框架；提供诊断和配置面。 | 不要硬编码订阅、API secret、控制端口或防火墙规则；透明代理/DNS 劫持会影响联网、VPN 与热点，必须实现停止、恢复、最小权限和日志脱敏。 |
| [NetProxy-Magisk](https://github.com/Fanju6/NetProxy-Magisk) `ksu-research/modules/NetProxy-Magisk` | GPL-3.0；开源模块脚本、WebUI 与 sing-box 管理；README 明说配套原生 Android 管理 app **不提供公开源码**。 | `src/module/customize.sh` 定义配置白名单备份/恢复和可执行文件清单；`post-fs-data.sh` 只加载早期依赖；`service.sh` 等 boot 完成后再启核心；`scripts/cli` 是统一的受控入口，WebUI 写配置而不直接散落命令。 | 不要复用公开默认 controller secret，或随意加载 IPSET LKM、改 TPROXY/REDIRECT；网络规则必须有冲突检测、撤销和 IPv4/IPv6 回归。仅“原生 app”是闭源，不要误称整个模块仓库闭源。 |
| [Re-Malwack](https://github.com/ZG089/Re-Malwack) `ksu-research/modules/Re-Malwack` | GPL；hosts 广告/恶意域名拦截，WebUI、CLI、配置 profile，另有可读 Zygisk/xHook 代码。 | `module/customize.sh` 建立持久数据目录、配置默认值和交互式 profile 选择；`service.sh` 更新模块状态描述；`zygisk/jni/module.cpp` 展示 provider 中检查 denylist、限定目标进程、失败日志的基本形态。 | 不要将“自动禁用其它 hosts 模块”、DNS hook 或全进程 `getaddrinfo` hook 作为默认策略；它们易造成 DNS 失败、兼容性/隐私问题。应先最小化 target、给用户选择并保留退出路径。 |
| [PlayIntegrityFork](https://github.com/osm0sis/PlayIntegrityFork) `ksu-research/modules/PlayIntegrityFork` | GPL-3.0；有 C++ 与模块脚本源码；在 KernelSU 上依赖独立 Zygisk 实现。 | 可借鉴的仅是工程卫生：`module/customize.sh` 保留用户配置、对旧格式做显式 migration、`killpi.sh` 等动作脚本与日志/冲突诊断分层。 | 这是针对 Google 服务完整性检查的定向 Zygisk 注入/属性伪装样本，**不要复制为通用模块功能，也不要分发指纹、keybox 或规避方案**；此类行为会带来账号、法律、服务条款与设备稳定性风险。 |
| [Sui](https://github.com/XiaoTong6666/Sui) `ksu-research/modules/Sui` | GPL-3.0-or-later；大型 Zygisk 模块，为 app 提供 Shizuku 风格 root/shell Binder API。 | `module/build.gradle.kts` 演示 APK/native lib/module ZIP 一体化构建与 `ksud module install` 测试任务；README 的 root/shell/system_server/SystemUI/Settings 分层、按 UID 授权缓存和启动日志要求，是高权限服务的好架构样本。 | 不适合作为“小模块”拷贝起点。system_server/Binder/SELinux/adb root hook 出错风险极高；KernelSU 使用时还依赖 Zygisk provider，必须明确版本、denylist 和回退条件。 |
| [Encore](https://github.com/Rem01Gaming/encore) `ksu-research/modules/encore` | Apache-2.0；性能调优 daemon、C++ JNI、配置存储和 WebUI。 | `module/service.sh` 先等待 boot、记录原 governor、创建 cleanup 路径再启动 daemon；`jni/EncoreConfigStore.cpp` + `InotifyHandler.cpp` 演示带默认值、持久化和热重载的配置层；`Main.cpp` 用进程事件切换 profile。 | CPU governor、thermal、`/proc`/`/sys` 调优不能照抄；必须保存原值、在崩溃/卸载/重启时恢复，并在不同 SoC/内核上做白名单检测。 |
| [meta-overlayfs](https://github.com/KernelSU-Modules-Repo/meta-overlayfs) `ksu-research/modules/meta-overlayfs` | GPL-3.0（`Cargo.toml` 声明）；KernelSU metamodule 的 OverlayFS **参考实现**。 | `src/mount.rs` 采用 metadata/content 双目录：扫描 `module.prop`、`disable`、`skip_mount`，从独立内容目录收集 lowerdir；先枚举子挂载、失败时回滚；`metamodule/customize.sh` 做 ABI 选择和 sparse ext4 image 初始化。 | README 明示它不是生产级实现。大 image、upper/workdir、嵌套 mount、白化/回滚均有 bootloop 风险；不要在未做 mount graph/失败恢复测试时复制到生产模块。 |
| [meta-magic_mount-rs](https://github.com/Tools-cx-app/meta-magic_mount-rs) `ksu-research/modules/meta-magic_mount-rs` | GPL-3.0；Rust Magic Mount metamodule，带 TOML/WebUI。 | `module/metainstall.sh` 声明 `KSU_HAS_METAMODULE`/`KSU_METAMODULE`，处理 `/system/{vendor,product,system_ext}` 软链接布局、`skip_mount`、模块 hot-install；`src/scanner.rs` 验证 module id/metadata；`src/magic_mount/` 建树后按路径挂载。 | 不要默认接管所有模块或用 `rm -rf` 处理元模块目录；自挂载模块须 blocklist/`skip_mount`，分区迁移必须可逆且针对真实设备布局测试。 |
| [meta-hybrid_mount](https://github.com/Hybrid-Mount/meta-hybrid_mount) `ksu-research/modules/meta-hybrid_mount` | Apache-2.0；OverlayFS、Magic Mount、Kasumi 后端的策略驱动 metamodule，含 daemon/CLI/WebUI。 | README/`config.toml` 将“模块/路径 → mount backend”做成声明式 policy；`module/metainstall.sh` 提供 mode marker、已知自挂载 blocklist 和安全的分区识别；`module/service.sh` 仅在设置为 persistent 时启动 daemon。 | 不要把 Kasumi 的 LKM、stealth/hide/spoof 能力直接复制到普通模块；后端选择、内核 ABI、daemon socket、状态持久化都要最小化、鉴权并具有恢复模式。 |
| [TrickyStore](https://github.com/5ec1cff/TrickyStore) `ksu-research/modules/TrickyStore` | **非开源兼容目标**：README 明说从 1.1.0 起停止开源，本机 tree 只有文档/metadata，没有可读实现。 | 只能借鉴公开的配置边界：它读取 `/data/adb/tricky_store/` 下的配置，配置变更即时生效的语义需要与其它模块避免冲突。 | 版权明确限制；不可抽取、修改、再发布二进制或把其实现当模板。不要处理/分发 keybox、私钥或证明材料。 |
| [Zygisk Next](https://github.com/Dr-TSNG/ZygiskNext) `ksu-research/modules/ZygiskNext` | **非开源兼容目标**：README 写明 v4-0.9.2 起保留所有权利，禁止修改、再发布、摘取；本机 tree 也只有 README/issue 模板。 | 只把它作为“提供 Zygisk API 的外部依赖”进行安装前检测、最低版本提示和冲突提示；不能作为源码来源。 | 禁止复制、vendoring、改名发行或假定其 Magisk 内部行为。模块只应调用稳定公开 API，并在没有 provider 时拒绝安装或降级。 |

## 哪些可以复用，哪些只能兼容

### 可读源码、可研究的 14 个样本

`FreePPS`、`Device Faker`、`bindhosts`、`MoveCertificate`、`MakeFontsGreatAgain`、`MagicNet`、`NetProxy-Magisk`、`Re-Malwack`、`PlayIntegrityFork`、`Sui`、`Encore`、`meta-overlayfs`、`meta-magic_mount-rs`、`meta-hybrid_mount`。

“可研究”不是“可直接拷贝”。遵守各自 GPL、Apache-2.0、MIT、WTFPL 或字体资产的独立许可证；尤其 GPL 衍生/分发会带来相应源码与许可义务，字体/第三方二进制还要逐项复核。

### 明确仅能作为兼容目标的 2 个样本

1. **TrickyStore**：上表所列 README 写有 “Stop opening source”，并且当前 checkout 没有可读实现源码。只适合做配置冲突检测或功能边界说明。
2. **Zygisk Next**：README 的 copyright notice 明确禁止修改、再发布和摘取组件；当前 checkout 无实现源码。只能检测其是否已安装/版本是否满足，绝不能吸收进自己的 ZIP。

### 容易误判的一项

**NetProxy-Magisk 的模块仓库是开源 GPL-3.0**：脚本、WebUI 和打包文件都在本地 checkout；README 所说“不提供公开源码”的是其单独维护的 Android 管理 app。因此：可研究模块工程，但不要假装拥有或重打包那个原生 app。

## 按模式归类与可迁移的设计要点

### 1. 普通 Shell 生命周期与文件覆盖

样本：MoveCertificate、MakeFontsGreatAgain、bindhosts、Re-Malwack，以及所有包含安装脚本的样本。

可迁移做法：

- 在 `customize.sh` 中只做安装时的输入检查、版本 gate、配置迁移、权限设置和用户确认；不要启动长期服务。
- 把可更新的用户配置放在稳定的 `/data/adb/<module-id>/`，升级时只备份/恢复白名单文件；`MODPATH` 只保存可替换的程序和默认模板。
- 将早期必须动作限定在 `post-fs-data.sh`，例如必要的 LKM/挂载准备；将网络、应用、外部存储和 daemon 启动放到 `service.sh`，等待所需系统状态。
- 用 `action.sh` 做短、可逆、可解释的操作（开关、诊断、更新），必要时采用音量键或 WebUI 二次确认。
- 所有路径加引号、所有可删除项目有精确白名单；处理失败时保留日志和不破坏旧配置。

不该迁移的做法：无条件 `rm -rf`、自动禁用别的模块、把开机完成当成所有资源已可用、把 Manager 注入的环境变量当作永远存在。

### 2. 原生二进制、daemon 与 ABI 包装

样本：FreePPS（Rust daemon）、Encore（C++ daemon）、Device Faker（Rust `cdylib` + CLI）、Sui（APK/native）、meta-*（Rust）。

可迁移做法：

- 以构建文件作为唯一的 ABI/依赖事实源（Cargo/Gradle/NDK），在安装阶段显式选择 ABI 并检查文件存在、可执行位和 SELinux 可读性。
- daemon 启动前确认配置完整、依赖可用、设备/内核能力满足；写 PID/日志/健康状态并能够停止、重启和清理。
- 对调优类模块保存原值，创建清理脚本，并在 daemon 异常退出时做尽可能安全的恢复。
- 用 schema/默认值/版本化 migration 管理持久配置；配置解析失败时应回退到安全默认，而不是写损坏状态。

高风险边界：`setns`、`mount`、`resetprop`、Binder hook、`LD_PRELOAD`、LKM、sysfs/thermal 调优都必须有目标能力检测、超时、撤销和真机回归。它们不是一个“通用二进制模块骨架”。

### 3. WebUI 与 CLI 控制面

样本：MagicNet、NetProxy-Magisk、bindhosts、Re-Malwack、Encore、Device Faker、meta-hybrid_mount、meta-magic_mount-rs、MakeFontsGreatAgain。

可迁移做法：

- WebUI 只负责渲染、表单校验和调用少量明确的命令；实际特权逻辑集中在一个受参数校验的 CLI/API，便于终端、Action 和 UI 复用。
- WebUI 写入配置时进行原子写入、schema 校验、备份，并通过受控 reload/apply 命令生效；不要拼接用户文本为 root shell。
- 将状态、日志、版本、健康检查以只读接口提供；敏感 token、订阅和私钥绝不渲染、绝不写进 `module.prop` 或浏览器存储。
- 允许无 WebUI 的完整 CLI 恢复路径，因为 Manager WebView 可能不可用或模块本身导致 UI 崩溃。

不要照搬：默认开放 TCP 控制端口、固定 secret、任意文件读写/任意 shell 执行桥、依赖某个第三方 WebUI 容器存在。

### 4. 配置、升级与状态持久化

样本：Device Faker 的 TOML、meta-* 的 TOML、MagicNet/NetProxy 的配置白名单、Re-Malwack 的 profile、Encore 的 JSON、MoveCertificate 的 mode 配置。

推荐契约：

1. `defaults/` 随 ZIP 更新，`/data/adb/<id>/` 是用户状态；不要直接用新默认覆盖用户状态。
2. 为配置记录 `schema_version`，升级时从旧版明确迁移；迁移失败保留原件并提示恢复命令。
3. 每项配置都定义默认值、允许范围、重启/热应用语义和失败回退。
4. 写入时采用临时文件 + 校验 + rename，避免断电产生半文件。
5. 服务启动时只读取被验证的配置；不要 `source` 用户可编辑文件来执行任意 shell，除非这是明确受信任的高级接口且有隔离说明。

### 5. 元模块、OverlayFS 与挂载编排

样本：meta-overlayfs、meta-magic_mount-rs、meta-hybrid_mount；bindhosts/MoveCertificate/MakeFontsGreatAgain 是被管理模块的现实兼容样本。

可迁移做法：

- 把 **metadata**（`module.prop`、`disable`、`skip_mount`）和 **content**（要挂载的 `system/`、`vendor/` 等）概念上分离；扫描前验证 module ID 和标记文件。
- 识别 `/system/vendor` 与 `/vendor` 等软链接/分区布局，先建 mount graph，再按明确顺序处理子挂载；失败要回滚，不要继续部分挂载。
- 自己实现挂载的模块要有 `skip_mount` 或元模块 blocklist，防止双重挂载。
- 用 declarative policy 表达“哪个模块/路径用哪个 backend”，并在启动前检测冲突、无效路径、不可用后端与重复 ownership。
- 任何 OverlayFS upper/workdir、ext4 image、LKM backend 都需要空间、文件系统、内核 feature 和恢复模式检查。

绝不能简化为：“把 `system/` 目录塞进 ZIP 就一定在所有 app 可见”。从关闭 issue #346、#359、#365 以及这些元模块源码可知，app namespace、软链接、嵌套 mount、Manager 策略都会改变可见性。

### 6. Zygisk 兼容与进程内模块

样本：Device Faker、Sui、PlayIntegrityFork、Re-Malwack；外部 provider 兼容对象为 Zygisk Next。

可迁移做法：

- 安装前检测存在可用 provider；没有 provider 时清晰 abort 或切换到非注入实现，不能把 provider 二进制打入自己的模块。
- 在 native 模块中尽早判断目标包/进程/denylist，非目标进程立即卸载本库；日志需可开启但不得泄漏配置/凭据。
- 只 hook 自己有必要且能长期维护的 API；配置按包名/UID 分层，进程退出后撤销临时挂载/状态。
- 对 Java/Native/Binder 双端版本、ABI、Android API 级别建立兼容矩阵，并提供“禁用模块后可恢复”的故障路径。

禁止照搬：Google 完整性规避、根隐藏、系统服务全局 hook、私钥/keybox 用法或未公开 Zygisk provider 的任何实现。兼容 Zygisk Next 的正确做法是版本检测和公开 API 调用，而不是复制其二进制/源码。

## 从样本抽取的模块制作检查表

在做一个新的 KernelSU 模块前，按下面顺序决定实现：

1. **明确功能边界**：文件覆盖、配置、daemon、WebUI、Zygisk、挂载中哪些是必要的；不要为了“兼容更多”无条件引入 LKM、hook 或网络重定向。
2. **选择最小生命周期**：安装逻辑放 `customize.sh`；早期启动只做必要动作；晚期服务等待系统 ready；用户手动动作独立于开机路径。
3. **设计持久化**：用户配置和程序文件分开；升级、卸载、禁用、异常退出都有明确结果。
4. **处理兼容矩阵**：Android API、ABI、内核能力、KSU/ksud、Zygisk provider、ROM 分区布局、其它互斥模块逐项检测。
5. **把特权操作做成可审计接口**：参数白名单、日志、干运行/状态命令、超时、回滚；WebUI 不能绕过此接口。
6. **写救砖说明并真机验证**：如何从 Manager、`ksud`、recovery 或 safe mode 禁用/删除；验证 boot、升级、禁用/启用、卸载、异常配置、与一个冲突模块共存的表现。

## 本地源码证据索引

- 普通模块入口：`FreePPS/module/{customize,service,action}.sh`、`MoveCertificate/{customize,post-fs-data}.sh`、`bindhosts/module/{customize,post-fs-data,service,action}.sh`、`Re-Malwack/module/{customize,post-fs-data,service}.sh`。
- 原生/配置：`device_faker/{Cargo.toml,src/config.rs,src/cpu_spoof.rs,src/companion.rs}`、`FreePPS/{Cargo.toml,src/monitoring/}`、`encore/{jni/Main.cpp,jni/EncoreConfigStore.cpp,module/service.sh}`、`Sui/module/build.gradle.kts`。
- 网络/WebUI：`MagicNet/src/MagicNet/{customize.sh,service.sh,lib/}`、`NetProxy-Magisk/src/module/{customize.sh,post-fs-data.sh,service.sh,scripts/cli,webui/}`。
- 挂载：`meta-overlayfs/{README.md,src/mount.rs,metamodule/customize.sh}`、`meta-magic_mount-rs/{docs/README.md,module/metainstall.sh,src/scanner.rs,src/magic_mount/}`、`meta-hybrid_mount/{README.md,module/metainstall.sh,module/service.sh,src/}`。
- 闭源判定：`TrickyStore/README.md` 的 “Stop opening source”；`ZygiskNext/README.md` 的 copyright notice（no modifications/no redistribution/no picking）。
