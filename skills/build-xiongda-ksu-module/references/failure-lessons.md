# 开发失败与修正

## Action 空白、WebUI 报 Permission denied / exit 126

原因：只检查了 ZIP 中 helper 的 `0755`，却忽略 KernelSU 默认安装会把普通文件重新设为 `0644`；Action 使用 `exec "$MODDIR/bin/helper"`，WebUI 也把裸 helper 路径直接交给 `exec`/`spawn`，而 `customize.sh` 没有恢复权限。

修正：在 `customize.sh` 顶层给 `action.sh`、lifecycle 脚本和每个 `bin/` helper 明确 `set_perm ... 0755`；Action/WebUI 仍统一经 `/system/bin/sh` 调用 Shell helper。发行验证必须从安装后 `0644` 模型检查权限，并用缺权限、Action 裸执行、WebUI 裸路径三个负向 fixture 证明会失败。

不要把 ZIP mode、Shell 语法通过或页面成功调用 bridge 当作安装后可执行证据。截图若出现 `can't execute: Permission denied` 与 `exit 126`，先核对设备上实际 mode、`customize.sh` 安装输出和完整调用命令。

## WebUI 出现用户没要求的启动、停止或状态按钮

原因：把熊大完整控制台当成所有派生模块的默认模板，没有把用户对 Action/WebUI 的功能边界冻结成白名单。

修正：用户要求“Action 启动 payload、WebUI 只刷驱动”时选择 `minimal-action-manual-driver`，拒绝 `service.sh`、游戏监测、自启开关、`bin/control` 和 WebUI launcher 调用。复用熊大的入口分离与日志机制，不复用未要求的产品功能。

## Action 显示执行但熊大没启动

原因：把 `.sh` 后缀当作 Shell，实际文件是 ARM64 ELF，却使用 `/system/bin/sh FILE`。

修正：每个当前 payload 重新读魔数。ELF 直接执行；Shell 才交给解释器。把静态格式判断与真机启动结果分开报告。

## WebUI 开关写入了但自启没效果

原因：让 WebUI 临时创建长期监测进程；WebView/root shell 生命周期、进程组或关闭页面会使服务退出。

修正：只让 `service.sh` 在开机启动一个长期监测进程。WebUI 只原子写入本地 `0/1` 文件，监测服务持续读取配置。

## 声称存在 `persist.config`，设备却找不到

原因：把 KernelSU 配置 API、某个源码版本的内部实现和当前设备上的实体路径混为一谈。

修正：只描述已证明的调用链。此模块默认是 `app.js -> bin/control -> 模块根 autostart_enabled`；没有设备文件证据时，不虚构 `persist.config` 的具体路径。

## 开关需要重启才生效

原因：只在 `service.sh` 启动时读取一次开关，或关闭开关时直接杀掉监测服务且没有可靠热重建。

修正：监测进程保持存活，每轮用 shell 内建读取一字节配置。覆盖安装新模块本身仍需重启切换，但日常开关不需要。

## 关闭后再打开不触发同一个游戏进程

原因：旧 `last_pid` 仍被视为已触发，或切换时没有重置转换状态。

修正：控制 helper 写入 `trigger-reset`，监测进程清空 `last_pid/last_mode`，再按当前游戏状态重新建立边沿。

## PID 文件存在但服务或熊大没有运行

原因：PID 已过期并被其他进程复用，或只检查文件存在。

修正：读取数字 PID 后 `kill -0`，再核对 `/proc/<pid>/cmdline` 或 `/proc/<pid>/exe` 是否属于预期脚本/文件；不匹配则清理自己的 stale PID。

## Action 页面出现大量以前日志

原因：启动前读取或拼接了旧日志，或者多个任务共用追加文件。

修正：手动任务开始时截断 `last-action.log`；驱动 WebUI 每次截断 `driver-webui.log`；自启日志独立轮转；payload 日志不回灌 Action。

## 驱动日志无法判断到底刷了还是跳过

原因：把两个结果合并成“首次加载或已经存在”，或只看驱动退出码 0。

修正：保留原始输出并识别互斥结果标记，最后追加唯一明确结论。未知的退出 0 必须 fail closed，不能写成功。

## 简单 `driver | tee` 把失败报成成功

原因：ash 的 `$?` 是管道最后一个 `tee`，不是驱动进程。

修正：使用 FIFO，独立启动 `tee`，前台执行驱动并立即保存它的退出码，然后等待日志进程。

## 游戏中重复下载、重复启动或重复刷驱动

原因：按轮询周期触发而不是按游戏启动转换触发；缺少任务锁；没有确认当前 payload PID。

修正：仅在无 PID→有 PID 的边沿触发；使用原子目录锁；一次游戏进程只触发一次；下载/驱动后再次确认游戏和开关。

## “无残留”重启后仍有文件

原因：把路径名当成易失存储，实际位于持久分区；或把下载缓存/显式提取文件也纳入无残留承诺。

修正：读取 `/proc/mounts` 验证状态根是 `tmpfs/devtmpfs`，否则拒绝加载。明确无残留只覆盖运行状态、锁和临时 `.ko`。

## 从 v1.7.1 派生却混入 v1.8.x 自动驱动

原因：直接修改当前最新源码，而不是从用户指定基础 ZIP 建工作树。

修正：从精确基础包解压；列出批准 delta；要求 `action.sh`、launcher、monitor、service 等未授权文件逐字节相同。

## 校验器报告 `chmod 0700` 为全局可写

原因：历史正则只要权限数字中出现 `7` 就告警，未按最后一位的 other-write 位判断。

修正：定位触发位置，使用正确权限规则复核。保留原版驱动字节，记录工具误报，不把所有 `WORLD_WRITABLE` 告警无条件忽略。
