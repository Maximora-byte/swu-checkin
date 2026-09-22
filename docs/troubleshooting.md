# 故障排查

先记录版本/tag、运行平台、运行方式、北京时间、状态码、CLI exit code 和异常类型名称。不要记录账号值、密码、token、验证码、ticket、完整回调 URL、宿舍地址、坐标或原始 API body。

## 基础检查顺序

```bash
swu-checkin --help
swu-checkin doctor
swu-checkin probe
```

systemd 部署再检查：

```bash
systemctl status swu-checkin.timer --no-pager -l
systemctl status swu-checkin.service --no-pager -l
journalctl -u swu-checkin.service -n 100 --no-pager
swu-checkin status --file /var/lib/swu-checkin/status.json
```

`doctor` 使用 fresh authentication，且不读写 token cache；`probe` 是只读业务检查，也不会刷新 stale cache。二者可帮助区分凭据/接口、cached session 与正式运行问题。

## 状态码 3：登录失败

常见原因包括学号或密码错误、账号锁定或需要额外验证、Secret/环境文件名称错误，以及 Windows 任务不是由保存 DPAPI 密文的同一用户运行。

先在浏览器确认账号可登录，再运行 `doctor`。不要通过命令行参数直接写密码，避免进入 shell 历史或进程列表。

## 状态码 4：网络错误或数据异常

状态 4 是 fail-closed 聚合状态，不等于“重试一定能解决”。它可能来自：

- 网络 timeout、DNS、TLS 或连接错误；
- 学校服务 HTTP 异常；
- 非 JSON、缺字段或 schema 改变；
- 请假、宿舍、任务或提交结果无法安全确认；
- cached session 在某个业务接口失效。

建议：

1. 运行 `doctor`，确认 7 项检查中失败的位置；
2. 运行一次 `probe`，观察是否稳定复现；
3. 等待学校服务恢复，不要连续手动执行正式签到；
4. 如果 `doctor` 成功而使用 cache 的正式流程稳定失败，升级到 v1.1.3 或更高版本；正式流程可在提交前明确 401/403 时安全 fresh-auth 一次；
5. 若仍失败，提交脱敏 Issue，而不是手动删除所有状态或修改 payload。

不要把 schema、JSON 或 timeout 错误一律解释为 token 失效。项目只对明确 401/403 进行 cached-session 恢复。

## probe 与正式运行结果不同

这是可能且有意的：

- `probe` 不提交，也不刷新 TokenStore；
- `doctor` 总是 fresh-auth，且不读写 cache；
- 正式运行可读取 cache，并只在明确 session expiry 时执行一次安全恢复；
- 正式运行受跨进程锁保护，probe 不受锁影响。

如果 probe 返回 `[6]`，只表示检测到待签到任务，不能当作签到成功。

## “已有签到任务正在运行，本次跳过”

这是本地并发保护，不是学校端错误。另一个正式 CLI 或定时任务已经持有锁，当前进程立即以 no-op 退出。等待现有任务完成，再读取状态；不要删除正在使用的锁文件。

systemd 明确使用 `/var/lib/swu-checkin/checkin.lock`。普通 POSIX CLI 使用 `$XDG_RUNTIME_DIR/swu-checkin.lock` 或临时目录中带 uid 的路径；可通过绝对路径 `SWUDK_LOCK_FILE` 统一锁域。

## status 显示“尚无本地运行状态”

普通本地 run 默认不记录状态，这是正常行为。systemd 默认写 `/var/lib/swu-checkin/status.json`；其他环境需要显式设置 `SWUDK_STATUS_FILE`。

`status` 只读文件，不发网络请求，不能代替学校端实时回读。

## GitHub Actions 延迟

GitHub cron 不保证准点，可能延迟数分钟到数小时。先查看 workflow 的实际 `started_at`，不要把排队延迟误判为脚本没有触发。时间窗口严格时改用 systemd 或 Windows 计划任务。

## Windows 任务问题

```powershell
Get-ScheduledTask -TaskName "SWUCheckin-Daily"
Get-ScheduledTaskInfo -TaskName "SWUCheckin-Daily"
```

确认任务由安装时同一用户运行，并且该用户在触发时登录。DPAPI 文件不能复制到另一用户或另一台机器使用。

## 安全提交 Issue

Issue 至少包含版本或 commit SHA、Linux/Windows 与 Python 版本、部署方式、状态码、exit code、命令模式、稳定复现步骤，以及字段名/类型/HTTP 状态/异常类型等脱敏结构信息。

提交入口：[Maximora-byte/swu-checkin/issues](https://github.com/Maximora-byte/swu-checkin/issues)。
