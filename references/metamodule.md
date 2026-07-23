# KernelSU metamodule（元模块）实现参考

> 适用对象：需要为 **多个普通 KernelSU 模块** 提供 `system/` systemless
> 挂载能力的元模块作者，以及需要判断自己的普通模块是否应依赖元模块的作者。
> 本文不是把任意 Magisk 挂载脚本直接改名为 KernelSU 脚本的指南；元模块的错误会
> 影响所有普通模块，必须优先保证可停用、可清理、可救援。
>
> 取证基线：本机 `tiann/KernelSU` checkout
> `87a62b76c9d3dd31495f63508469601237b1ad09`（2026-07-23），官方 Guide 的
> metamodule/module 页面，以及本机可读的三个开源元模块样本。KernelSU、ksud、内核、
> Manager、ROM 和 SELinux 会独立演进；发布前必须在目标设备上复核。

## 目录

1. [先判断是否真的需要元模块](#先判断是否真的需要元模块)
2. [身份、活动元模块与安装限制](#身份活动元模块与安装限制)
3. [三个元模块 hook 的实际契约](#三个元模块-hook-的实际契约)
4. [启动时序与 late-load](#启动时序与-late-load)
5. [挂载、KSU 标识与自动卸载信号](#挂载ksu-标识与自动卸载信号)
6. [OverlayFS、bind mount 与持久镜像的风险](#overlayfsbind-mount-与持久镜像的风险)
7. [失败、回滚、卸载与救援](#失败回滚卸载与救援)
8. [三个开源样本怎样借鉴](#三个开源样本怎样借鉴)
9. [发布前测试矩阵](#发布前测试矩阵)
10. [文档与源码不一致时的保守规则](#文档与源码不一致时的保守规则)

## 先判断是否真的需要元模块

### 结论

普通模块只有在需要让其 `system/` 内容以 systemless 方式出现在 `/system` 视图时，
才依赖一个兼容且活跃的 metamodule。下面这些能力本身 **不需要** 元模块：

- `post-fs-data.sh`、`late-load.sh`、`post-mount.sh`、`service.sh`、`boot-completed.sh`；
- `system.prop`、`sepolicy.rule`、`initrc/*.rc`（受运行模式限制）；
- 模块私有数据、配置、CLI、WebUI、native daemon；
- 自己在 `post-mount.sh` 中明确实现并测试的非 `/system` 挂载。

因此，不能把“没有元模块时模块完全不能工作”写成通用结论。正确的说明应是：

```text
本模块的脚本/配置功能：是否可独立工作？
本模块的 system/ 覆盖：没有兼容的活跃 metamodule 时不会挂载。
重启要求：哪些改动必须下次启动才生效？
```

### 选择路径

```text
需求只是脚本、属性、策略、服务或 WebUI？
  └─ 是：做普通模块；不要为此新建 metamodule。

需求是一个普通模块覆盖 system/ 中的文件？
  └─ 是：声明/检测已安装的兼容 metamodule；不要接管其它模块。

需求是为多个普通模块实现 system/ 挂载引擎？
  └─ 是：才考虑 metamodule，并实现本文全部安装、扫描、挂载、清理、失败恢复契约。
```

不要为了一个普通模块的 `system/` 文件覆盖另写元模块。元模块在机器上是全局基础设施；
它的策略、忽略列表、挂载后端、错误和升级都会影响其它模块作者的 payload。

### 普通模块作者的依赖边界

若普通模块含有 `system/`：

1. 在 README/安装器中明确列出支持的元模块、最低版本、已知 ROM/内核限制和重启要求。
2. 没有兼容元模块时，选择清楚地拒绝安装、只启用非挂载功能，或显示“system payload 未生效”。
3. 不要自行创建全局 OverlayFS、随意扫描/修改其它模块目录，或假定任意 metamodule 都兼容。
4. 在 `skip_mount` 存在、模块被禁用、待删除、更新尚未切换时，不能报告“覆盖已生效”。

## 身份、活动元模块与安装限制

### 声明元模块

元模块根目录的 `module.prop` 必须有普通模块身份字段，且额外声明：

```properties
id=example-metamodule
name=Example metamodule
version=1.0.0
versionCode=1
author=Example Author
description=为普通模块提供可恢复的 systemless 挂载
metamodule=1
```

当前 `ksud` 以 `metamodule=1`，或不区分大小写的 `metamodule=true` 识别元模块。
其它值不是元模块。将该字段写成 `yes`、`on`、空值或多余格式，不应当作兼容声明。

`id` 仍是稳定主键；不能通过改 ID 达到“并行安装两个后端”或“绕过冲突”的目的。
模块 ZIP、目录和 `module.prop` 的 ID 契约仍适用，详见 `core-contract.md`。

### 活动元模块不是任意扫描结果

当前实现通常以：

```text
/data/adb/metamodule -> /data/adb/modules/<active-meta-id>
```

作为活动元模块的符号链接；必要时会回退扫描 `module.prop`。应用或模块不得手动创建、替换、
删除这个链接，也不得直接操作 `/data/adb/modules` 或 `modules_update` 来“切换后端”。
应走 KernelSU Manager 或受支持的 `ksud module install`/卸载流程。

### 一次只能有一个活动元模块

当前源码的核心规则是：

- 同时只能安装一个 **不同 ID** 的元模块；尝试装第二个不同 ID 的元模块应失败。
- 更新同一个元模块 ID 是允许的；它仍须经历 staging 和下次启动切换。
- 安装普通模块时，若活动元模块有 `metainstall.sh`，但该元模块被 `disable`、或带有
  `update`/`remove` 标记，安装会被拒绝，而不是悄悄跳过 hook。
- 元模块自身的安装不会调用它自己的 `metainstall.sh`。
- 活动元模块带 `disable` 时，元模块 hook 会被跳过；不要把“脚本文件存在”当作“引擎已工作”。

这意味着“更换元模块”是一次有停机和救援计划的迁移，不是普通模块的覆盖升级。先备份
所需配置、卸载/切换旧后端、重启并验证挂载，再安装依赖新后端的普通模块。

### 作者不可假定的状态

`disable`、`remove`、`update`、`skip_mount`、staging 目录与 Manager 展示状态可能不同步。
元模块必须在实际执行点重新检查模块目录、标记文件、ID、内容和挂载结果；不要以安装期
缓存或 WebUI 显示的状态替代启动时检查。

## 三个元模块 hook 的实际契约

### 总览

| 文件 | 用途 | 调用对象/时机 | 当前失败结果 | 作者必须保证 |
| --- | --- | --- | --- | --- |
| `metainstall.sh` | 接管普通模块安装的最后安装步骤 | 安装普通模块；不用于安装元模块自己 | 安装失败；保留受安装器流程约束的 staging | 验证输入，且恰好一次完成 `install_module` |
| `metauninstall.sh` | 删除普通模块前清理元模块拥有的外部资源 | 处理普通模块卸载时 | 仅记录警告，核心删除继续；无事务回滚 | 幂等、限定到被删模块、即使资源缺失也安全 |
| `metamount.sh` | 启动期发现并挂载合格普通模块的 payload | 所有普通模块早期脚本/属性之后，`post-mount` 之前 | 仅记录警告，后续 `post-mount` 仍继续 | 原子化或自清理的挂载图，成功才通知内核 |

不要把这三个文件当作普通模块的同名脚本，也不要让它们读取、`source` 或执行来自未验证
普通模块、WebUI、网络或可写共享目录的 shell 文本。

### `metainstall.sh`：安装接管

普通安装器会把模块放在 `/data/adb/modules_update/<id>` staging 区，下一次早期启动才会
切换为活动 `/data/adb/modules/<id>`。`metainstall.sh` 必须把这一事实视为边界：不得直接把
payload 写进活动模块目录，不得试图立即让新模块的早期 mount 生效。

当前源码的实际执行方式是把内置安装器内容、`metainstall.sh` 文本和 `exit 0` 拼接后交给
BusyBox `sh -c`。功能上，它仍能访问安装器函数；但它不是可依赖的“以文件路径 source”语义。
特别是不要依赖 `$0`、`return`、source stack、工作目录或文件描述符的历史行为。

与默认安装路径不同，当前元模块接管路径不会在 hook 之后自动追加 `install_module`。因此
`metainstall.sh` 应在通过全部前置校验后调用 **恰好一次** `install_module`。零次会留下没有
完成默认安装语义的模块；多次会导致重复解压、权限/label 混乱或覆盖不可预测。

安全骨架如下；函数名是当前安装器接口，具体能力仍须随 KernelSU 版本验证：

```sh
#!/system/bin/sh
# metainstall.sh：运行在 KernelSU BusyBox 安装器拼接的 shell 中
set -eu

# 仅检查本元模块明确支持的条件：KSU、ABI、API、磁盘空间、后端能力等。
# 对模块 ID、路径、压缩包条目和所用配置做严格验证；失败时使用安装器的 abort。

# 如有需要，在安装器已提供的 staging 路径内准备元数据或外部存储；
# 不写 /data/adb/modules/<id>，不扫描或清除别的模块。

install_module               # 当前接管路径必须且只能调用一次

# 仅在成功安装之后做可回滚的轻量收尾；不要启动长期 daemon 或创建挂载。
```

`metainstall.sh` 的设计要点：

- 首先拒绝不支持的内核、ABI、文件系统、Android API 或存储空间，而不是在半安装后继续。
- 若要把 payload 移到内容镜像/外部存储，先验证归属、大小、hash/文件清单、SELinux label 和
  失败清理；metadata 与 content 分离时仍要保持卸载可定位。
- 不要无条件覆盖用户配置；采用明确白名单、备份、迁移和原子 rename。
- 不启动服务、不挂载、不假设当前启动立即生效；这些属于重启后的启动路径。
- 不使用普通模块提供的 `customize.sh` 作为可信 API；它是模块作者的安装脚本，不是后端控制面。

### `metauninstall.sh`：删除前清理

`metauninstall.sh` 只用于 **普通模块** 被删除时的元模块清理；删除元模块自身时，核心会先处理
元模块链接，再运行它自己的普通 `uninstall.sh`，而不是把它当成一个普通模块传给
`metauninstall.sh`。

当前源码以环境变量提供删除目标：

```sh
MODULE_ID=${MODULE_ID:?missing module id}
```

不要采用官方旧示例中的 `MODULE_ID="$1"`。当前调用没有保证位置参数 `$1`；若将空值拼进
路径或 `rm` 命令，会将一次普通模块卸载扩大为共享数据损坏。

安全骨架：

```sh
#!/system/bin/sh
set -eu

MODULE_ID=${MODULE_ID:?missing module id}
case "$MODULE_ID" in
  [A-Za-z][A-Za-z0-9._-]*) ;;
  *) exit 0 ;;              # 不对异常 ID 执行清理
esac

# 仅清理本元模块以该 ID 建立且可证明归属的 image、状态记录、mount 记录或临时目录。
# 每个删除目标使用固定根路径和精确白名单；不存在时也应成功。
# 不能删除 /data/adb/modules、别的模块状态、共享 image 或整个挂载根。
```

核心对 `metauninstall.sh` 失败只记警告并继续普通模块删除；它不提供事务、重试或自动 rollback。
所以 hook 必须能够处理重复运行、模块目录已消失、上次挂载失败、镜像不存在和部分升级状态。
任何不能安全确认归属的资源宁可保留并报告诊断，也不要递归删除。

### `metamount.sh`：启动期全局挂载引擎

`metamount.sh` 运行时，普通模块的早期脚本和 `system.prop` 已按核心顺序处理，但并不表示每个
模块都适合挂载。元模块应自行筛选：

- 只考虑当前普通模块集合；不把自身或私有缓存误当 payload；
- 跳过带 `disable`、`remove`、`skip_mount` 的模块；
- 仅在确有已验证的可挂载内容时处理；脚本型模块不应获得空目录/重复挂载；
- 处理模块 ID、软链接、路径穿越、重复 owner、嵌套目标、文件/目录冲突和后端 blocklist；
- 对每个实际目标记录明确 owner、source、mount 类型和清理动作。

官方说明把 `MODDIR` 列为 `metamount.sh` 环境变量，但当前源码没有显式导出它。不要依赖它；
从脚本路径推导元模块根目录：

```sh
#!/system/bin/sh
set -u
MODDIR=${0%/*}
readonly MODDIR

# 读取只受本元模块控制的配置；逐项扫描候选模块并建立 mount plan。
# 先验证全部 plan，再按父/子关系执行；任一关键步骤失败则卸载本轮已创建的挂载。
# 只有 plan 完整成功且 mountinfo 可见时才通知 KernelSU。
```

当前核心对 `metamount.sh` 非零退出也只记录警告，仍继续 `post-mount`。因此不能用“退出非零”
代替回滚；必须在脚本/二进制内部执行反向卸载、关闭镜像、删除临时目录，并把失败状态保存为
可诊断但不会在下次启动扩大问题的记录。

## 启动时序与 late-load

### 标准模式的关键顺序

以下是当前源码级别的简化顺序。它说明 hook 在哪里运行，不代表每项都可安全做网络、UI 或
长时间 I/O：

```text
early boot / post-fs-data:
  处理 updates、remove、恢复 label/SELinux 等核心准备
  活动元模块 post-fs-data.sh
  普通模块 post-fs-data.sh
  加载普通模块 system.prop
  活动元模块 metamount.sh                 ← 建立 systemless 可见性
  模块 post-mount.sh

late_start:
  service.sh

boot completed:
  boot-completed.sh
```

同一 stage 中元模块优先于普通模块。元模块不要在 `post-fs-data` 或 `metamount` 等待网络、
解锁、外置存储或人为输入；这些阶段卡住会放大为启动缓慢或 bootloop。需要较晚资源的控制
daemon 应放入受控的 `service.sh`，且不能把其“将来会修好”作为早期挂载失败的借口。

### late-load 不是标准启动的轻量别名

late-load 在 Android 已启动之后工作：它以阻塞的 `late-load` stage 取代标准的早期
`post-fs-data` 工作，随后仍会运行 `metamount`、`post-mount`、`service` 和 boot-complete
相关 stage。对元模块而言，挂载发生得更晚，目标进程、包扫描或系统服务可能已经观察过旧
文件视图。

late-load 的保守规则：

- 明确检测 `KSU_LATE_LOAD=1` 或 `KSU_RUNTIME_MODE=late-load`，不要只根据文件名猜测。
- 不宣传需要极早挂载、init 服务注册、开机前包扫描或安全模式交互的 payload 在 late-load
  上“等价可用”。当前官方表格对 initrc、early hook 和 safe-mode 行为有额外限制。
- 以“模块在 shell 中看到文件”之外的实际目标进程验证；必要时要求重启/重启目标进程，或在
  late-load 下拒绝该功能。
- 单独测试标准与 late-load；不能把其中一个的成功迁移为另一个的兼容承诺。

## 挂载、KSU 标识与自动卸载信号

### 挂载 source/设备名约定

官方 metamodule 指南规定：元模块创建的相关 mount source/设备名应为 **`KSU`**。

- 使用新 mount API 时，在 `fsconfig` 中设置 `source=KSU`；
- 使用 legacy OverlayFS `mount(2)` 时，同样传入 source `KSU`；
- bind/magic mount 后端也应明确记录实际 source 和 target，不能把匿名临时路径当成协议。

该标识是 KernelSU 生态的约定，便于挂载识别和管理；它不是通用安全边界，也不证明目标路径
已经在所有 namespace 可见。

### `notify-module-mounted` 的正确时机

当前用户态命令：

```text
ksud kernel notify-module-mounted
```

会向内核发出 `EVENT_MODULE_MOUNTED`。当前内核处理只会将 `ksu_module_mounted` 设为真；因此
它应在 **所有必需 mount 已成功、已核对 `/proc/*/mountinfo`、且没有待清理的半完成步骤之后**
调用。

绝不能：

- 在扫描模块前、建立第一层 mount 后、或仍有关键 child mount 失败时调用；
- 用“脚本 exit 0”代替实际检查；
- 因为另一个元模块样本没有通知就假定所有设备/后端都不需要或都需要它。

`meta-magic_mount-rs` 和 `meta-hybrid_mount` 的脚本都在其挂载二进制成功后才通知；
`meta-overlayfs` 的 `metamount.sh` 成功后只退出，没有调用此命令。这个差异说明样本行为
不是通用 API 保证，元模块应结合目标 KernelSU/内核、后端和实机验收决定。

### source `KSU` 不等于自动登记卸载目标

当前内核的自动卸载逻辑还依赖用户态通过显式 umount-list 接口登记目标路径，例如由元模块
调用相应 `ksud kernel umount add ...` 命令。仅给 mount source 标成 `KSU`，不会把 target
自动加入该列表；仅通知 `notify-module-mounted` 也不会创建列表。

因此实现必须分别测试：

1. source/设备名是否为 `KSU`；
2. 每个需要 KernelSU 管理的 target 是否已按当前接口明确登记；
3. 自动卸载触发时，所有 parent/child mount 是否按正确顺序消失；
4. 未登记的 mount 是否有模块自己的安全清理路径。

不要把 `KSU` 标签、`notify-module-mounted` 和“KernelSU 会自动卸载一切”混为同一承诺。

### `skip_mount`、禁用与自挂载模块

普通模块的 `skip_mount` 是一个重要的协作标记。元模块应跳过它；自行实现挂载的模块也应把
自己的内容排除出元模块扫描，或通过明确 blocklist/policy 避免双重挂载。双重 bind/overlay
常见后果是路径遮蔽、递归 lowerdir、卸载顺序错误和不可恢复 bootloop。

同理，`disable` 表示不应执行该模块的系统性行为；`remove` 表示该模块处在删除路径。不要
为“修复兼容”而无视这些 marker。

## OverlayFS、bind mount 与持久镜像的风险

### 先构建 mount graph，再执行

`/system/vendor`、`/system/product`、`/system/system_ext` 可能是 `/vendor`、`/product`、
`/system_ext` 的软链接，也可能对应独立分区或 ROM 特有布局。错误地先挂父路径、再处理子路径
会遮蔽 child mount；错误地把软链接当普通目录会把内容落在意外位置。

推荐流程：

1. 读取真实 symlink、mountinfo、文件类型、SELinux context 与可写/可挂载能力。
2. 从候选模块内容构造规范化的 source→target graph，拒绝 `..`、重复 owner、循环和目标冲突。
3. 先预检全部父/子关系、后端能力、磁盘空间和可用 namespace。
4. 按确定顺序创建；每创建一步就记录反向操作。
5. 对 child mount 失败，按反序卸载本轮已创建的所有层，绝不继续留下部分视图。
6. 最后在 init、目标 app/system_server（如适用）的 namespace 分别验证，而不是只看 root shell。

### OverlayFS 特有风险

- lowerdir 顺序决定覆盖优先级；模块排序、重复文件和 opaque directory 必须有明确、可解释
  的 policy，不能依赖目录遍历偶然顺序。
- whiteout/tombstone、opaque 目录、xattr、权限、所有者和 SELinux label 需要逐项保留/验证。
  “能列出文件”不等于系统服务能读取/执行。
- `system/` 中的字符设备 `c 0 0` 可表达隐藏下层条目的语义；它不是删除真实 `/system` 文件。
  不要在 install/uninstall 中直接修改真实系统分区。
- `REPLACE` 不应被当作跨版本可靠的 opaque directory 能力。当前安装器可见 `mark_replace`
  调用，但当前核心找不到对应定义；若确需 opaque 语义，必须在锁定的目标元模块/内核/ROM 上
  明确操作、做白化与恢复测试，并在发布说明标为需实机验证。
- upperdir/workdir 的底层文件系统、空间、inode、崩溃恢复和 SELinux 会决定 OverlayFS 是否
  可用；失败时不能静默退化为半覆盖。

### bind/magic mount 特有风险

- bind mount 对单个文件、目录、权限、递归标志、共享传播和 namespace 极为敏感；在 root
  namespace 成功不代表 app namespace 成功。
- Magic Mount 一类实现通常需要建立路径树、逐项目标绑定并登记清理。任何一个中间路径、
  SELinux label 或传播标志错误，都可能让用户只看到部分覆盖。
- 模块只应挂自己拥有或以声明式 policy 分配的目标；禁止用宽泛 glob 接管其它模块、`/data/adb`
  或系统全树。
- 回滚要按创建的反序执行，并检查 mount point 仍由本模块拥有；不可对未知 mount 执行盲目
  `umount -l`，否则会破坏其它基础设施。

### 内容镜像（例如 ext4 image）不是免费隔离

有些元模块把普通模块 payload 迁入 ext4 image，再在启动期挂载镜像。这样可隔离 metadata
与 content，但增加了：镜像大小规划、稀疏文件实际占用、文件系统检查、label 保留、loop/
挂载失败、升级迁移、断电一致性与删除归属的风险。

若采用镜像，必须：

- 限制每模块路径和镜像名为已验证 ID；不接受任意文件名；
- 检查可用空间、镜像大小上限、挂载成功、内容完整性及 unmount 后再清理；
- 在 `metauninstall.sh` 中只删除能证明属于 `MODULE_ID` 的镜像；
- 为镜像创建、迁移、损坏、空间耗尽和中途掉电设计可恢复状态机；
- 不因为“安装成功”就删掉唯一可回退的旧内容。

## 失败、回滚、卸载与救援

### 核心不会替元模块做事务

`metainstall.sh`、`metauninstall.sh`、`metamount.sh` 都不是核心提供的 ACID 事务。特别是：

- `metauninstall.sh` 失败后，普通模块删除仍继续；
- `metamount.sh` 失败后，核心仍会走后续 `post-mount`；
- 更新安装在 staging 与下次启动切换之间存在状态窗口；
- 内核/ROM 的 mount 清理、namespace 与 label 行为不能由脚本退出码替代。

元模块必须自己维护最小状态：本轮事务 ID、已成功创建的 mount、每个 target 的 owner、镜像/
临时目录、反向动作、失败原因和版本。状态文件放在元模块明确拥有的私有根，原子写入，并在
下一次启动时先处理未完成事务。不要将状态放在每个普通模块不可控的任意可写文件中。

### 挂载失败的处理模型

```text
发现候选模块
  -> 全部预检通过？否：不创建 mount，记录可读原因
  -> 建立 parent/child mount graph
  -> 任一步失败？是：反序执行本轮 cleanup，验证无残留，再返回失败
  -> 全部成功：检查每个 target、所需 namespace、登记的 auto-umount list
  -> 全部验证通过：notify-module-mounted
```

“尽力继续”只适用于与其它模块完全无关、已显式声明可降级的功能；不能用于同一条系统路径的
一半层级。若一个系统路径的 owner/后端冲突，安全默认是拒绝该路径并诊断，而不是最后写入者
获胜。

### 卸载与后端迁移

- 普通模块卸载：`metauninstall.sh` 清外部资源，普通 `uninstall.sh` 清该模块自己的资源，
  两者都必须幂等；不要假设调用顺序以外的共享资源仍存在。
- 元模块卸载：应把它当成全局后端移除。确保活动链接、挂载、登记清单、daemon、镜像、状态和
  后续普通模块行为都有明确迁移/禁用计划；不要让普通模块变成表面启用、实际遗留 mount。
- 更换元模块：先关闭/卸载旧后端并重启验证清理，再安装新后端和重新验证。不要尝试两个不同
  ID 元模块并存，也不要绕过单实例约束。
- 升级失败：保留足够日志和旧配置备份，避免删除旧 image/状态；必须能在禁用该元模块后安全
  启动并恢复到无挂载或旧已验证状态。

### 救援设计

发布包、README 和 WebUI 至少提供：

1. 明确的模块 ID、版本、后端、受影响目标与关闭/卸载方法；
2. 不依赖网络、WebUI 或 daemon 的本地 CLI/Action 诊断与禁用路径；
3. 安全模式、Manager 可用时的停用说明，以及设备无法启动时仅针对该模块目录的恢复步骤；
4. 日志位置、挂载表采集方法、未完成事务标志和如何避免把日志/配置误删；
5. 不使用全局 `killall`、全局 `rm -rf`、盲目 lazy unmount 或删除共享 `/data/adb` 目录的
   承诺。

救援脚本也需要输入校验和最小范围。无法确定资源归属时，保留残留并让用户人工检查，优于
为了“自动清理”删除其它模块/系统的资源。

## 三个开源样本怎样借鉴

下面是本机源码审阅到的代表性实现，均是 **第三方样本，不是 KernelSU API 规范**。许可证、
内核要求、存储格式、hot-install 行为、mount namespace 策略都不同，不能复制后宣称通用。

| 样本 | 可借鉴的源码模式 | 需特别避免的误读 |
| --- | --- | --- |
| `KernelSU-Modules-Repo/meta-overlayfs`（commit `7143eb7`） | `metamodule=1`；安装期调用 `install_module`，将 content 放入 ext4 image；`metamount.sh` 用 `MODDIR=${0%/*}`；Rust 中先处理子挂载并有失败回滚；现代 `fsconfig` 与 legacy mount 都设置 `KSU` source。 | README 自称非生产级；镜像、upper/workdir、白化、嵌套 mount 和空间失败都有 bootloop 风险。其脚本成功后没有调用 `notify-module-mounted`；而且分区级失败可能仅记录后继续，不能把它解释为生产级成功判定。 |
| `Tools-cx-app/meta-magic_mount-rs`（commit `8340ca9`） | `metainstall.sh` 调用 `install_module`，处理 `/system/{vendor,product,system_ext}` 布局和 `skip_mount`；挂载成功后才执行 `ksud kernel notify-module-mounted`；实现显式登记可卸载 target。 | 它的 `metauninstall.sh` 实际为空操作，不能用来证明普通模块外部资源都会被清理；其 magic/bind 策略、TOML、hot-install 和 blocklist 是项目 policy，不是默认策略。 |
| `Hybrid-Mount/meta-hybrid_mount`（commit `aaae7b6`） | 同样从脚本路径推导 `MODDIR`；`metauninstall.sh` 使用 `MODULE_ID` 环境变量；挂载二进制成功后才通知；对 Overlay、Magic、Kasumi 类后端使用声明式策略及明确的 unmount 记录。 | 多后端、daemon、LKM、自动 source 检测和隐藏/规避相关能力不适合作为最小基线；其 hot-install 也有先删旧目录再移动的无回滚窗口，越复杂越需要失败恢复。 |

三个样本共同佐证的仅是“当前源码可行的工程模式”：元安装 hook 中显式 `install_module`、
`metamount.sh` 中自行推导根目录、把成功通知放在实际挂载之后。两个有实际删除逻辑的样本
读取环境 `MODULE_ID`；MMRS 的 `metauninstall.sh` 是 no-op，正好说明样本不能取代核心契约。
它们并不替代对当前 KernelSU 源码和目标设备的验证。

## 发布前测试矩阵

不要只测试“ZIP 安装成功”和“root shell 能看到文件”。每次支持一个新 Android/ROM/内核/后端
组合时，至少记录 KernelSU/Manager/ksud、元模块版本、ABI、API、SELinux enforcing 状态、
运行模式、其它已启用模块和完整 mountinfo。

| 场景 | 操作与注入 | 必须观察的结果 |
| --- | --- | --- |
| 纯脚本模块 | 安装不含 `system/` 的普通模块 | 不依赖元模块也能工作；元模块不为它创建空 mount。 |
| 基础 system payload | 安装一个只覆盖单文件的普通模块并重启 | 有兼容活跃元模块时目标可见；无元模块/有 `skip_mount` 时明确不挂载。 |
| 模块 metadata | 测试 `metamodule=1`、`true`、`TRUE`、错误值 | 仅当前源码认可的值成为元模块；错误值不会被误识别。 |
| 单实例 | 安装第二个不同 ID 元模块；更新同 ID 元模块 | 前者被拒绝，后者允许但遵循 staging/重启切换；不手改链接。 |
| 元模块状态 | 对活动元模块建立 `disable`、`update`、`remove` | hook 跳过/普通模块安装拒绝的实际行为符合当前核心；清理后才能继续。 |
| 安装 hook | 在 `metainstall.sh` 给 `install_module` 计数，并分别模拟校验失败 | 成功路径恰好一次；失败路径不留下活动目录、越权文件或半完成 image。 |
| 删除 hook | 卸载存在/不存在 image 的普通模块，重复执行清理 | 从环境读取正确 `MODULE_ID`；只清自家资源；hook 失败时普通删除继续且无共享误删。 |
| 停用/待删普通模块 | 分别创建 `disable`、`remove`、`skip_mount` | 扫描器全都跳过，不生成遗留 mount，不把它们计为成功。 |
| 分区布局 | 覆盖 `/system`、`/vendor`、`/product`、`/system_ext`，包括软链接布局 | target 正确、parent/child 顺序正确、无路径遮蔽；每种目标 ROM 单测。 |
| 同路径冲突 | 两个模块覆盖同一文件/目录、文件与目录冲突、嵌套目标 | 采用书面 policy 或拒绝；结果可解释、可重复，不依赖目录遍历顺序。 |
| Overlay 语义 | whiteout、opaque/替换目录、xattr、权限、label | 不修改真实系统；目标服务可读取；失败后全部回滚。 |
| bind/magic 语义 | 单文件、目录、递归/传播、卸载重启 | mount graph 完整，反向清理只影响本模块 owner，不能遗留遮蔽。 |
| SELinux | enforcing 下读取、执行、服务访问目标内容 | 不只在 permissive/root shell 成功；记录 context 和 avc，不能用宽泛 allow 规则掩盖。 |
| namespace | 对 init、system_server、目标 app 比较 `/proc/<pid>/mountinfo` | 目标消费者看到预期文件；看不到时明确标为不兼容或做受控补救。 |
| 自动卸载 | 检查 `KSU` source、显式 umount-list、通知前后行为 | source 标签、target 登记、`notify-module-mounted` 三者分别符合预期；parent/child 都能清。 |
| 通知时序 | 强制一个 child mount 失败 | 不发成功通知；反序清理后 mountinfo 无本轮残留。 |
| 镜像存储 | 空间不足、镜像损坏、升级迁移中断、掉电模拟 | 不丢旧可回退数据；能报告原因；下一启动可恢复/安全禁用。 |
| 标准启动 | 标准模式冷启动、热重启、多模块并存 | hook 顺序符合设计，不阻塞早期启动，所有目标一致可见。 |
| late-load | late-load 冷启动及目标进程已启动情况 | 不承诺早期语义；按功能判断拒绝/降级/重启目标进程，且无残留 mount。 |
| 升级与降级 | 更新元模块、更新普通模块、回到旧版 | staging、配置迁移、状态 schema、旧 mount 清理和版本不兼容都可恢复。 |
| 禁用与救援 | 停用元模块、普通模块、模拟 WebUI/daemon 不可用 | 设备可启动；CLI/Manager/安全模式步骤可执行；无需删除共享目录。 |
| 卸载/切换 | 卸载普通模块、卸载元模块、切换不同后端 | 没有孤儿 mount、loop/image、daemon、umount 条目或错误的活动链接。 |

测试日志至少保留：安装器输出、模块 ID/版本、`mountinfo`（init 和目标进程）、`ls -lZ`、
SELinux denial、后端状态、清理清单和失败注入步骤。截图或“感觉已生效”不能取代这些证据。

## 文档与源码不一致时的保守规则

当前实现与官方高层说明存在几处会影响安全性的漂移。制作或审计元模块时，按下列保守规则：

1. **`metainstall.sh` 的“source”表述**：官方文档写为 source；当前代码把 hook 拼进生成的
   BusyBox `sh -c` 脚本。可访问安装器函数不代表 `$0`、`return`、相对路径或 source 语义稳定。
   使用显式、最小的 shell 代码，并在目标版本做安装测试。
2. **`MODDIR`**：官方文档把它列为 `metamount.sh` 环境变量；当前源码未显式 export。统一用
   `MODDIR=${0%/*}`，不要在未设置时扩展为空路径。
3. **`MODULE_ID`**：官方示例可见 `MODULE_ID="$1"`；当前 `metauninstall.sh` 通过环境变量传入，
   未保证位置参数。用 `${MODULE_ID:?}` 再白名单校验。
4. **`KSU` source 与自动卸载**：文档推荐 source 标识，但当前内核的通知只设置 mounted flag，
   自动卸载 target 仍依赖显式列表。不要把 source tag 或通知等同于“所有 mount 自动管理”。
5. **“新模块需要元模块”**：高层文案过宽。以 `module.md` 和当前核心为准，只有 `system/`
   payload 的 systemless 挂载依赖元模块；脚本、属性、策略等可以独立。
6. **`REPLACE`**：不要因历史说明或安装器调用就声称普遍安全。当前核心找不到 `mark_replace`
   的定义；把它视为需锁定版本、后端和 ROM 的实验性行为。
7. **第三方样本**：示例的 source、notify、镜像、storage、hot-install、namespace 和 cleanup
   均是其自身设计，不是官方承诺。复用前先看许可证、当前 commit、源码和目标设备实测。

出现新 KernelSU 版本、Manager 更新、内核 backport、ROM SELinux 改动、挂载后端升级或问题单
与本文冲突时，优先检查源码的实际调用、环境传递、错误处理和内核事件，再更新本模块的兼容
矩阵；不要用旧 README 或单个关闭 issue 覆盖当前行为。

## 源码与文档索引

- 官方 Guide：`https://kernelsu.org/guide/metamodule.html`、
  `https://kernelsu.org/guide/module.html`。
- 本机官方文档镜像：`KernelSU/website/docs/guide/{metamodule,module}.md` 及
  `website/docs/zh_CN/guide/metamodule.md`。
- 元模块识别、单实例、install/uninstall hook：
  `KernelSU/userspace/ksud/src/metamodule.rs`。
- staging、安装器拼接、环境、更新切换：
  `KernelSU/userspace/ksud/src/module.rs`。
- 标准/late-load 时序：`KernelSU/userspace/ksud/src/{init_event,late_load}.rs`。
- 通知命令与内核事件：`KernelSU/userspace/ksud/src/{cli,ksucalls}.rs`、
  `KernelSU/kernel/runtime/boot_event.c`、`kernel/feature/kernel_umount.c`。
- 样本：`ksu-research/modules/{meta-overlayfs,meta-magic_mount-rs,meta-hybrid_mount}`。

相关通用安装、模块目录、生命周期、SELinux、WebUI 与原生 payload 约束见同技能目录的
`core-contract.md`、`native-and-zygisk.md`、`testing-and-release.md` 和安全专项参考。
