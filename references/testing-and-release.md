# 测试、更新与发布

## 可复现构建

从一个干净工作目录建立模块，不要把 ZIP 输出到源目录。顺序为：实现 → 静态校验 → 根目录 ZIP
打包 → ZIP 再校验 → 真机安装。skill 自带命令：

```sh
python3 scripts/scaffold_module.py example-module --output ./work --webui --action
python3 scripts/validate_module.py ./work/example-module --strict
python3 scripts/pack_module.py ./work/example-module ./dist/example-module-v1.zip
python3 scripts/validate_module.py ./dist/example-module-v1.zip --strict
sha256sum ./dist/example-module-v1.zip
```

常规模块包含 `system/` 时，`METAMODULE_REQUIRED` 是环境前提提示。只有已明确安装/测试兼容
metamodule 时，才使用 `--strict --allow-warning METAMODULE_REQUIRED`；其余 warning 不得放行。

`pack_module.py` 固定 ZIP 时间、排除 `.git`/缓存、拒绝 symlink，并把脚本保留为 executable；它不是
真机测试的替代。每次 release 固定版本工具链、输入依赖、native ABI 与 source commit，保存 ZIP 的
SHA-256 和一份 human-readable release note。

## 安装、更新和回滚事实

当前 `ksud` 先从 ZIP 根读取 `module.prop`，按 `id` 创建 `modules_update/<id>` staging 目录，
解压、运行安装器后写入活动目录的 `module.prop` 与 update 标记；下一次启动的
`handle_updated_modules()` 才处理 staging 切换。不要在 `customize.sh` 或伴生 app 直接修改
`/data/adb/modules/<id>` 的活动内容，也不要把“Manager 显示安装成功”当作已生效。

验证路径：安装日志 → 重启 → 模块卡状态/版本 → 生命周期日志 → 目标功能 → mount/SELinux/app
行为。更新测试必须至少从上一个正式 ZIP 覆盖安装一次；若修改了 module ID、目录布局、配置 schema、
binary ABI 或 mount layout，先写迁移与回滚逻辑，再发布。

安装 ZIP 必须根放 `module.prop`；KernelSU 模块不支持 Recovery 安装。`customize.sh` 被导入到
KernelSU BusyBox ash，使用 `abort` 报失败、`ui_print` 输出信息；只有在真正自行处理解压/权限/错误
恢复时才设置 `SKIPUNZIP=1`。先做 API、ABI、runtime 和依赖检查，再写任何不可逆数据。

## updateJson

在 `module.prop` 设定可审计的 HTTPS `updateJson=<URL>` 后，当前 Manager 会在模块 enabled、未待更新、
未待移除且网络可用时请求它。JSON 至少应提供：

```json
{
  "version": "1.2.0",
  "versionCode": 120,
  "zipUrl": "https://example.invalid/releases/example-module-v1.2.0.zip",
  "changelog": "- Fixed example behavior"
}
```

只有远端 `versionCode` 大于本地且 `zipUrl` 非空时，当前实现才宣布更新。确保 `versionCode` 单调递增；
不要复用 ID 发布不同软件；更新 JSON 与 ZIP 都走 HTTPS、由稳定域名提供、保留旧版本/哈希和变更说明。
当前实现没有在该解析段验证 ZIP 哈希字段，因此发布者仍应公开 SHA-256/签名并在 CI 或下载流程中自行
验证，不要虚构“Manager 已做端到端签名验证”。

源码锚点：`manager/.../data/repository/ModuleRepositoryImpl.kt` 的 `checkUpdate()` 读取
`version`、`versionCode`、`zipUrl`、`changelog`；`userspace/ksud/src/module.rs` 的安装流程使用
`MODULE_UPDATE_DIR` 并要求 ZIP 根 `module.prop`。

## 真机验收矩阵

| 场景 | 必验内容 |
|---|---|
| 冷启动 | 完整开机、不超过预期时长、无持续 crash/AVC、功能生效 |
| 更新 | 旧版→新版后 config/数据迁移、重启切换、版本展示、无重复 daemon |
| 禁用/移除 | `disable` 后功能停止；`remove`/卸载后只清自己的外部数据 |
| 安全模式/救援 | 高风险模块有可执行的恢复说明，用户可在不依赖 WebUI 的情况下停用 |
| system 修改 | metamodule 已安装；挂载目标、软链接分区、目标 app namespace、SELinux/PackageManager 都验证 |
| late-load | `late-load.sh` 代替 post-fs-data；无 initrc 依赖；明确延迟挂载影响 |
| WebUI | 离线可用、输入注入测试、Manager 前后台/旋转、错误/超时、配置持久性 |
| native/Zygisk | 每 ABI、依赖 loader、SELinux enforcing、无依赖/不支持环境的明确失败 |
| OEM/OTA | 至少一台目标 OEM；若声称支持 A/B/OTA，在升级后冷启动与模块状态验证 |

排查时保存：ZIP SHA-256、`module.prop`、安装日志、KSU/Manager/ksud 版本、`getprop`、
`uname -a`/KMI、`logcat`、相关 `dmesg`/AVC、`/proc/*/mountinfo`、模块私有日志和精简复现步骤。

## 不应发布的信号

- 模块只能通过 Recovery 安装，或者 ZIP 有外层目录。
- `module.prop` ID/版本不稳定、`versionCode` 倒退、更新 URL 不可信。
- `post-fs-data` 中网络/长任务/`setprop`，没有超时或恢复路径。
- 用全局 `/data/adb/*.d`、`rm -rf /data/adb`、通用 `killall` 或远程 `curl | sh` 完成功能。
- 不清楚 `system/` 需要哪一个 metamodule、或未经真实 ROM 验证就承诺所有设备适用。
- WebUI 加载 CDN/远程脚本、提供任意 root terminal、或将 untrusted input 拼 shell。
- 只因 GitHub issue 关闭、Manager 卡片出现或文件存在便宣称问题已解决。
