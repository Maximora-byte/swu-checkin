# Windows 脚本部署（Python / uv）

本页介绍 `scripts/windows/install.ps1` 的脚本部署，**不是**独立 EXE 安装包。想双击中文窗口的用户请看 [Windows 桌面预览版](windows-desktop.md)。两种方式共用业务核心，但凭据格式、安装器和任务不同，不能混用。

本文以所在源码 commit 为准。已发布 Python 稳定版仍为 [v2.0.0](https://github.com/Maximora-byte/swu-checkin/releases/tag/v2.0.0)；当前源码已同步为 2.1.0 预发布候选，未创建新 tag/Release。生产脚本部署选择已审阅且一致的 tag/commit、文档和锁文件；差异见 [候选说明](releases/v2.1.0.md)与 [发布准备](releases/release-readiness.md)。

| 项目 | 本页脚本部署 | 桌面预览版 |
| --- | --- | --- |
| 程序 | uv 管理的 Python 3.13 非 editable 环境 | 内置运行时的 `SWUCheckin.exe` |
| 程序目录 | `%LOCALAPPDATA%\SWUCheckin\.venv` | `%LOCALAPPDATA%\Programs\SWUCheckin` |
| 用户数据 | `%LOCALAPPDATA%\SWUCheckin` | 同一数据根目录，使用 `desktop-*` 配置文件 |
| 密码保护 | `password.dpapi`；账号在 `config.json` | 账号和密码一起保存在 `desktop-credentials.dpapi` |
| 计划任务 | `SWUCheckin-Daily` | `SWUCheckin-Desktop` |
| 安装后调度 | doctor 成功后启用正式签到 | 不创建任务；在 GUI 中另行选择和授权 |
| 错过执行时间 | `StartWhenAvailable=true`，可能补跑 | `StartWhenAvailable=false`，不补跑 |
| 卸载数据 | 递归删除整个共用数据根目录 | 保留个人配置 |

> [!WARNING]
> 脚本安装并非只读配置：诊断成功后会启用每天北京时间 21:15、21:45 的正式签到。仅在能确保每次运行时本人在寝且符合学校规则时使用；不满足时提前停用。本工具使用学校寝室坐标，不测量真实 GPS，不能证明人在寝。

## 前提与安装

- 目标平台为 Windows 10/11，使用 Windows PowerShell 5.1 或 PowerShell 7
- 当前用户能创建自己的计划任务，并在触发时保持登录、联网和开机
- 安装时能访问官方代码/依赖下载源及学校接口
- 脚本支持下载 x64/ARM64 的 uv，但这不等于全部 Python 原生依赖或桌面应用都已在 ARM64 验收

从[权威仓库 Releases](https://github.com/Maximora-byte/swu-checkin/releases) 选择 Python 稳定 tag，并使用同一 tag 的代码、文档与 `uv.lock`。在仓库根目录运行：

```powershell
.\scripts\windows\install.ps1
```

仅在设备当前策略允许执行脚本时运行。若脚本被系统或组织策略阻止，请遵守管理规则并核实来源；不要修改执行策略或绕过保护来完成安装。

安装器会：

1. 优先使用 PATH 中已有的 uv；没有时下载脚本指定版本的官方 ZIP，并校验官方 SHA-256 文件
2. 安装 Python 3.13，按 `uv.lock` 创建非 editable 独立环境
3. 交互读取账号和 SecureString 密码；账号写入本地 JSON，密码通过当前用户 DPAPI 加密
4. 将凭据临时注入子进程环境，先运行 `swu-checkin doctor`
5. doctor 成功后创建/更新 `SWUCheckin-Daily`，配置 21:15、21:45 两个北京时间 trigger

任务使用 `InteractiveToken`、`LeastPrivilege`、`IgnoreNew`、网络可用条件和 15 分钟执行上限。当前脚本启用 `StartWhenAvailable=true`；若不允许错过窗口后补跑，请勿把它当作桌面版的“不补跑”调度。

DPAPI 密文只能由保存它的 Windows 用户在相应环境解密；不要复制给其他用户或机器。密码不进入任务参数、JSON 或日志，但执行时必须短暂出现在子进程环境中。

## 验证与只读检查

```powershell
Get-ScheduledTask -TaskName "SWUCheckin-Daily"
Get-ScheduledTaskInfo -TaskName "SWUCheckin-Daily"

& "$env:LOCALAPPDATA\SWUCheckin\.venv\Scripts\swu-checkin.exe" doctor
& "$env:LOCALAPPDATA\SWUCheckin\.venv\Scripts\swu-checkin.exe" probe
& "$env:LOCALAPPDATA\SWUCheckin\.venv\Scripts\swu-checkin.exe" status `
  --file "$env:LOCALAPPDATA\SWUCheckin\status.json"
```

直接调用安装后的 CLI 不会自动读取脚本的 `config.json` / `password.dpapi`；`doctor` / `probe` 在没有环境凭据时会重新询问账号和无回显密码。`status` 只读文件，不访问学校。

`run.ps1` 固定调用 `run --json` 并读取已保存凭据，是正式签到入口，没有 probe 参数。不要用运行它、启动计划任务或真实签到来测试安装。

## 停用、更新与重新启用

不满足自动签到条件或准备更新时，先停用任务，并等待已有执行完成：

```powershell
Disable-ScheduledTask -TaskName "SWUCheckin-Daily"
Get-ScheduledTask -TaskName "SWUCheckin-Daily"
```

停用只阻止后续触发，不撤销已经开始的请求。不要在提交结果未知时强行重复执行。

从新 tag 根目录重新运行 `install.ps1` 会更新同一个目录和任务，并在 doctor 成功后启用任务，不会追加重复 trigger。doctor 返回失败时会移除本项目任务；但其他安装中途错误不保证旧任务已被移除，所以升级前需主动停用。安装后再次检查任务与只读 probe。

## 迁移到桌面预览版

桌面版发现 `SWUCheckin-Daily` 仍注册时，即使任务已禁用，也会拒绝启用桌面任务。迁移步骤：

1. 停用旧任务，等待正在执行的任务结束
2. 在任务计划程序删除 `SWUCheckin-Daily` 的任务登记，或在尚未保存桌面数据前完成旧脚本卸载
3. 安装桌面版，在当前用户下重新录入并保存凭据，先做只读检测，再按需启用任务

两种凭据格式不会自动迁移。若桌面版已保存配置，**不要运行旧脚本卸载器**：它会递归删除 `%LOCALAPPDATA%\SWUCheckin`，包括桌面配置、密文与状态。此时只删除旧任务登记并谨慎处理旧文件，不要删除整个共用目录。

## 卸载脚本部署

确认没有需要保留的桌面版数据后：

```powershell
& "$env:LOCALAPPDATA\SWUCheckin\uninstall.ps1"
```

脚本卸载器删除 `SWUCheckin-Daily` 和整个 `%LOCALAPPDATA%\SWUCheckin`，不会卸载系统已有的 uv、Python，也不会删除 `SWUCheckin-Desktop` 或其他任务。若两种方式曾共存，先按上面的迁移警告处理，避免删数据后留下桌面任务。

## 常见问题

- **DPAPI 解密失败**：确认运行任务和保存密文的是同一 Windows 用户，不要公开密文或复制到另一设备
- **任务未执行**：检查登录、电源、网络、任务历史和 `LastTaskResult`；这些条件不保证学校端成功
- **并发跳过**：`IgnoreNew` 之外，正式 CLI 与桌面版默认共用 `%LOCALAPPDATA%\SWUCheckin\checkin.lock`；不要删除活跃锁文件
- **状态码 3/4**：见 [故障排查](troubleshooting.md)，先只读诊断，不要重复正式提交
