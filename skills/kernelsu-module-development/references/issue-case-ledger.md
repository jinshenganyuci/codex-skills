# 已关闭 Issue 学习台账（1,102 条）

本 skill 随附 `references/issue-ledgers/` 的六份逐条台账，覆盖 `tiann/KernelSU` 已关闭
issues 的 JSONL 第 1–1,102 条。每一条均按“问了什么｜怎么解决或为何关闭｜可复用模块开发教训”
记录；无提交、维护者结论或报告者复测证据的 `COMPLETED` 均明确标为“未证实关闭”。因此不能把
GitHub 的 closed 状态当成功能已修复或兼容性已保证。

## 需要查哪个文件

| 文件 | JSONL 范围 | 常用主题 |
|---|---:|---|
| `issue-ledgers/001-184.md` | 1–184 | 早期模块布局、OverlayFS、权限、root/namespace、旧内核 |
| `issue-ledgers/185-368.md` | 185–368 | 安装镜像、更新 staging、vendor、SELinux、构建/版本 |
| `issue-ledgers/369-551.md` | 369–551 | 挂载/卸载、legacy/GKI、模块镜像、allowlist、ABI |
| `issue-ledgers/552-735.md` | 552–735 | sparse image、WebUI、Zygisk、分区/刷写、Manager/OTA |
| `issue-ledgers/736-918.md` | 736–918 | LKM、KMI、模块动作、升级、OEM 限制、late 兼容性 |
| `issue-ledgers/919-1102.md` | 919–1,102 | 近期 LKM/late-load、分区选择、非标准设备、Zygisk、WebUI |

先用 `rg -n '#<issue-number>|关键词' references/issue-ledgers` 检索，再读命中项前后文；不要因为
某条 issue 的临时 workaround 而跳过核心契约与当前源码验证。台账是经验/证据索引，当前发布前
仍需用 `core-contract.md`、代码版本和真实设备验证。

## 会反复出现的强规则

1. 模块 ZIP 根直接放 `module.prop`；安装/更新先写 staging，重启才切换。不要手工改活动模块目录。
2. 只有 `system/` 挂载依赖 metamodule；脚本、`system.prop`、`sepolicy.rule` 不依赖它。不要把
   Magisk `overlay.d`、`.replace`、recovery 安装或 `MAGISK_VER*` 检测搬过来。
3. 普通启动任务首选 `service.sh`；`post-fs-data.sh` 和 `late-load.sh` 是阻塞阶段，前者不能 `setprop`。
   late-load 下 `initrc` 不可用。
4. 根权限不等于所有 app 都看见同一个 mount namespace。涉及 app/system service 时，检查
   `/proc/<pid>/mountinfo`，并考虑 KSU 的 auto-unmount/授权行为。
5. `system/` 的软链接分区（vendor/product/system_ext）、SELinux label、package scan、ABI 和
   OverlayFS 目录语义必须实测；“文件可见”不等于 app 可启动。
6. 内核/Manager/ksud/模块的版本兼容需要分开看。KMI 和导出符号优先于 Android 补丁日期或 ZIP 名字；
   OEM RKP/Knox/security guard 等内核边界不能由一个模块绕过。
7. 每个高风险模块须提供 disable/remove/恢复路径；若碰到 bootloop，先保全日志和模块列表，再按
   官方救援流程处理，不能盲删共享目录。
8. WebUI 是 root 执行面；只打包本地资源，固定子命令、严格验证输入，不开放任意 shell。

## 高价值案例索引

| Issue | 已验证/谨慎结论 | 何时查 |
|---|---|---|
| #322 | `system/` OverlayFS 的替换与 `mknod c 0 0` tombstone 规则 | 删除/覆盖系统文件 |
| #359 | `/system/product` 等软链接路径需按真实分区处理 | product/vendor/system_ext 不生效 |
| #365 | 复杂嵌套 mount 不能粗暴重挂 `/system` | 自定义挂载/ROM 差异 |
| #713 | `overlay.d`/Recovery 不能当 KSU 标准模块路径 | 从 Magisk 迁移 |
| #746 | `customize.sh` 需尊重 `modules_update` staging | 安装器/更新逻辑 |
| #817/#838 | 模块与 vendor overlay 的 SELinux context 可决定启动成败 | overlay APK/服务失败 |
| #852 | 单个 mount failed 日志不足以证明安装失败 | 诊断安装/挂载 |
| #957 | 路径边界/模块路径处理有已合并修复 | 路径与更新异常 |
| #1050 | legacy SELinux 规则需要按实际内核适配 | 老内核移植 |
| #1185 | allowlist 清理可能造成 bootloop | 授权/模块恢复 |
| #1213 | BusyBox/用户态兼容的合并修复 | shell 工具差异 |
| #1331 | overlay 参数长度有边界 | 大型 overlay/mount |
| #1382/#1521 | WebUI 明文 HTTP 与 mixed content 的边界；loopback 需明确处理 | 本地 HTTP API |
| #1386 | app 是否看到模块挂载取决于 namespace/umount | app 读系统覆盖 |
| #1403 | 伴生 app 不应直接操作 KSU 内部模块目录 | App 管理模块 |
| #1469 | LKM 模块开关异常须以 early boot dmesg 和匹配 Manager 验证 | LKM 模块系统异常 |
| #1524 | legacy 文件遍历要使用 `namelen`，不是假设 NUL 终止 | 旧内核适配 |
| #1806 | legacy/GKI 支持先做 KMI 前置检查 | 分发/安装约束 |
| #1852 | 安装临时目录权限影响模块安装 | 安装器权限错误 |
| #2037 | 不能承诺 Magisk 模块一键通用转换 | 迁移评估 |
| #2171 | action 后需刷新模块状态（PR #2201） | action/WebUI 行为 |
| #2225 | sparse image/可选挂载要考虑更新和回滚 | 镜像/挂载架构 |
| #2462 | 快速返回的 WebUI 白屏有明确 PR 修复 | WebUI 生命周期 |
| #2523 | `su --shell` 的参数处理有已合并修复 | Shell 兼容性 |
| #2637 | 内核 RCU 临界区不可睡眠（PR #2646） | 内核/原生扩展 |
| #2701 | legacy 指引与源码符号会漂移，查当前提交 | 非 GKI 集成 |
| #2789 | `/system` 外目标挂载应在 `post-mount.sh` 自行处理 | vendor/mnt 自定义挂载 |
| #2802 | 残留旧 ksud 会让升级后的授权/Manager 表现异常 | 升级诊断 |
| #2865 | 非标准分区布局需要显式选择修补目标（PR #2896） | 安装/刷机工具 |
| #2908 | Manager、内核与 Direct Install 的分区目标必须同代并明确核验 | 升级/直接安装 |
| #3209/#3551 | 非挂载模块可无 meta；OverlayFS `system/` 模块硬依赖 compatible meta | 模块架构选择 |
| #3244 | 自定义 Manager/ksud 分发需要稳定签名、hash 与 size 校验 | 伴生管理器/供应链 |
| #3520 | Bazel `--config=fast --config=stamp` 修复版本生成并获报告者确认 | 构建版本可复现性 |
| #3535 | resetprop API 迁移需要按当前 userspace 验证 | 属性模块升级 |

## 问题报告模板

让每个模块提交 issue 时包含：KSU/Manager/ksud/runtime mode、设备/ROM/内核/KMI、模块版本和
完整 ZIP hash、最小复现、是否移除其他模块、安装日志、`logcat`、相关 dmesg/AVC、目标进程
`mountinfo`、预期与实际结果、恢复步骤。这样才能判断是模块、metamodule、Zygisk loader、OEM
内核、ROM 或 Manager 的责任，而不是把时间相关性误当因果。
