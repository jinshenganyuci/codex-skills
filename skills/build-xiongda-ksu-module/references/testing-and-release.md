# 测试与发行

## 证据层级

始终分开报告：

1. 静态识别和哈希。
2. Shell/JS 语法。
3. 假驱动、假下载器、假 payload 模拟。
4. 源码与 ZIP 结构/字节校验。
5. KernelSU 真机安装和重启切换。
6. 游戏触发、联网下载、真实熊大启动。
7. 真实内核驱动加载和功能。

前四项不能替代后三项。

## 基础版差异控制

从正式 ZIP 解包后保存基线。发布前计算：

- modified：同路径字节变化。
- added：派生版新增。
- removed：基础版存在但派生版删除。

将三类集合与用户批准的相对路径做精确集合比较。不要用 `diff` 输出“看起来合理”代替白名单。

手动驱动变体通常只允许：元数据、安装权限、WebUI 三个文件、新 helper 和内置驱动发生变化。`action.sh`、`download-and-run`、`game_monitor.sh`、`service.sh` 若要求保持基础逻辑，应逐字节相同。

## 静态熊大/驱动检查

- 对输入和包内副本分别计算大小与 SHA-256，并 `cmp`。
- 对自解包 Shell 先定位 payload marker，只把 marker 前缀交给 Bash、Dash、BusyBox ash 的 `-n`。
- 可以静态解压内嵌 `.ko` 并读取 ELF header/hash；不要 `insmod`。
- 重新证明 `/dev` 状态目录确属 `tmpfs/devtmpfs` 的 fail-closed 逻辑，不能只看注释。

## 功能模拟矩阵

| 组件 | 必测分支 |
|---|---|
| 本地开关 | 默认 0、非法/缺失/软链接、0→1→0→1、同 PID 重置、disable/remove |
| 下载 | 新文件、304/未变化、失败保留旧缓存、错误文件名、超时、原子替换 |
| payload | Shell、ELF、stale PID、已运行、退出、卡密输入但日志无卡密 |
| 驱动 | 实际加载标记、重复跳过、非零、未知成功、并发、哈希篡改 |
| 游戏 | 启动转换、等待中关开关、驱动/下载期间退出、一次进程只触发一次 |
| WebUI | 无 bridge、开关四状态、流式 stdout/stderr、exit 后 error、重复点击 |

真实驱动一律用可控假脚本替代。假脚本只生成同样的结果标记和退出码，不包含 `.ko`。

## Shell 和 WebUI

对普通 shell 依次运行：

```sh
bash -n FILE
dash -n FILE
KSU_BUSYBOX ash -n FILE
```

对 WebUI 运行 `node --check webroot/app.js`，并执行模拟 bridge 测试。扫描 `webroot` 中的 `http://`、`https://`、远程 script/link、iframe 和通用终端输入。

## KernelSU 校验

使用 `kernelsu-module-development` 的当前脚本校验源目录、打包、再校验 ZIP。ZIP 根必须直接包含 `module.prop`，不能再包一层目录。

某些校验器历史正则把任何含数字 `7` 的 `chmod`（例如安全的 `0700`）误报为 `WORLD_WRITABLE`。处理方式：

1. 定位触发的精确字节和脚本前缀。
2. 用正确规则检查 other-write 位，仅 `...2`、`...3`、`...6`、`...7` 或 `o+w/a+w` 是全局可写。
3. 确认包中没有真正的全局可写权限。
4. 在发行记录中说明工具误报；不要无检查地全局放行该 warning，也不要为了过校验改写用户原版驱动。

## ZIP 最终验收

- `unzip -t` 通过。
- ZIP 文件集合与源码集合完全相同。
- 每个成员解压字节与源码相同。
- 包内驱动与当前用户输入逐字节相同。
- `module.prop` ID 稳定、`versionCode` 高于已安装正式版。
- `autostart_enabled` 符合本次默认值。
- 不含 `disable`、`remove`、测试文件、缓存、triage 报告、旧 payload、秘密或 source map。
- 从同一源码构建第二个 ZIP，两个 ZIP 逐字节相同。
- 记录最终 ZIP 大小和 SHA-256。

运行本 Skill 的 `verify_release.py` 做专项结构验证；它不能替代 KernelSU 通用校验器和功能测试。

## 真机验收

安装日志成功后重启，再核对模块卡版本和 lifecycle 日志。分别测试：

- 覆盖安装、冷启动、禁用、重新启用、卸载。
- WebUI 开关无需再次重启即可被常驻监测读取。
- 手动 Action 下载/启动。
- 游戏由未运行变为运行时触发一次。
- 手动驱动按钮实时日志与设备内日志一致。
- 当前内核/KMI、Root、SELinux、dmesg 权限和驱动真实结果。

只有完成对应设备操作后才写“真机成功”。
