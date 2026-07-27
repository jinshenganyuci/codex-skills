# 历史样本快照：2026-07-27

这是可选历史资料，不是 Skill 的固定前提，也不代表当前或未来版本。仅在识别相同哈希、回溯旧行为或寻找分析线索时读取。所有网址、格式、加壳、压缩、偏移、路径和行为都必须从本次输入重新证明。

本快照来自 2026-07-27 的只读静态分析。样本、解压代码区、内嵌 ELF 和 Shell 均未执行。远程控制文件会变化；每次分析新版本时应重新获取并注明时间。

## 样本身份

### APK 1.2

- 文件名：`熊大kernel_1.2.apk`
- 大小：`8,614,698` 字节
- SHA-256：`573af725ff2d1a6471abc2cc6f9a40bbab7c2ef07f205af9817db3c0efccc643`
- 真实类型：Android APK
- ZIP 成员：602 个
- DEX：`classes.dex`
- ARM64 库：
  - `lib/arm64-v8a/libandroidx.graphics.path.so`，10,096 字节
  - `lib/arm64-v8a/libmerminal.so`，9,736 字节
  - `lib/arm64-v8a/libsparkle_core.so`，4,698,976 字节

机器可比较的静态扫描报告见 `historical-apk-1.2-triage.json`。

### 熊大 1.4.2

- 文件名：`熊大_1.4.2.sh`
- 大小：`10,846,400` 字节
- SHA-256：`d43007966f2cd4dcedf9e016509be2b556545da7b8fd2e6e15a3ea5f20185ce0`
- 真实类型：Android ARM64 PIE ELF，不是 Shell 文本
- 解释器：`/system/bin/linker64`
- 保护：`Virbox Protector`
- 入口：`0x43870`

机器可比较的外层扫描报告见 `historical-kernel-1.4.2-triage.json`。

## APK 内置控制地址

APK 的 `classes.dex` 固定包含：

```text
https://jianhancloud.cn/hcf/熊大配置.json
```

这是稳定引导地址。内核、驱动、字体和脚本的实际下载地址由远程文件控制，不应说成全部硬编码在 APK 中。

2026-07-27 11:10 +08:00 的远程响应状态为 200。服务端内容不是严格 JSON，因为它写成了：

```text
"内核版本": 1.4.2
```

分析脚本只把这个非法多段数字修复为字符串 `"1.4.2"`，并在报告的 `json_repairs` 中记录。当前关键字段为：

| 字段 | 当前值 |
|---|---|
| 内核版本 | `1.4.2` |
| 内核下载链接 | `http://pan.n8w.cn/down/XD` |
| 驱动版本 | `1.6` |
| 驱动下载链接 | `http://wpan.cdndns.site/down/xddrive` |
| 物资表配置 | `https://jianhancloud.cn/hcf/熊大物资表.json` |
| 字体下载链接 | `http://wpan.cdndns.site/down/zt` |
| 脚本下载链接 | `http://wpan.cdndns.site/down/cleanup` |

同一时间的只读 HEAD 结果：

| URL 后缀 | 文件名 | Content-Length |
|---|---|---:|
| `/down/XD` | `熊大_1.4.2.sh` | 10,846,400 |
| `/down/xddrive` | `熊大驱动.zip` | 43,329,713 |
| `/down/zt` | `字体.zip` | 6,646,356 |
| `/down/cleanup` | `清理.zip` | 8,075 |

链接和响应头是时间点事实。新版本分析必须重新探测，不能照抄。

## APK 下载与解压行为基线

APK 包名数据根目录通常解析为 `/data/user/0/sparkle.kernel.xiongda/`。内核资源同步涉及：

```text
files/熊大.sh.part
files/熊大.sh
files/kernel-launch/
files/kernel-launch/熊大.sh
files/kernel_launch_flow_cache.json
shared_prefs/driver_resource_state.xml
```

`熊大.sh.part` 是下载临时文件。1.2 APK 的资源流程期待兼容的加密 ZIP，而当前 `/down/XD` 返回 ELF；此组合会写入临时文件后报格式不兼容，并清理临时文件和 `kernel-launch`。分析新 APK 时应重新追踪下载格式检查，不能假定该不兼容仍存在。

APK 的 DEX 还包含 `/data/熊大/...`、头像、字体、登录缓存和资源包路径。只有在 Java/Kotlin、smali 或 JNI 写入调用得到确认后，才能把它们归为 APK 自身创建行为。

## 1.4.2 解壳基线

外层 ELF 中验证成功的 Zstandard 帧：

| 项目 | 值 |
|---|---|
| 起点 | `0x5d8f0` |
| 末尾 | `0x9d43e9` |
| 压缩大小 | 9,923,321 字节 |
| 解压大小 | 21,582,304 字节 |
| 解压 SHA-256 | `675793ec4a45335e2e4fe478f3919d261a7ce63604ab5e9ce771235cb77f3dd6` |

1.4.2 的已验证代码映像重建公式为：

```python
rx = outer[0x9db000:0x9db240] + b"\0" * 0x30 + zstd_payload
```

重建映像大小为 21,582,928 字节，SHA-256 为：

```text
e35f1f9bb389abfb005dc960d5e0d1fcf93defdcf8be3a57d9e113834dac832d
```

这些偏移和公式只适用于这个哈希。新版本必须从程序头、装载代码和压缩帧重新推导。

## 确认持久创建或重写

### 目录

```text
/data/熊大
/data/熊大/配置
```

代码分别调用 `mkdir(path, 0755)`。保存卡密时还会尝试 `mkdir("/data/熊大", 0700)`；若目录已存在，不会把权限自动改为 0700。

### 四个页面 JSON

```text
/data/熊大/配置/绘制.json
/data/熊大/配置/物资.json
/data/熊大/配置/自瞄.json
/data/熊大/配置/追踪.json
```

保存循环使用 `fopen(..., "wb")`，所以不存在时创建、存在时截断重写。读取使用 `rb`。删除配置功能会对四个路径调用 `unlink`。

### 自定义物资原子写入

```text
/data/熊大/自定义物资.txt.tmp
/data/熊大/自定义物资.txt
```

程序先写 `.tmp`，再 `rename(tmp, final)`。成功后 `.tmp` 消失；失败或异常中断时可能残留。最终路径属于持久原子替换目标。

### 功能标记

```text
/data/熊大/iswht
```

开启功能时使用 `wb` 创建空文件，关闭时 `unlink`。启动检查只读打开。

### 卡密存储

```text
/data/熊大/卡密储存
```

C++ 输出流模式为 `binary|out|trunc`，会创建或截断。该文件可能含真实卡密；报告只列路径，不得输出内容。

## 条件输出和临时文件

### 临时注入库

```text
/data/local/tmp/libparadise_gyro.so
```

程序使用 `wb` 写出内嵌 ELF、`chmod 0777`，用于注入相关流程，随后走删除逻辑。正常路径会清理；失败时可能残留。

内嵌 payload 信息：

- 外层样本偏移：`0xa0ec48`
- 大小：`0x3ba40`，即 244,288 字节
- SHA-256：`b18750cb0854d73c2f0cc594f3d63d32ce24d6065812b51e49126d770bce1548`
- SONAME：`libgyro.so`

该 SO 自身不创建目录或普通文件。它只读访问 `/proc/self/maps`、解析 `/system/lib64/libsensor.so`，并建立名为 `ParadiseGyroMem` 的匿名内存映射；匿名映射名不是文件。

### 录像

录像功能开启时寻找首个不存在的编号：

```text
/sdcard/1.mp4
...
/sdcard/9999.mp4
```

最大编号已核对为 9999。若 1 至 9999 全部存在，回退到：

```text
/sdcard/recording.mp4
```

### ImGui

相对于程序启动时的当前工作目录：

```text
$PWD/imgui.ini
$PWD/imgui_log.txt
```

`imgui.ini` 在布局保存开启时可能产生；`imgui_log.txt` 只在启用 ImGui 文件日志时产生。不要把 `$PWD` 展开成固定 Android 目录，除非启动方已被分析。

## 配置迁移行为

程序枚举 `/data/熊大/配置`，保留四个页面 JSON。对其他既有文件：

- 若 `/data/熊大/<同名>` 不存在，使用 `rename` 移到上一级；
- 若上一级已存在同名文件，删除配置子目录内的重复文件。

这是迁移已有内容，不是凭空生成新文件。

## 只读取，未证明由 1.4.2 创建

```text
/data/熊大/自定义盒内物资.txt
/data/熊大/类名锁.txt
/data/熊大/类名追.txt
/data/熊大/仇人.txt
/data/熊大/分辨率x
/data/熊大/分辨率y
/data/熊大/icon.png
/data/熊大/字体.ttf
/data/熊大/手持图片/%d.png
```

另有 QQ、微信头像缓存读取。`/storage/emulated/0/network/mac_random.txt` 只发现于嵌入组件字符串，未找到直接代码引用，保持为未解决候选。

## 内嵌调度 Shell

主程序通过 `popen("/system/bin/sh", "w")` 把两段文本写入 Shell 标准输入。该功能由用户点击触发，不是每次启动无条件执行。

| 重建映像偏移 | 长度 | SHA-256 |
|---:|---:|---|
| `0x250460` | 96 | `42738c67d1de9e294d46442d8b9aa3f7213b3e01de7754da9c6451bf22c200c0` |
| `0x2504c1` | 6,517 | `b684712177978e91efc840b9e30a5dd638848a1b8ff61051e3fc5e6b166cb6b4` |

### 条件重建文件

```text
/data/system/mcd/df
```

只有 `/data/system/mcd` 和原 `df` 都已存在时，脚本才清除 immutable、删除、重建空内容并执行 `chattr +i`。它不会创建父目录，也不会在原文件不存在时创建该路径。

### `/cache` 镜像文件

`hide_value()` 仅在对应 `/sys` 或 `/proc` 源节点存在时创建镜像：

```text
/cache/sys/class/thermal/thermal_message/market_download_limit
/cache/sys/class/thermal/thermal_message/modem_limit
/cache/sys/kernel/fpsgo/common/fpsgo_enable
/cache/sys/kernel/fpsgo/fbt/limit_cfreq
/cache/sys/kernel/fpsgo/fbt/limit_rfreq
/cache/sys/kernel/fpsgo/fbt/limit_cfreq_m
/cache/sys/kernel/fpsgo/fbt/limit_rfreq_m
/cache/sys/kernel/fpsgo/fbt/enable_ceiling
/cache/proc/oplus_scheduler/sched_assist/sched_impt_task
/cache/proc/oplus_scheduler/sched_assist/sched_assist_enabled
/cache/proc/game_opt/cpu_max_freq
/cache/proc/game_opt/cpu_min_freq
/cache/proc/task_info/task_sched_info/task_sched_info_enable
```

它先以 `mkdir -p` 补齐父目录，把末级路径短暂建成目录，再删除末级目录并用 `cp -f` 创建同名普通文件，最后 bind mount 回原节点。可能创建的父目录包括：

```text
/cache
/cache/sys
/cache/sys/class
/cache/sys/class/thermal
/cache/sys/class/thermal/thermal_message
/cache/sys/kernel
/cache/sys/kernel/fpsgo
/cache/sys/kernel/fpsgo/common
/cache/sys/kernel/fpsgo/fbt
/cache/proc
/cache/proc/oplus_scheduler
/cache/proc/oplus_scheduler/sched_assist
/cache/proc/game_opt
/cache/proc/task_info
/cache/proc/task_info/task_sched_info
```

### cgroupfs

脚本创建：

```text
/dev/cpuset/foreground/4-5
```

cgroupfs 随目录生成并被脚本使用的易失虚拟节点包括：

```text
/dev/cpuset/foreground/4-5/cpus
/dev/cpuset/foreground/4-5/mems
/dev/cpuset/foreground/4-5/tasks
/dev/cpuset/foreground/4-5/cgroup.procs
```

这些不是普通持久磁盘文件。脚本定义的 `mk_cpuctl()` 没有被调用，因此 `/dev/cpuctl/$1` 不能列为实际创建。

脚本还删除 `/dev/cpuset/background/untrustedapp` 和 `/dev/cpuset/foreground/boost`，并修改大量已有 `/sys`、`/proc` 和 `/dev/cpuset` 节点。

## 高危分支

与 `libPhysxShared.so` 处理相关的异常分支中存在：

```text
rm -rf /dev/*
rm -rf /*
reboot
```

静态分析不能证明正常启动必然走到该分支，也不能忽略它。每个新版本都要重新确认字符串引用、调用点、条件和可达性，并在报告中单列高危警告。

## 新版本比较规则

- 先用保存的 APK 或 ELF triage JSON 做集合差异比较。
- 不把 1.4.2 的偏移、重建公式或文件行为直接套到新哈希。
- 重新确认远程配置，因为链接和版本由服务器随时修改。
- 对新增路径、Shell、内嵌 ELF 和危险命令重新做调用点证明。
- 若新版本去除某字符串，不代表行为一定消失；还要检查编码、加密、动态拼接和表驱动引用。
