---
name: build-xiongda-ksu-module
description: Build, migrate, audit, test, and package the `A.xiongda-onekey-start` KernelSU module and derived 熊大 variants. Use when Codex must create or update 熊大一键启动 module ZIPs, preserve a chosen base release, implement manual or game auto-start and a local 0/1 switch, download and launch the current 熊大 payload, embed a byte-exact driver in manual-WebUI or prelaunch mode, stream root-operation logs through KernelSU WebUI, diagnose a prior module that did not execute, or deliver a reproducible validated release.
---

# 构建熊大 KernelSU 模块

把用户指定的基础版本派生为可安装、可回归、日志明确的熊大 KernelSU 模块。优先保留已验证行为，只修改本次要求的路径，并分别证明源码、ZIP、模拟执行和真机结果。

## 组合已有能力

开始前按任务加载并遵守：

1. `kernelsu-module-development`：读取其核心契约、测试发布资料；涉及 WebUI 时再读 WebUI 安全和 Manager 回调资料。
2. `xiongdaneiheskill`：对每个当前熊大内核、驱动、APK 或伪装 `.sh` 重新做静态识别。

本 Skill 负责熊大模块的产品架构和派生流程，不复制上述两个 Skill 的通用知识。

## 坚守边界

- 不在开发机执行用户上传的 APK、ELF、驱动、自解包脚本、`insmod` 或真实熊大 payload。
- 不因扩展名、旧哈希、旧 URL、旧版本号或历史分析推断当前文件类型。
- 不改写用户要求原样保留的驱动；复制前后、ZIP 内外均做逐字节比较和 SHA-256 校验。
- 不直接修改当前活动模块或用户未指定的正式源码；从明确的基础 ZIP/源码建立独立工作树。
- 不把静态检查、Shell 语法、假驱动测试说成真机加载成功。
- 不把 WebUI 做成任意 root 终端；只调用模块内固定 helper 和固定子命令。
- 不加载远程 JS/CSS/CDN；不在日志中输出卡密、令牌或完整敏感输入。

## 先冻结需求

在写文件前记录：

- 基础版本的精确 ZIP/源码路径和 SHA-256。
- 目标模块 ID、显示版本、递增的 `versionCode` 和输出包名。
- 手动启动、游戏自启、本地开关、在线下载、卡密输入分别是否保留。
- 驱动模式、日志保留方式、覆盖安装还是并存安装。
- 用户给出的当前 payload、驱动、下载地址和预期设备 ABI/内核。

将“独立版本”默认解释为独立源码和独立 ZIP、仍使用原 ID 覆盖升级；只有用户明确要求两套同时安装时才更换 ID，并重新审计两个监测服务、日志、锁和 payload 目录冲突。

### 选择驱动模式

| 模式 | 调用位置 | 必须保证 |
|---|---|---|
| `no-driver` | 不调用驱动 | 熊大原启动链完全不含驱动逻辑 |
| `manual-driver` | 仅 WebUI 按钮调用 `bin/driver-control run` | 手动/游戏自启不会加载驱动；页面实时显示完整日志 |
| `prelaunch-driver` | `download-and-run` 在 payload 前调用固定 helper | 驱动失败阻止 payload；游戏存活和开关在驱动后再次确认 |

不要把一种模式的逻辑悄悄带进另一种模式。

## 建立派生工作树

优先从用户点名的正式 ZIP 解包，不从当前较新源码“倒改”成旧版。使用本 Skill 的安全解包器：

```sh
python3 "$SKILL_DIR/scripts/extract_base.py" BASE.zip WORK/A.xiongda-onekey-start
```

它拒绝外层目录、路径穿越、符号链接、重复成员、错误模块 ID 和已存在的输出目录。解包后：

1. 保存基础文件清单和哈希。
2. 列出允许修改、新增、删除的相对路径。
3. 对未列入范围的运行文件做 `cmp`，不能只看文件名。
4. 保持稳定 ID `A.xiongda-onekey-start`；其 `A` 只提供同组字母排序靠前，不是置顶字段。

详见 [references/architecture.md](references/architecture.md)。

## 处理当前熊大文件

对每个上传或下载的文件分别运行 `xiongdaneiheskill` 的普通和 JSON triage。至少记录真实类型、大小、SHA-256、架构、内嵌容器和文件路径候选。

- `.sh` 若为 ELF：直接执行文件；不要强制交给 `/system/bin/sh`。
- `.sh` 若为 Shell/自解包脚本：仅静态读取脚本前缀和内嵌数据；不要真实运行。
- 在线下载：每次读取当前地址，保留服务器验证后的原始版本文件名，先写 `.part` 再原子替换。
- 卡密自动输入：复用已验证的 PTY/输入链；不把卡密写入日志、Skill 或公开测试数据。
- 内置驱动：按当前输入动态写入 helper 的预期大小和 SHA-256，禁止复用历史常量。

## 保留低耗自启架构

除非用户明确要求改架构，保持：

- 模块根 `autostart_enabled`，内容仅允许 `0` 或 `1`；新装默认 `0`。
- `bin/control status|enable|disable` 使用临时文件加 `mv` 原子写入。
- `game_monitor.sh` 用 `IFS= read -r` 内建读取；缺失、非法、空文件或软链接均按关闭。
- `service.sh` 在开机启动一个监测进程；关闭开关只阻止触发，不依赖 WebUI 创建服务。
- 未检测到游戏启动转换时不联网、不下载、不启动熊大。
- 用 PID、命令行/可执行文件归属和原子锁处理旧 PID、重复点击和并发任务。

不要在每轮检测中调用 `ksud module config`、`cat` 或网络请求。保留 `bin/control` 的四种稳定状态：`enabled-running`、`enabled-stopped`、`disabled-ready`、`disabled-stopped`。

## 实现 WebUI 驱动日志

手动驱动模式使用固定 `bin/driver-control run|log`：

1. 拒绝软链接、缺失或哈希不符的驱动。
2. 用原子目录锁阻止并发。
3. 通过 FIFO 和 `tee` 同时流向 WebUI、完整日志和结果识别文件。
4. 保留驱动真实退出码。
5. 明确输出“本次执行 insmod”“本次已加载并跳过 insmod”“执行失败”“退出 0 但结果无法识别”。
6. 每次 `run` 覆盖旧的 `logs/driver-webui.log`，避免当前页面混入以前日志；`log` 只读取最后一次完整日志。

WebUI 使用 KernelSU `spawn` 的真实事件协议，分别处理 `stdout.data`、`stderr.data`、`exit` 和非零退出后的 `error`。运行时禁用重复点击；“清空屏幕”只清 DOM，不删除模块日志。

完整协议和 shell 模式见 [references/webui-and-driver.md](references/webui-and-driver.md)。

## 保证下载与启动结果可解释

让手动 Action 和游戏自启共享同一个固定 launcher，但使用不同来源标签和日志：

- 手动执行先清空本次 Action 日志并向 Manager 输出当前任务。
- 自启只写轮转后的 `auto-start.log`，不把旧 Action 日志重新打印。
- 下载保留验证后的服务器原始文件名；不要发明 `.bin`、`最新` 或无版本别名。
- 先检查当前 payload PID 是否确属当前文件，再决定是否重复启动。
- 根据魔数选择 ELF 直接执行或 Shell 解释器。
- 驱动前置模式中，驱动失败必须阻止 payload；手动驱动模式不得触碰此链。

## 测试且不碰真实驱动

至少完成：

1. 基础版未授权文件逐字节不变。
2. Bash、Dash、KernelSU BusyBox ash 解析所有普通 shell；自解包驱动只解析 marker 之前的文本前缀。
3. Node 解析 WebUI JS；用假 `window.ksu` 验证控制开关和 `spawn` 四类事件。
4. 用假驱动覆盖实际加载、重复跳过、退出失败、退出 0 但结果不明、并发锁、文件篡改。
5. 运行本地 0/1 开关循环：默认关闭、非法值、关闭后重开、同 PID 重触发、disable/remove 退出。
6. 用假下载器和假 payload 验证文件名、ELF/Shell 分流、卡密不泄漏、游戏退出取消。
7. 校验源目录和 ZIP、`unzip -t`、根布局、源码/ZIP 字节一致、驱动字节一致、可复现构建和最终 SHA-256。

运行专项验证器：

```sh
python3 "$SKILL_DIR/scripts/verify_release.py" \
  --source WORK/A.xiongda-onekey-start \
  --zip DIST/module.zip \
  --mode manual-driver \
  --driver CURRENT_DRIVER.sh \
  --base-zip BASE.zip \
  --expected-base-delta module.prop \
  --expected-base-delta customize.sh \
  --expected-base-delta bin/driver-control \
  --expected-base-delta driver/CURRENT_DRIVER.sh \
  --expected-base-delta webroot/index.html \
  --expected-base-delta webroot/app.js \
  --expected-base-delta webroot/style.css
```

按实际批准范围调整 delta，不能把未知差异全部放行。验证细节和校验器误报处理见 [references/testing-and-release.md](references/testing-and-release.md)。

## 诊断时先复盘已知失败

遇到“没执行”“开关失效”“必须重启”“日志混乱”“重复刷入”时，先读 [references/failure-lessons.md](references/failure-lessons.md)，再从当前源码、日志和设备状态重新证明原因，不直接套历史结论。

## 交付

先给可安装 ZIP 和 SHA-256，再说明：

- 基础版本、版本/`versionCode`、模块 ID 和覆盖/并存关系。
- 驱动模式以及哪些启动链会或不会加载驱动。
- WebUI 实时日志和设备内最后日志路径。
- 内置驱动与输入的大小、SHA-256、逐字节一致结果。
- 静态、模拟、ZIP、可复现构建分别通过什么。
- 是否完成真机安装、重启、游戏触发和真实驱动加载；未完成时明确写“未实机证明”。

不要用“应该成功”代替证据，也不要把用户先前确认过的旧版本行为冒充新 ZIP 的真机结果。
