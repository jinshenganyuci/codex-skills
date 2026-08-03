# KernelSU WebUI 与驱动实时日志

## Root 调用面

KernelSU Manager 将模块 WebUI 放在 `https://mui.kernelsu.org/` 合成来源，并注入 `window.ksu`。`exec` 和 `spawn` 最终都构造 root shell 文本，因此：

- 只使用本地 HTML/CSS/JS。
- 只调用模块内固定路径和固定 `run|log|status|enable|disable`。
- 不把输入框、URL、文件名、配置值或网络响应拼进 command、args、cwd 或 env。
- shell helper 内再次使用 `case` 白名单；拒绝额外参数。

## 当前原生 `spawn` 协议

调用形状：

```js
window.ksu.spawn(command, JSON.stringify(args), JSON.stringify(options), callbackExpression);
```

Manager 随后执行：

```text
callback.stdout.emit('data', line)
callback.stderr.emit('data', line)
callback.emit('exit', exitCode)
callback.emit('error', error)       # 非零退出时通常紧跟 exit
```

不要在收到非零 `exit` 后立刻删除 callback，否则随后 `error` 会丢失。延迟清理或在两类事件均可达的状态机中清理。运行期间禁用按钮；不同任务使用唯一 callback 名，避免开关读取与驱动任务互相覆盖。

页面应在普通浏览器没有 `window.ksu` 时显示只读错误，而不是崩溃。

## `driver-control` 契约

仅提供：

```text
driver-control run
driver-control log
```

`run` 推荐顺序：

1. 从 helper 自身路径推导 `MODDIR`。
2. 验证日志/运行目录不是软链接或特殊文件。
3. 取得原子目录锁；活跃锁返回固定非零码（例如 75）。
4. 截断本次日志。
5. 验证驱动是普通非软链接文件，大小和当前输入 SHA-256 完全匹配。
6. 创建 PID 唯一 FIFO 与本次结果文件。
7. 后台 `tee -a LOG OUTPUT < FIFO`，驱动 stdout/stderr 合流写入 FIFO。
8. 保存驱动真实退出码，再等待 `tee`。
9. 从原版驱动的稳定结果标记分类本次实际加载、重复跳过或不明确。
10. trap 清理 FIFO、临时结果和自己持有的锁。

不要用简单管道：

```sh
driver 2>&1 | tee log
```

普通 ash 中 `$?` 往往只得到 `tee` 的退出码，可能把驱动失败误报为成功。

## 结果文案

日志最后必须只有一种明确结论：

- `本次已执行 insmod，驱动加载成功。`
- `本次没有执行 insmod：本次开机已加载，已跳过重复加载。`
- `驱动脚本执行失败，退出码=N。`
- `驱动退出码为 0，但无法确认实际加载或跳过。`

不要使用“首次加载或已经存在”“处理完成”等合并文案。

## 日志显示

- 实时面板逐行追加 stdout 和 stderr 并自动滚动。
- 最终状态显示退出码；不能仅因 `spawn` 被调用就显示成功。
- “查看上次日志”调用固定 `log` 子命令。
- “清空屏幕”只修改 DOM，避免误删诊断证据。
- 每次 `run` 覆盖旧驱动日志，让当前任务不混入历史内容。

## 假 bridge 测试

用 Node 的最小 DOM/`window.ksu` stub 验证：

1. `moduleInfo()` 返回当前 ID 和 moduleDir。
2. `exec` 回传四种开关状态。
3. `spawn` 依次发 stdout、stderr、exit、error。
4. 命令严格等于固定 helper `run`，args/options 为固定 JSON。
5. 成功、非零、重复任务三种状态均恢复按钮。
6. 页面没有远程资源，也没有任意命令输入。
