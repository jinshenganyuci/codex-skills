# WebUI、配置与安全

## 先定边界

`webroot/index.html` 是 KernelSU Manager 中 WebUI 的入口；Web 资源必须随模块
本地打包。它不是普通网页：当前 Manager 会把 `window.ksu` 注入页面，`exec`/`spawn`
最终请求 global mount namespace 的 root shell。把 WebUI 当作一个 root 权限的本地管理程序来设计、
审计和测试。

不要加载远程 JavaScript、远程 CSS、第三方 CDN 或未经固定校验的 WASM。也不要把用户输入、
URL 参数、配置内容或文件名直接拼进 shell 字符串。

源码锚点：`manager/app/src/main/java/me/weishu/kernelsu/ui/webui/WebViewHelper.kt` 将
`webroot` 以 `https://mui.kernelsu.org/` 的 asset loader 提供并注入名为 `ksu` 的接口；
`WebViewInterface.kt` 的 `exec` 和 `spawn` 均创建 root shell。接口的 `cwd`/`env` options
会被拼接为 shell 文本，故不能把不可信值放入它们。当前 WebView 关闭 `file://` access，但没有
页面导航/iframe 的 origin allowlist，也不在异步回调前重新校验 URL；不能把“初始资源来自 webroot”
误认为是 root bridge 的来源隔离。

## 最小布局与发布要求

```text
module-root/
  module.prop
  webroot/
    index.html
    app.js
    style.css
  service.sh                 # 可选；把长期工作放到这里
```

- 根目录一定要有 `module.prop`；`webroot/index.html` 缺失时 Manager 无法作为 WebUI 打开。
- 让安装器设置 `webroot` 的权限和 SELinux context；不要在 `customize.sh` 中自行 `chown`、
  `chmod` 或 `restorecon` 这个目录，除非已在真实设备验证。
- 使用相对 URL、CSP、无内联远程依赖和本地静态资源。页面在浏览器中调试时可能没有 `window.ksu`，
  应显示只读降级状态，不要报错崩溃。
- 禁止导航到不可信页面、嵌入不可信 iframe、动态插入外部脚本或把用户输入交给 HTML 解释。任何能
  在当前 WebView 执行的第三方 JavaScript 都应按“可请求 root shell”对待。
- 不把密钥、令牌、私有服务器地址、完整日志或 `/data` 的敏感内容写进页面、`localStorage` 或
  `module.prop`。Manager 卸载后 `localStorage` 也可能丢失；真正持久状态使用模块配置 API 或模块
  私有目录，并明确访问权限。

## 调用 bridge 的安全模式

把每个 root 操作实现为模块内固定的子命令，而不是由 UI 传任意 shell：

```sh
# service/action helper: "$MODDIR/bin/control"
case "$1" in
  status)  /system/bin/getprop ro.product.model ;;
  enable)  : "只接受固定的、已校验的开关" ;;
  *)       echo 'unsupported action' >&2; exit 64 ;;
esac
```

WebUI 只调用固定路径和固定枚举，例如 `ksu.exec('/data/.../bin/control status')`。若必须接受
字符串：先在 JavaScript 和 shell 两端白名单验证（布尔值、整数范围、固定枚举、已验证包名），
并用安全参数协议；当前 bridge 本身会组装一个 shell command，不能把 JSON 字符串当作天然安全的
argv。不要使用 `eval`、反引号、`$()`、`sh -c`、管道下载执行，或把 JSON 直接插到命令中。

`spawn(command, args, options, callback)` 适合展示长任务流式输出，但其 `args` 仍会被拼接到
shell 命令，不是安全的 execve 参数数组。它也没有原生 stdin、可靠的取消/kill、PID 或完整启动
失败回调；不要把 npm wrapper 伪造出来的 `ChildProcess` 当作普通 Node 子进程。只将自己打包的固定
二进制/脚本作为 command，并让参数来自严格白名单。不要提供通用“终端”“执行命令”输入框。

在做破坏性行为前：页面展示具体目标与副作用、要求确认、调用可幂等的固定操作、返回 exit code
及经脱敏的错误，并提供取消/恢复方案。UI 不能替代 shell 端的校验。

## 可用的当前 bridge 能力

当前源码暴露 `exec`（同步或 callback）、`spawn`（stdout/stderr/exit 事件）、`toast`、
`fullScreen`、`enableEdgeToEdge`、`moduleInfo`、`listPackages`、`getPackagesInfo` 和 `exit`。
root shell 会优先请求 KernelSU global namespace，失败时可退回其他 shell 路径；必须检查 exit code
和实际结果，不能因 `ksu.exec()` 被调用就声称设备已获 root。不同 Manager 版本的 npm `kernelsu`
包只是这个 bridge 的封装，接口和 schema 仍需在目标版本实测，不要只凭 TypeScript 类型声明断言
兼容性。

可把 `moduleInfo()` 用于显示版本、模块路径和启用状态，但除 `moduleDir` 外字段来自 daemon，不能
假定固定完整 schema，也不把它当授权边界。包列表与包信息也属于敏感设备信息，只为实现功能所需
的最小范围读取与展示。系统 file picker 需要用户选择，不能视为任意本地文件读取能力。

## 模块配置 API

所有模块生命周期脚本运行时会得到 `KSU_MODULE=<模块ID>`。以该身份调用：

```sh
value=$(ksud module config get feature_mode 2>/dev/null || true)
case "$value" in
  ''|safe|fast) ;; *) value=safe ;; esac
ksud module config set feature_mode "$value"
```

可用命令：`get`、`set`、`set --temp`、`list`、`delete`、`clear`，`set` 可经 stdin 写多行
内容。持久值在重启后保留；临时值在每个启动的 post-fs-data 阶段自动清除；卸载模块时两者都会
清理。读取时临时值优先。当前上限为每模块 32 项、key 最多 256 bytes、value 最多 1 MiB；key
匹配 `^[a-zA-Z][a-zA-Z0-9._-]+$` 且至少两个字符。

- 在写入前限制大小和 schema；在读取后始终重新验证，配置文件不是可信输入。
- 把用户偏好存持久配置；把本次启动的状态存 `--temp`；不把秘密放进 `override.description`。
- `override.description` 可动态覆盖 Manager 显示的 description，适合简短状态，不适合日志。
- `manage.su_compat` 和 `manage.kernel_umount` 是当前预定义的 managed feature 名；只有在模块确实
  负责该全局功能并能安全回滚时才设置，卸载/停管时删除该 key，避免与其他模块抢控制权。

## WebUI 验收清单

1. 断网打开 WebUI：页面和所有资源仍可用，且没有 network dependency。
2. 以 WebView 与普通浏览器分别打开：后者没有 bridge 时能安全降级。
3. 为每个 root action 测试合法、空、超长、含空格、引号、换行、`$()` 和 `;` 的输入；它们都
   不得改变命令边界。
4. 对每个开关测试连续点击、失败重试、Manager 被杀后重开、重启后配置是否符合设计。
5. 检查打包 ZIP：无 map/source、开发 token、`node_modules`、未用依赖或远程 script URL。
6. 在禁用模块、待更新、待移除状态下确认 UI 不会继续宣称操作已成功。
7. 验证 `webroot/index.html` 确实在 ZIP 根模块目录下；Manager 会检查 module 有 WebUI 且已启用、
   未待更新/移除，但当前加载路径不替代你自己的入口文件校验。

## 参考依据

- `website/docs/zh_CN/guide/module-webui.md`：布局、WebView 与官方 JS API 概览。
- `website/docs/zh_CN/guide/module-config.md`：配置生命周期、上限和 managed features。
- `userspace/ksud/src/module_config.rs`、`userspace/ksud/src/feature.rs`：配置存储与调用模块身份。
- `manager/.../ui/webui/WebViewHelper.kt`、`WebViewInterface.kt`：当前实际执行面、root bridge 和
  资源加载边界。
