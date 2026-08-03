# 熊大模块架构

## 目录

1. 稳定身份与派生方式
2. 推荐目录
3. 启动链
4. 本地开关
5. 下载与 payload
6. 日志和状态
7. 升级与卸载

## 稳定身份与派生方式

- 默认模块 ID：`A.xiongda-onekey-start`。
- 同 ID 安装表示覆盖升级，KernelSU 先写 staging，通常重启后切换。
- `A` 只影响同类模块的字母排序；不存在模块私有的置顶字段。
- “独立版本”若未明确并存，表示独立源码/ZIP，不表示新 ID。
- 从用户点名的基础 ZIP 派生；不要从更高版本源码猜测旧版内容。

## 推荐目录

```text
module-root/
  module.prop
  action.sh
  customize.sh
  service.sh
  game_monitor.sh
  uninstall.sh
  autostart_enabled
  bin/
    control
    download-and-run
    driver-control          # 仅含驱动功能的变体
  driver/
    <服务器或用户原始名称>
  payload/                  # 运行时下载缓存，不预打包
  logs/                     # 运行时创建
  run/                      # PID、锁、FIFO 等运行状态
  webroot/
    index.html
    app.js
    style.css
```

脚本始终用自身路径推导 `MODDIR`，不硬编码活动模块绝对目录。`customize.sh` 可以读取活动旧版目录做受控迁移，但写入目标必须是安装器提供的 `MODPATH`。

## 启动链

```text
KernelSU late_start
  -> service.sh
  -> 单实例 game_monitor.sh
  -> 每轮用 shell 内建读取 autostart_enabled
  -> 检测到 和平精英 未运行 -> 运行 的转换
  -> 二次确认开关与游戏仍存活
  -> bin/download-and-run auto
  -> 下载/校验当前熊大
  -> 按魔数选择 ELF 或 Shell
  -> 后台启动并记录属于当前文件的 PID
```

手动 Action：

```text
KernelSU Action
  -> action.sh
  -> bin/download-and-run manual
```

手动驱动 WebUI：

```text
WebUI button
  -> window.ksu.spawn(fixed command)
  -> /system/bin/sh bin/driver-control run
  -> 校验内置驱动
  -> 原版驱动 --load
  -> 实时输出 + logs/driver-webui.log
```

这三条链必须保持可区分。`manual-driver` 中前两条链不引用驱动；`prelaunch-driver` 中 shared launcher 在 payload 前调用驱动 helper。

## 本地开关

- `autostart_enabled` 新装默认 `0`，升级仅保留有效的旧值 `0` 或 `1`。
- 缺失、空值、非法值、软链接均 fail closed 为关闭。
- WebUI 只调用 `bin/control status|enable|disable`。
- 写入使用同目录临时文件后 `mv -f`，避免半写内容。
- 关闭开关不杀监测服务；监测仍低耗读取一个字节，便于立即重新开启。
- 开启和关闭状态默认都约每 5 秒读取一次；不要用亚秒轮询，除非有真机功耗证据。
- 模块 `disable` 或 `remove` 标记使监测退出。

## 下载与 payload

- 每次触发才联网；等待游戏时不联网。
- 下载到模块私有 `.part`，校验后原子替换。
- 从完整、验证后的 `Content-Disposition` 恢复原始 UTF-8 文件名。
- 仅接受预期的普通文件名，不接受斜线、目录穿越、软链接或无效版本格式。
- `.sh` 后缀不决定解释器。读取魔数：ELF 直接执行；文本 Shell 才交给 `/system/bin/sh`。
- PID 文件只是线索；同时核对 `/proc/<pid>/exe` 或 cmdline 是否属于当前 payload。

## 日志和状态

- `logs/last-action.log`：仅最后一次手动 launcher 任务。
- `logs/auto-start.log`：监测、自启、下载和启动事件；限制大小并轮转。
- `logs/payload.log`：熊大进程自身输出，不回灌历史内容到当前 Action。
- `logs/driver-webui.log`：最后一次 WebUI 驱动任务，执行前截断。
- `run/game-monitor.pid`、`run/current.pid`：需做归属校验。
- 每类任务使用自己的原子目录锁；不要把一个模糊 PID 当成所有操作的锁。

## 升级与卸载

- `versionCode` 必须严格递增，即使显示版本从高版本派生回旧版功能线。
- 覆盖升级只迁移有效开关和已验证的 payload 缓存/元数据。
- 卸载只停止 PID 文件确认属于本模块的进程；不要 `killall`。
- 模块私有日志、锁和内置驱动随模块目录删除；已加载到当前内核且主动隐藏的驱动通常要重启才消失。
- “重启无残留”只覆盖已证明位于 `tmpfs/devtmpfs` 的运行状态；下载文件和显式提取目标不属于该承诺。
