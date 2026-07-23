# KernelSU 模块核心契约

> 适用对象：编写、审计、迁移或发布 KernelSU 常规模块、元模块和带原生/Zygisk
> payload 模块的作者。本文件是实现前必须遵守的稳定边界；WebUI、安全、原生
> payload 和逐条 issue 经验分别见同目录的专项参考。
>
> 取证基线：`tiann/KernelSU` 当前 checkout
> `87a62b76c9d3dd31495f63508469601237b1ad09`（2026-07-23）。KernelSU、Manager、
> ksud、元模块、内核与 ROM 会独立演进；发布前仍应以目标设备的实际版本复测。

## 目录

1. [证据等级与实现选择](#证据等级与实现选择)
2. [模块身份、元数据与目录](#模块身份元数据与目录)
3. [安装、更新、启停与卸载](#安装更新启停与卸载)
4. [systemless、挂载与元模块](#systemless挂载与元模块)
5. [启动生命周期、脚本与环境](#启动生命周期脚本与环境)
6. [属性、SELinux 与 initrc](#属性selinux-与-initrc)
7. [配置、WebUI、原生与 Zygisk](#配置webui原生与-zygisk)
8. [安全、诊断、救援与发布验收](#安全诊断救援与发布验收)
9. [来源与进一步阅读](#来源与进一步阅读)

## 证据等级与实现选择

本文使用下列标记，避免把历史 workaround 或第三方项目行为误当 KernelSU API。

- **已确认**：当前源码与官方文档一致，或当前源码能直接证明。
- **需实机验证**：依赖元模块、内核、Manager、ROM、SELinux、mount namespace 或
  Android 版本的行为；不能只因 ZIP 安装成功就宣称有效。
- **当前不应依赖**：官方旧说明、历史 issue 或当前 checkout 彼此不一致时的保守结论。

先按需求选择最小实现层，避免为简单事情引入挂载、native daemon 和 Zygisk 三层风险：

| 需求 | 首选机制 | 前提/边界 |
|---|---|---|
| 启动时执行固定命令、写 sysfs、启动普通服务 | `service.sh`，必要时 `boot-completed.sh` | 不阻塞早期启动；脚本可恢复、可重复运行 |
| 比 zygote 更早的准备 | `post-fs-data.sh` | 阻塞阶段；不得用 `setprop`；只做很短的必要工作 |
| late-load 设备中的早期等价工作 | `late-load.sh` | 仅 late-load；替代普通的 post-fs-data 逻辑 |
| 修改 `/system` 可见文件 | 模块 `system/` + 兼容的 metamodule | 没有 metamodule 时不会挂载 |
| 修改 `/system` 外的挂载目标 | 自己在 `post-mount.sh` 处理 | 分区布局、label、namespace 均需实测 |
| 注册极早 Android init 服务 | `initrc/*.rc` | 标准启动；late-load 不可用；安全模式未必阻止它 |
| 保存用户偏好/短状态 | `ksud module config` | 不放秘密；读取后仍校验 schema |
| 图形设置或受控操作 | 本地 `webroot/` + 固定 helper | WebUI 是 root shell 执行面 |
| 高性能、协议或持续守护 | 打包的 native payload | ABI、SELinux、退出/升级与 mount namespace 均需测试 |
| zygote/app 进程注入 | 独立 Zygisk 兼容实现的模块 | KernelSU 核心没有内建 Zygisk |

**总原则**：模块拥有 root 级破坏能力。不要把“能执行”当成“可以安全发布”，也不要把
Magisk 目录、变量或 Recovery 安装流程无条件照搬过来。

## 模块身份、元数据与目录

### `module.prop` 是身份根

一个模块根目录必须有 `module.prop`；没有它不会被当成模块。ZIP 解压后，
`module.prop` 必须直接位于模块根，而不是额外的顶层目录内。模块目录名必须与
`id` 相同，运行目录通常是 `/data/adb/modules/<id>`，但脚本不得硬编码该路径。

最小元数据如下：

```properties
id=example-module
name=Example Module
version=1.0.0
versionCode=1
author=Example Author
description=一个可恢复的示例模块
```

`id` 是发布后的稳定主键，必须匹配：

```text
^[a-zA-Z][a-zA-Z0-9._-]+$
```

因此它以字母开始、只含字母数字点下划线连字符、至少两个字符。不要用空格、斜线、中文
或仅一个字符；不要通过改 ID 来“升级”已有模块，否则配置、启停和卸载都会变成另一个
模块。文件必须使用 LF 换行，不要用 CRLF。

可选字段包括：

```properties
updateJson=https://example.invalid/update.json
actionIcon=icon/action.png
webuiIcon=icon/web.png
```

图标路径相对模块根。`versionCode` 用于比较，必须是整数；其它公开字段保持单行、可显示、
不含令牌、设备私密路径或长日志。动态状态应使用配置系统的 `override.description`，不要
让脚本随意重写 `module.prop`。

### 根目录契约

下列是普通模块可使用的结构；额外私有文件/目录允许存在，但必须由模块自身清理和保护。

```text
module-root/
  module.prop                 # 必需
  system/                     # 可选：只放需覆盖的 /system 相对路径
  skip_mount                  # 可选标记：不挂载 system/
  disable                     # 可选标记：当前禁用
  remove                      # 可选标记：下次 early boot 清理
  customize.sh                # 可选：安装期被 source
  uninstall.sh                # 可选：实际删除前执行
  action.sh                   # 可选：Manager Action，同步执行
  post-fs-data.sh             # 可选：标准启动早期、阻塞
  late-load.sh                # 可选：仅 late-load，替代上述早期逻辑
  post-mount.sh               # 可选：挂载后、阻塞
  service.sh                  # 可选：late_start、非阻塞
  boot-completed.sh           # 可选：系统 boot complete 后、非阻塞
  system.prop                 # 可选：通过 resetprop 加载
  sepolicy.rule               # 可选：动态 SELinux 规则
  initrc/*.rc                 # 可选：标准启动的 init RC 注入
  webroot/index.html          # 可选：Manager WebUI 入口
  bin/ data/ logs/            # 模块私有内容；定义自己的权限和清理规则
```

区分两个容易混淆的“删除”概念：

- 模块根的 `<MODDIR>/remove` 是**卸载标记**；它不等于立即删除目录。
- `system/` 内的字符设备 `c 0 0` 是 OverlayFS tombstone/whiteout 等效物，用于让
  被覆盖的系统路径消失；它不删除真实系统分区文件。

脚本内部始终从脚本路径推导根目录：

```sh
MODDIR=${0%/*}
```

对 `action.sh`、WebUI helper 和 native 子程序同样传递这个已确定的模块根；不能由 UI、
配置或外部文件名决定模块路径。

## 安装、更新、启停与卸载

### 安装是 staging 协议，不是复制目录

**已确认**：当前 `ksud` 在 Android 已完成启动（`sys.boot_completed=1`）后才允许安装。
使用 KernelSU Manager 或 `ksud module install <zip>` 走受支持入口；不要支持或宣传
Recovery 安装。模块 ZIP 根直接放模块文件，`META-INF/` 可以存在但不是模块根目录。

安装/覆盖更新使用 `modules_update/<id>` staging 区，随后在下一次早期启动把更新切换进
活动 `modules/<id>`；旧模块的 `disable`/`remove` 标记会被保留。安装完成后活动目录会被
标记为有更新，故“Manager 显示已安装”不表示新 payload 已在当前启动中生效。

由此得到的规则：

1. 不要手动修改 `/data/adb/modules`、`modules_update` 或 `update` 标记来升级、回滚或修复。
2. 不让伴生 App 直接复制/删除这些内部目录；生成 ZIP 后调用受支持的 Manager/`ksud` 安装流程。
3. 将安装、覆盖更新、重启后切换、禁用、重新启用、卸载和升级失败恢复作为一组测试。
4. 若模块依赖挂载、initrc 或 early script，在说明中明确“重启后生效”，而非承诺热更新。

### `customize.sh` 的边界

`customize.sh` 在 KernelSU BusyBox 的 standalone `ash` 中被 **source**，不是独立子进程。
它可以检查 ABI/API/运行模式并调用安装器提供的 `ui_print`、`abort`、`set_perm`、
`set_perm_recursive` 等帮助函数。遇到不支持的前提，用 `abort '原因和恢复办法'`，不要用
`exit` 跳过安装器清理。

普通情况下让内置安装器解压、设置默认权限和 SELinux context。若必须完全接管，文件中要有
**完全等于** `SKIPUNZIP=1` 的一行；当前安装器按该精确行识别它。此时作者负责：

- 将 ZIP 内容解到当前 staging `MODPATH`，而非活动 `modules/<id>`；
- 验证 `module.prop`、ID、ABI、API、空间与所有预期文件；
- 设置需要的最小权限/label，拒绝不可信压缩包路径和符号链接陷阱；
- 保持失败可清理，且不能遗留半安装的共享状态。

安装期可读取的典型环境有 `KSU=true`、`KSU_VER`、`KSU_VER_CODE`、
`KSU_KERNEL_VER_CODE`、`KSU_UAPI_VER`、`KSU_RUNTIME_MODE`、`KSU_LATE_LOAD`、
`BOOTMODE=true`、`MODPATH`、`TMPDIR`、`ZIPFILE`、`ARCH`、`IS64BIT`、`API`。用
`KSU` 判断 KernelSU；不要用在 KSU 中伪装兼容值的 `MAGISK_VER*` 作判断依据。

### 状态变更与清理

| 操作 | 当前行为 | 作者应保证 |
|---|---|---|
| 禁用 | 创建 `disable`；活动脚本、挂载、RC 收集跳过该模块 | 工作进程下次启动不再依赖它；不破坏其他模块 |
| 启用 | 删除 `disable`，RC 会刷新 | 初始化可重复，不依赖旧临时文件 |
| 卸载请求 | 创建 `remove`，当前源码会刷新 RC | 不把“点击卸载”当作即时删除成功 |
| 下次 post-fs-data | 执行元模块 `metauninstall.sh`（普通模块时）、本模块 `uninstall.sh`、清配置、删除目录 | `uninstall.sh` 幂等、短小、只清自家外部资源 |
| Action | `action.sh` 由 Manager/ksud 同步等待 | 不长时间阻塞 UI；输出可读、无任意输入执行 |

`uninstall.sh` 可能在部分初始化失败后仍被调用，因此先检查存在性和归属；不要 `killall`、
删除 `/data/adb` 共享目录、删其他模块、删系统分区或假定网络可用。要清理 daemon，使用自家
pidfile/固定 socket，并容忍它已不存在。

## systemless、挂载与元模块

### 何时需要 metamodule

**已确认**：只有 `system/` 的 systemless 挂载依赖 metamodule。普通脚本、`system.prop`、
`sepolicy.rule`、配置和 WebUI 不需要 metamodule。没有兼容的活跃 metamodule 时，模块的
`system/` 内容不会被挂载；不要把“模块启用”误报告为“系统覆盖已生效”。同一时刻只允许一个
活跃 metamodule。

普通模块作者应把 metamodule 视为可声明的运行依赖，至少说明兼容的挂载实现、重启要求、
OverlayFS/ROM 限制和无 metamodule 时的降级/拒绝策略。不要为了普通 `system/` 覆盖另写一个
metamodule；那会影响机器上的所有模块。

### `system/` 的 OverlayFS 语义

`system/` 中的路径相对 `/system`：同名文件会覆盖，目录通常合并。它是对可见视图的修改，
不是对真实 `/system` 分区的写入。遵守以下规则：

```text
system/etc/example.conf       -> /system/etc/example.conf
system/app/MyApp/...          -> /system/app/MyApp/...
```

- 删除一个系统文件/目录时，在模块对应路径创建 tombstone：
  `mknod "$MODPATH/system/目标" c 0 0`。不要直接 `rm /system/...`。
- `customize.sh` 的 `REMOVE` 列表由当前安装器实现为这种 tombstone；每项是实际目标的
  相对映射，需在目标 ROM 检验。
- `skip_mount` 会阻止该模块的 `system/` 被挂载，适合脚本/配置型模块或有意的临时降级。
- `/system/vendor`、`/system/product`、`/system/system_ext` 以及设备上的 `odm` 可能是独立
  分区或软链接。当前安装器有相应的分区处理分支，但真实路径、label、扫描时机与 ROM
  不同；发布前逐机验证，而不是假定任何一个目录布局。
- `/system` 外的 OverlayFS 不是普通模块的隐式能力。若确需它，在 `post-mount.sh` 自行处理、
  检查 mount 返回值，并提供回滚；参见 closed issue #2789 的经验索引。

官方文档描述 `REPLACE` 可把目录设为 opaque。然而当前 checkout 的安装脚本调用
`mark_replace`，仓库中没有对应定义；因此 **当前不应依赖 `REPLACE` 变量作为可发布能力**。
若必须使用 opaque directory 的 OverlayFS 语义，只在确定的 metamodule/ROM 上以明确的
`trusted.overlay.opaque=y` 操作和完整恢复测试实现，并在发布说明中标为需实机验证。

### Mount namespace 是另一层兼容性

root shell 看见挂载，不代表普通 App、system_server 或目标进程看见同一挂载。涉及 APK、
framework、包扫描、Zygisk 或 service 时，对比 `/proc/1/mountinfo` 与目标 PID 的
`/proc/<pid>/mountinfo`；同时记录 KernelSU auto-unmount、授权模式和 metamodule 行为。
“文件在 shell 中存在”不能作为应用兼容的验收证据。

### 编写 metamodule 时的额外契约

仅在确实实现模块安装/挂载基础设施时，把模块声明为：

```properties
metamodule=1
```

它可以提供：

- `metamount.sh`：挂载所有合格普通模块，跳过 `disable`/`skip_mount`，并正确处理卸载与
  回滚。KernelSU 文档要求 mount source/设备名为 `KSU`，现代 mount API 也要设置该 source。
- `metainstall.sh`：普通模块安装时被 source，可调整安装流程；安装该元模块自身时不会调用它。
- `metauninstall.sh`：普通模块删除前清理元模块创建的资源；参数/环境只接受已验证的模块 ID。

元模块脚本比普通模块脚本优先执行，故错误会扩大到全部模块。实现前阅读本技能的
`native-and-zygisk.md` 和现有公开元模块的架构样本；将挂载资源命名、清理、失败注入、
升级、降级与多个普通模块并存视为必须测试的功能。

## 启动生命周期、脚本与环境

### 标准启动顺序

当前 `ksud` 的核心顺序如下；元模块在同 stage 的普通模块之前执行。

```text
post-fs-data:
  清所有临时 module config
  安全模式检查；处理 updates 与 remove
  刷新 modules.rc；restorecon；加载 sepolicy.rule 与 feature
  metamodule post-fs-data.sh -> 普通模块 post-fs-data.sh
  加载 system.prop -> metamodule mount -> post-mount 脚本

late_start:
  通用 service.d -> metamodule service.sh -> 普通模块 service.sh（非阻塞）

Android boot completed:
  通用 boot-completed.d -> metamodule boot-completed.sh
  -> 普通模块 boot-completed.sh（非阻塞）
```

每个普通模块脚本使用 KernelSU BusyBox `ash`，并启用 `ASH_STANDALONE=1`。这会优先使用
BusyBox applet；若必须调用 Android 原生工具，用绝对路径，例如 `/system/bin/cmd`，并在目标
Android 版本测试语义。常见环境包括：

```text
KSU=true
KSU_VER / KSU_VER_CODE / KSU_KERNEL_VER_CODE / KSU_UAPI_VER
KSU_RUNTIME_MODE= built-in | lkm | late-load
KSU_MODULE=<本模块 id>          # KernelSU 启动/模块脚本上下文
KSU_LATE_LOAD=1                 # 仅 late-load
```

不要假定从 WebUI 直接启动的 root shell 一定带有 `KSU_MODULE`；它不是用户输入，也不应由
网页伪造。需要配置 API 时，用模块自己的固定 helper 在已验证的模块脚本上下文调用，或显式
设置可信的自家 ID，而不是把 UI 参数拼进环境。

### 每种脚本该做什么

| 文件 | 时机与阻塞性 | 适用工作 | 禁忌 |
|---|---|---|---|
| `post-fs-data.sh` | 挂载前、zygote 前、阻塞 | 极短的早期准备 | 网络、长扫描、等待 daemon、`setprop` |
| `late-load.sh` | 仅 late-load、挂载前、阻塞 | late-load 中取代早期逻辑 | 假定普通 post-fs-data 也会执行 |
| `post-mount.sh` | metamodule 挂载后、阻塞 | 依赖已挂载视图的短工作 | 长服务、无限等待 |
| `service.sh` | late_start、非阻塞 | 大多数后台启动与正常初始化 | 依赖 initrc 已注册或仍处于早期时机 |
| `boot-completed.sh` | `sys.boot_completed` 后、非阻塞 | 依赖系统/包管理就绪的工作 | 作为必须早期执行的唯一机制 |
| `action.sh` | 用户触发、同步 | 短小、受控的显式操作 | 长任务、任意 shell、无确认的破坏操作 |
| `uninstall.sh` | 删除目录前、同步 | 清本模块外部资源 | 删除共享路径或假设完整系统已启动 |

官方文档曾把 post-fs-data 描述为约 10 秒限制；当前源码此处仍标注 `TODO: Add timeout`。
所以设计上必须像有严格超时一样短小，但**不能依赖某个硬超时替你终止死锁**。在
`post-fs-data.sh` 需要改属性时用 `resetprop -n <key> <value>`，不能用 `setprop`，后者可能
使启动死锁。

### late-load、safe mode 与 initrc 的交叉影响

late-load 的 `ksud late-load` 在系统已启动后加载内核模块。此模式跳过普通
`post-fs-data.sh`/`post-fs-data.d`，改跑 `late-load.sh`/`late-load.d`，然后依次加载
`system.prop`、执行 metamodule mount、`post-mount`、`service`、`boot-completed`。检测条件是
`KSU_LATE_LOAD=1` 或 `KSU_RUNTIME_MODE=late-load`；如模块声明支持它，必须分别测试两个分支。

KernelSU 安全模式会禁用普通模块脚本和模块，但模块 `initrc` 的注入发生得更早，坏 RC 仍可能
导致无法启动。不要把 initrc 用作普通服务的方便替代；每个会改启动路径的模块都须提供不依赖
initrc 的禁用/救援方案。

## 属性、SELinux 与 initrc

### `system.prop`

`system.prop` 每行使用 `key=value`，由 KernelSU 通过 resetprop 加载。用它表达可验证、
范围小的属性覆盖；不要试图写入只读 `/system`，也不要把秘密、设备唯一标识、长日志或未经
校验的用户文本写入属性。

属性会影响全局行为，可能与 ROM、其它模块或 Android 版本冲突。每个属性都记录原值、依赖和
关闭/卸载后的预期；在最低/最高支持 API、冷启动、覆盖更新和安全模式做回归测试。

### `sepolicy.rule`

活动模块的 `sepolicy.rule` 会在启动阶段尝试动态加载；加载失败只会记录警告并继续，故安装成功
不等于规则生效。`ksud sepolicy check` 只做规则的语法/解析检查，**不证明**实际内核已加载、
目标 label 正确或访问可用。

编写规则时：

1. 先收集精确 `avc: denied`、进程 context、对象 context、调用路径与最小复现。
2. 优先缩小文件路径、domain、type 和操作集合；不要宽泛 `allow`、全局 permissive 或
   `setenforce 0`。
3. 在 enforcing SELinux、目标 ROM 和冷启动中验证真实操作；升级 KSU/ROM 后复查。
4. 把 policy 失败看作安全失败，不以“临时关闭 SELinux 后可用”作为发布结论。

### `initrc/`

标准启动下，启用模块的 `initrc/*.rc` 会被合并进将在下一次启动注入 init 的 `modules.rc`：

- 仅收集 `.rc`；模块间按 ID、同模块内按文件名字母序。禁用或待移除模块不会被收集。
- 模块内 `initrc/` 的 `.rc` 不要求可执行位；全局 `/data/adb/initrc.d/` 文件则要求可执行，
  且全局文件先于模块文件。
- `ksud initrc refresh` 可重建生成文件，但改变在下次启动才被 init 看到。
- late-load 无 initrc 注入；修补时的 `--no-custom-rc` 也可关闭此能力。

RC 中明确 `user`、`group`、`seclabel`、启动/停止条件和失败路径。不要注册一个永久重启的
service，也不要让 RC 改写其它模块的服务/属性；它比普通 shell 更早、更难被安全模式拦截。

## 配置、WebUI、原生与 Zygisk

### 模块配置 API

模块脚本可调用 `ksud module config` 的 `get`、`set`、`set --temp`、`list`、`delete` 与
`clear`。同 key 的临时配置优先于持久配置；临时值会在每次启动的 post-fs-data 早期清除，
卸载时两类配置均清除。

```sh
mode=$(ksud module config get feature_mode 2>/dev/null || true)
case "$mode" in ''|safe|fast) ;; *) mode=safe ;; esac
ksud module config set feature_mode "$mode"
```

当前约束为每模块最多 32 项、key 最多 256 bytes、value 最多 1 MiB；key 使用与 module ID
相同的正则。把 key 视为固定 schema，写入前限制大小，读取后再次验证类型/枚举/JSON，配置文件
不是可信输入。多行值可经 stdin 写入，不能被拼入 shell。

- 使用持久值保存用户偏好，使用 `--temp` 保存本次启动状态。
- `override.description` 可安全地显示简短、脱敏的动态状态；不能当日志或秘密存储。
- `manage.su_compat` 与 `manage.kernel_umount` 是当前受支持的 managed feature key。只有模块
  确实负责该全局功能且能回滚时才设置；停止负责/卸载时删除 key，避免多个模块争夺控制权。

详细 API、WebUI 调用面和 shell 注入防护见
[webui-config-security.md](webui-config-security.md)。

### WebUI 是 root 权限程序

`webroot/index.html` 是 Manager WebUI 入口；资源应完全本地打包。当前 Manager 给页面注入
`window.ksu`，其 `exec`/`spawn` 最终以 root shell 运行，且 command、`cwd`、`env`、args 的
实现会组装 shell 文本。因此：

- 不加载远程 JS/CSS/CDN/WASM；离线启动也应可用。
- WebUI 只调用模块打包的固定 helper 和固定子命令，shell 端再次白名单校验。
- 不把用户输入、URL 参数、文件名、配置或包名直接拼进 command、args、cwd、env；不用
  `eval`、`$()`、反引号、`sh -c` 或管道下载执行。
- 短任务才用同步 `exec`；长任务用 `spawn`，显示脱敏 stdout/stderr、exit code、取消与恢复。
- 在禁用、待更新、待移除时不给出“已生效”的假成功；普通浏览器无 bridge 时安全降级。

### 原生 payload 与 Zygisk

只有 shell 不足以满足性能、协议或长期守护时才打包 native binary。按 ABI 放在模块私有的固定
路径，启动时选择明确 ABI、验证文件存在/可执行/版本，使用绝对路径；不从网络下载执行文件，
不把可写目录加入 `PATH`，不随意启动多个 daemon。native daemon 要处理 pidfile、重复启动、
退出、禁用、卸载、升级、SELinux label、socket 权限与崩溃恢复。

KernelSU 核心**没有内建 Zygisk**。Zygisk 模块必须依赖用户已安装且启用的兼容实现（例如明确
支持 KSU 的独立 loader），并在安装前检查 ABI、API、loader/version；`KSU=true` 不证明
Zygisk 可用。按所选 loader 的公开 ABI/目录/入口契约实现，不能从 Magisk 私有实现猜测。
详细样式、测试矩阵和公开项目边界见
[native-and-zygisk.md](native-and-zygisk.md)。

## 安全、诊断、救援与发布验收

### 安全底线

把每个模块视为用户授权的 root 程序：

- 审计安装脚本、native binary、WebUI、远程更新、下载、SELinux 规则和所有 root 命令。
- 不请求或收集无关设备标识、密钥、令牌、完整私有日志；不把它们写进 ZIP、WebUI、配置、
  属性或公开 description。
- 不执行 `curl | sh`、不信任可写配置中的命令/路径、不自动刷分区/删除数据、不承诺绕过
  银行/反作弊/企业安全检测。
- 对破坏性 Action 显示具体目标和副作用，要求确认，提供幂等性、日志与恢复路径。
- 优先最小权限和可回滚设计；`/apex`、关键系统库、loop/image、initrc 与广泛 sepolicy 都是
  高风险功能，需单独评审。

### 出问题时先采证据

报告或复现模块问题时，至少收集：模块 ZIP hash/版本、module ID、KSU/Manager/ksud 版本、
runtime mode、设备/ROM/API、内核/KMI、活动 metamodule、其它模块、完整安装输出、`logcat`、
相关 `dmesg`/AVC、`/proc/1/mountinfo` 与目标进程 mountinfo、预期/实际和最小复现。把
“首次安装成功、覆盖更新失败、禁用后仍可见、App 看不见挂载”等状态分开报告。

已关闭 issue 的常见教训可在 [issue-case-ledger.md](issue-case-ledger.md) 和其
`issue-ledgers/` 中按编号/关键词检索。closed 只表示 issue 生命周期结束，不能替代当前源码
阅读、维护者证据或真实设备复测。

### 救援设计

所有高风险模块在发布前测试这些路径：

1. KernelSU 安全模式（开机第一屏后快速按下、松开音量下超过三次）能禁用普通模块。
2. 可启动/ADB root 时用 `ksud module disable <id>` 或 `ksud module uninstall <id>`，再重启。
3. `uninstall.sh` 缺失、失败、重复运行时仍能恢复；模块不删除共享 KSU 基础文件。
4. 刷入前保留可回刷的原厂 boot/已知可启动 boot，并写明设备特定恢复步骤。

若安全模式无效且只能 Recovery 急救，官方流程会删除 `/data/adb/ksud`，并可删除生成的
`/metadata[/watchdog]/ksu/modules.rc` 以阻止模块加载。这是**紧急救砖**，会改变 KSU 的
用户态加载能力，不是常规卸载、升级或测试清理方法。坏 initrc 可能在安全模式仍执行，正是
必须把它作为高风险功能的原因。

### 发布前最小验收矩阵

在声明支持每一种设备/版本前，完成并记录：

1. **包结构**：ZIP 根有 LF `module.prop`；ID/目录一致；无私钥、token、host binary、
   `node_modules`、构建缓存、source map 或未用 payload。
2. **安装状态机**：初装、覆盖更新、重启切换、禁用、启用、卸载、失败重试和回滚均测试；不手改
   KSU 内部目录。
3. **生命周期**：每个脚本在正确 stage、正确 runtime mode 下只做预期工作；早期脚本不会死锁/
   长阻塞；service/daemon 可退出且无重复实例。
4. **挂载**：无 metamodule、目标 metamodule、不同 ROM 分区布局、`skip_mount`、tombstone、
   app/system_server namespace 都测；若含 `system/`，冷启动后验证真实消费者，而非仅 root shell。
5. **安全与 policy**：enforcing SELinux；每条 rule 有 AVC/最小化依据；WebUI 离线、无 bridge、
   恶意输入、连续点击、失败重试、Manager 重启、秘密扫描均通过。
6. **原生/Zygisk（如适用）**：所有打包 ABI、最低/最高 API、loader 缺失、目标进程崩溃、
   disable/uninstall/upgrade 和 mount namespace 都测试。
7. **救援**：说明中给出 `disable`/`uninstall` 和设备恢复路径；在测试机演练至少一次故障恢复。

可先用本技能的 `scripts/scaffold_module.py` 生成保守骨架，以
`scripts/validate_module.py` 检查 ZIP/目录契约，再用 `scripts/pack_module.py` 构建发行包；
这些本地检查不能替代设备验收。

## 来源与进一步阅读

- `website/docs/zh_CN/guide/module.md`：模块结构、安装器变量、脚本阶段、OverlayFS、initrc、
  late-load、BusyBox 与 Zygisk 边界。
- `website/docs/zh_CN/guide/module-config.md`：持久/临时配置、上限、动态 description、
  managed features。
- `website/docs/zh_CN/guide/metamodule.md`：单元模块约束、mount/install/uninstall 钩子。
- `website/docs/zh_CN/guide/rescue-from-bootloop.md`：安全模式、`ksud` 与 Recovery 急救路径。
- `userspace/ksud/src/module.rs`：ID 校验、脚本环境、staging/更新/删除、initrc 收集、Action。
- `userspace/ksud/src/installer.sh`：安装期变量、`SKIPUNZIP`、`REMOVE` 与当前 `REPLACE` 风险。
- `userspace/ksud/src/init_event.rs`、`late_load.rs`：当前生命周期实际排序与阻塞性。
- `userspace/ksud/src/module_config.rs`、`sepolicy.rs`：配置上限、临时清理、policy apply/check 差异。
- `manager/.../WebViewHelper.kt`、`WebViewInterface.kt`：WebUI asset loader、bridge 与 root shell
  风险。
