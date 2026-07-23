# KernelSU Manager、Action 与 WebUI 源码学习笔记

> 取证版本：本机 `KernelSU` checkout `87a62b76c9d3dd31495f63508469601237b1ad09`
> （2026-07-23，`main`）。本笔记只记录当前源码/官方文档能证明的行为；Manager、ksud、
> metamodule、内核和 ROM 会独立演进，发布前仍须在目标版本实测。

## 1. Manager 实际如何识别模块

Manager 通过 root shell 运行 `libksud.so module list`，将 JSON 映射为自己的 `Module` 模型，
而不是直接扫描任意目录：

- Manager 的调用与 JSON 入口：`manager/app/src/main/java/me/weishu/kernelsu/ui/util/KsuCli.kt:126-132`。
- JSON 字段映射：`data/repository/ModuleRepositoryImpl.kt:21-46`。
- 当前卡片依赖的字段是 `id`、`name`、`author`、`version`、`versionCode`、`description`、
  `enabled`、`update`、`remove`、`updateJson`、`web`、`action`、`metamodule`、`actionIcon`、
  `webuiIcon`：同文件 `:29-45`。
- daemon 侧把 `webroot` 目录存在性映射为 `web`，把 `action.sh` 存在性映射为 `action`；同时从
  `disable`、`update`、`remove`、`skip_mount` 计算状态：`userspace/ksud/src/module.rs:913-929`。

因此 `webroot/` 没有 `index.html` 仍可能被列为有 WebUI（随后页面会失败）；发布 ZIP 必须把
`webroot/index.html` 放在模块根下的正确位置。`module.prop` 的稳定 ID、可选更新 URL 和快捷方式
图标字段见官方模块文档 `website/docs/zh_CN/guide/module.md:106-132`。

图标字段必须是模块内相对路径：daemon 拒绝绝对路径和含 `..` 的路径，只有实际存在的普通文件才
把它解析为可展示的路径，见 `userspace/ksud/src/module.rs:819-865`。不要把图标路径当成任意文件
读取能力。

## 2. 安装、启停、卸载、更新与 Action

### Manager 操作语义

- 安装时 Manager 将用户选择的 ZIP 复制到 app cache 的 `module.zip`，执行
  `ksud module install <cache-file>`，结束后删除 cache 文件：
  `manager/.../ui/util/KsuCli.kt:194-212`。这说明发布包应是 Manager 可安装的根布局 ZIP，
  不能依赖 Recovery installer。
- 启用/禁用调用 `module enable|disable <id>`，Manager 成功后刷新并提示“重启以应用”：
  `KsuCli.kt:146-154` 与 `ui/viewmodel/ModuleViewModel.kt:377-390`。
- 卸载调用 `module uninstall <id>`；daemon 只是创建 `remove` 标记，实际移除在后续启动阶段发生：
  `KsuCli.kt:164-168`、`userspace/ksud/src/module.rs:702-718`。不要在运行时手工删除活跃模块目录。
- 模块可通过 `module undo-uninstall <id>` 撤销未完成的卸载：`KsuCli.kt:157-161`。

### `action.sh` 不是通用命令行

Manager Action 页面只允许模块存在、含 `action.sh`、已启用且未处于 update/remove 的状态运行：
`ui/screen/executemoduleaction/ExecuteModuleActionUtils.kt:42-58`。随后它调用
`ksud module action <id>`，把 stdout/stderr 实时显示并可保存为日志：
`KsuCli.kt:215-238`、`ExecuteModuleActionUtils.kt:62-110`。

daemon 先验证 ID/UAPI，再同步执行固定路径
`/data/adb/modules/<id>/action.sh`：`userspace/ksud/src/module.rs:721-727`。普通模块脚本在
BusyBox ash standalone 环境运行，工作目录为脚本所在目录，并带 `KSU`、版本、UAPI、runtime、
以及有效模块的 `KSU_MODULE` 环境变量：`module.rs:62-95`、`:184-247`。

因此 Action 应是无参数、短小、幂等、带清晰 stdout/stderr 的受控维护动作；长驻服务应放
`service.sh`。不要把 Action 做成“用户输入任意 root 命令”的终端。

### 更新元数据的实际契约

Manager 只有在网络可用、模块启用、未标记 update/remove，且 `updateJson` 非空时请求更新元数据：
`ModuleRepositoryImpl.kt:50-62`。当前解析字段为：

```json
{
  "version": "1.2.0",
  "versionCode": 12,
  "zipUrl": "https://example.invalid/module-v1.2.0.zip",
  "changelog": "https://example.invalid/changelog.md"
}
```

只有 `versionCode` 严格大于已安装版本且 `zipUrl` 非空才显示可更新：
`ModuleRepositoryImpl.kt:74-85`。Manager 代码在这一层可见的是版本比较和 URL 请求；模块发布者
仍应使用 HTTPS、稳定 URL、递增 `versionCode`、外部 SHA-256 和可回滚的 release 说明，不能把
网络更新元数据当作可信签名机制。

## 3. WebUI 的加载与可用 API

官方最低布局是模块根的 `webroot/index.html`；安装器会处理该目录权限/SELinux context：
`website/docs/zh_CN/guide/module-webui.md:7-23`。

默认安装器会递归设置目录 `0755`、普通文件 `0644` 和 SELinux context；但若安装器使用
`SKIPUNZIP=1`，这段默认处理也会被跳过，开发者必须自己做过目标机验证才可接管：
`userspace/ksud/src/installer.sh:408-420`。不要无理由在 `customize.sh` 手改 `webroot` 的权限或
label。

真实 Manager 会再次检查模块存在、有 WebUI、已启用且不是 update/remove，随后以 root shell 读取
`/data/adb/modules/<id>/webroot`：`manager/.../ui/webui/WebViewHelper.kt:43-103`。资源以
`https://mui.kernelsu.org/` synthetic origin 提供，WebView 禁用 `file://` 访问但启用 JavaScript 和
DOM storage：`WebViewHelper.kt:82-103`；首次页面为
`https://mui.kernelsu.org/index.html`：`ui/webui/WebUIScreen.kt:97-116`。

Manager 向 WebView 注入原生对象 `window.ksu`：`WebViewHelper.kt:189-193`。同仓库的 npm 包
`kernelsu` 只是它的 JavaScript 封装，而不是额外的权限或隔离层：`js/index.js:6-32`、`:71-145`。

| 原生接口 / npm wrapper | 作用与边界 |
|---|---|
| `exec` | 执行 shell，支持同步 stdout 或 callback 的 `(errno, stdout, stderr)`；`cwd`、`env` 会被拼入 shell 文本。`WebViewInterface.kt:30-82` |
| `spawn` | 提供 stdout/stderr data 和 exit/error 事件；`args` 也会拼成 shell 文本，不是安全的 execve argv。没有可靠 stdin、PID、kill 或取消 API。`WebViewInterface.kt:84-156`、`js/index.js:51-106` |
| `toast`、`fullScreen`、`enableEdgeToEdge`、`exit` | 原生 Toast、全屏/系统栏、inset 布局、关闭当前 WebUI。`WebViewInterface.kt:158-183`、`:257-260` |
| `moduleInfo` | 返回当前模块的 daemon JSON，并加上 `moduleDir`；不要假定除自己需要字段外的完整 schema。`:185-205` |
| `listPackages`、`getPackagesInfo` | 可读取用户/系统包列表，以及版本、label、UID、system 标志；仅按最小需求使用和显示。`:207-255` |
| `ksu://icon/<package>` | Manager 可返回应用 PNG 图标。`WebViewHelper.kt:106-139`；npm 文档例子见 `js/README.md:137-179` |

WebUI 可向系统文件选择器请求用户选择的文件，但不能把它理解为任意本地文件 API：
`WebViewHelper.kt:174-185`、`WebUIScreen.kt:36-49`。若需要 edge-to-edge CSS，可在本地页面引用
`/internal/insets.css`，它会让 Manager 传入系统栏 inset；官方 wrapper 说明见
`js/README.md:104-116`。

`/internal/colors.css` 与 `ksu://icon/<package>` 也是当前实现存在的渐进增强能力，前者在某些主题
模式可能返回空 CSS，后者仅能提供已知 app 的 PNG 图标：
`manager/.../ui/webui/SuFilePathHandler.java:184-208`、`WebViewHelper.kt:106-139`。它们没有构成
模块 WebUI 文档的稳定必需 API，需 feature-detect，不可作为关键功能前提。Manager 自己
`src/main/assets/webview/*` 的 HTML/CSS/JS 用于 Markdown，而不是给模块复用的公共 assets。

## 4. WebUI 的 root 安全模型（发布硬约束）

`exec`、callback `exec` 与 `spawn` 都调用 global-mount root shell：
`WebViewInterface.kt:30-33`、`:67-80`、`:102-155`。底层优先使用 KSU daemon 的 `su -g`，失败时依次
回退 `su -mm`、`su`、最终普通 `sh`：`manager/.../ui/util/KsuCli.kt:51-56`、`:70-90`。
所以页面应把失败当作可处理结果，且绝不能把“请求 root”误称为所有设备一定 root 成功。

更重要的是，bridge 对命令、工作目录、环境变量、调用模块和用户手势没有二次白名单：
`WebViewInterface.kt:40-68`、`:84-102`。当前 WebViewClient 也没有 navigation/iframe origin
allowlist，异步回调投回当前 WebView 时不复核 URL：`WebViewHelper.kt:106-145`、
`WebViewInterface.kt:73-81`、`:104-150`。故能在此 WebView 中运行的任意 JavaScript（第三方 CDN、
远程跳转、未验证 iframe、XSS payload）都应视为 root 级代码。

发布规则：

1. WebUI 只打包审核过的本地 HTML/CSS/JS/WASM；不加载远程 JavaScript、CSS、CDN 或不可信页面。
2. 每个 root 操作映射到模块内固定 helper 的固定子命令；JS 和 shell 两侧都将输入限制为枚举、
   整数范围、已验证包名等，绝不拼接 `;`、`$()`、反引号、换行或 JSON 到命令。
3. 对写文件、挂载、清配置、重启等破坏性操作显示精确目标、确认和可恢复路径；shell 端仍要校验，
   UI 确认不是授权边界。
4. 禁用、待更新、待移除状态下不要把页面缓存当作成功证据；Manager 会拒绝重新打开，但现存页面
   应能安全处理失败。
5. 所有模块 WebUI 复用 `https://mui.kernelsu.org` origin 且启用 DOM storage；`localStorage` 不应
   被视为模块隔离或秘密存储，不能写令牌、命令或敏感配置。用模块 config 或受控私有目录保存必要状态。
6. 分别在 Manager、普通浏览器（无 `window.ksu`）、断网、WebView 返回、异常输入和重复点击下测试。

## 5. Deep link 与快捷方式边界

`WebUIActivity` 是非导出的，仅 Manager 能直接启动：
`manager/app/src/main/AndroidManifest.xml:66-73`。对外 `ksu://webui` / `ksu://action` 深链由
MainActivity 先验证随机本地 intent token，再检查 Manager 状态后才分派：
`ui/navigation3/IntentDispatcher.kt:100-145`、`:167-203`。模块快捷方式 URI 由 Manager 生成并
包含该 token：`ui/util/module/Shortcut.kt:28-45`。

模块作者不应硬编码、存储或试图自行构造该 token；从模块卡片打开 WebUI/Action 是稳定的用户流程。
Action/WebUI 图标应保持小且合理，Manager 会对快捷方式 bitmap 截取并限制到 512 px：
`Shortcut.kt:197-255`。

## 6. 默认自动 umount 对模块开发的影响

Manager 的默认非 root App Profile 使用 key `$` 与 UID 9999 存储 `umountModules`：
`manager/app/src/main/java/me/weishu/kernelsu/Natives.kt:99-117`。官方文档说明设置中“默认卸载模块”
默认开启；在 5.10+ 内核上 KSU 可对应用卸载模块，而旧内核该项可能仅是配置：
`website/docs/zh_CN/guide/app-profile.md:108-121`。

因此 `/system` overlay 已挂载不代表某个 target app 看得到它。涉及 app/system service 的模块必须实测
目标进程的 mount namespace、App Profile、内核版本、metamodule 和 SELinux；不要通过关闭全局
kernel umount 或规避检测来宣称兼容。真正需要管理 `kernel_umount` / `su_compat` 的模块可用受控
配置声明，但需明确所有权、冲突和卸载回滚（见 `userspace/ksud/src/feature.rs:250-285`）。

## 7. 本节可直接纳入 skill 的验收项

- `webroot/index.html` 存在，所有静态资源为本地相对路径，ZIP 中无 CDN、开发 token、未审计 WASM
  或 source map。
- `action.sh` 仅执行固定、可重复的维护操作，并能在无 root/无 UAPI、禁用、update/remove 状态下
  失败而不破坏数据。
- `updateJson` 在离线、HTTP 失败、无 changelog、版本号相同/回退时均正常降级；仅 HTTPS 发布。
- 以正常模块、`system/` overlay 模块和没有 metamodule 的对照分别测试，记录 Manager 卡片、脚本、
  mount、目标进程可见性和实际功能五个不同结果。
- WebUI root helper 经 shell 端白名单测试：空值、超长、空格、引号、换行、`;`、`$()`、反引号、
  目录穿越和无效包名都不得改变命令边界。
