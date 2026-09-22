# Windows 使用指南

Windows 安装器把项目放到当前用户的 `%LOCALAPPDATA%\SWUCheckin`，使用独立 Python 3.13 虚拟环境，并创建每天北京时间 21:15、21:45 的计划任务。

## 前提

- Windows 10/11；
- Windows PowerShell 5.1 或 PowerShell 7；
- 当前用户可以创建自己的计划任务；
- 安装时可以访问 GitHub、Astral uv Release 和学校接口。

## 安装

从权威仓库下载并解压稳定版本，在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\install.ps1
```

安装器会：

1. 优先使用现有 uv；缺失时下载脚本固定版本的官方 uv ZIP，并校验官方 SHA-256；
2. 安装 Python 3.13，按 `uv.lock` 创建非 editable 独立环境；
3. 交互读取账号和 SecureString 密码；
4. 将密码通过 Windows DPAPI 加密，密文只能由同一台机器上的同一 Windows 用户解密；
5. 先运行 `swu-checkin doctor`；成功后才创建/更新 `SWUCheckin-Daily` 任务；
6. 为同一任务配置 21:15、21:45 两个 trigger，并使用 `IgnoreNew` 防止重叠运行。

账号会保存在本地配置 JSON；密码不会写入 JSON、环境文件、任务参数或日志。

## 验证

```powershell
Get-ScheduledTask -TaskName "SWUCheckin-Daily"
Get-ScheduledTaskInfo -TaskName "SWUCheckin-Daily"
```

手动运行已安装 CLI：

```powershell
& "$env:LOCALAPPDATA\SWUCheckin\.venv\Scripts\swu-checkin.exe" probe
& "$env:LOCALAPPDATA\SWUCheckin\.venv\Scripts\swu-checkin.exe" status `
  --file "$env:LOCALAPPDATA\SWUCheckin\status.json"
```

计划任务使用当前用户的交互登录令牌，因此触发时该用户需要处于登录状态。

## 更新

下载新的稳定 tag，阅读 Release Notes 后，在新版本仓库根目录再次运行安装器：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\install.ps1
```

重复安装会更新同一个目录和同一个计划任务，不会追加重复任务或 trigger。doctor 失败时，安装器会移除本项目任务，避免留下无法验证的自动执行。

## 卸载

```powershell
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\SWUCheckin\uninstall.ps1"
```

卸载器只删除 `SWUCheckin-Daily` 和 `%LOCALAPPDATA%\SWUCheckin`，不会卸载系统已有的 uv、Python，也不会修改其他计划任务。

## 常见问题

- **DPAPI 解密失败**：确认任务与安装器由同一 Windows 用户运行，且密文没有复制到另一台机器。
- **任务没有执行**：检查用户在触发时是否登录，并查看任务历史和 `LastTaskResult`。
- **重复触发**：任务采用 `IgnoreNew`；CLI 还会使用 `%LOCALAPPDATA%\SWUCheckin\checkin.lock` 做第二层跨进程保护。
- **状态码 3/4**：按 [故障排查](troubleshooting.md) 处理，不要公开 DPAPI 文件、账号或原始响应。
