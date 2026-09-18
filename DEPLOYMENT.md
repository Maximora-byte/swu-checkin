# 服务器部署

> 本文档适用于由 [Maximora-byte](https://github.com/Maximora-byte) 独立维护的 [Maximora-byte/swu-checkin](https://github.com/Maximora-byte/swu-checkin)。部署时应以当前仓库对应 commit 的文档和 `uv.lock` 为准，不要混用上游或其他 fork 的 unit、脚本和配置。部署问题请提交到[本仓库 Issues](https://github.com/Maximora-byte/swu-checkin/issues)。

推荐在可信的 Linux 主机上使用 systemd timer 运行本项目。任务是一次性脚本，不需要常驻 Web 服务。

## 关键要求

- 使用 Python 3.13 与仓库中的 `uv.lock`。
- 生产部署固定到本仓库已审阅的 commit；升级前先查看该 commit 的 CI 和变更说明，并保留可回滚的旧 release。
- 凭据仅写入 `/etc/swu-checkin/credentials.env`，权限设为 `0600`，不要提交到 Git。
- 服务进程明确设置 `TZ=Asia/Shanghai`。
- timer 不启用持久补跑，避免服务器在签到窗口外启动后提交过期任务。
- 部署前先运行 `swu-checkin-probe.service` 做只读探测；该服务只登录并读取任务，不提交签到。
- 命令行也可使用 `swu-checkin --probe`；需要自动化解析时使用 `swu-checkin --probe --json`，stdout 仅包含 schema v1 JSON。
- 签到任务把非敏感结果写入 `/var/lib/swu-checkin/status.json`；通知 timer 每天 21:50 汇总一次并发送 Telegram。
- Telegram target 仅写入 `/etc/swu-checkin/notify.env`，权限设为 `0600 root:root`，不要提交到 Git。

部署完成后，在服务器终端运行凭据录入器：

```bash
sudo swu-checkin-set-credentials
```

该命令使用无回显输入，原子写入凭据文件，先运行只读探测；只有探测成功才启用 timer。凭据文件格式为：

```ini
SWUDK_USERNAME=学号
SWUDK_PASSWORD=密码
```

推荐安装路径为 `/opt/swu-checkin`，systemd 单元模板位于 `deploy/systemd/`。默认在北京时间 21:15 与 21:45 各执行一次；第二次运行会识别“已签到”并退出。

如需 Telegram 汇总通知，先复制示例并填入实际 target：

```bash
sudo install -d -m 0700 -o root -g root /etc/swu-checkin
sudo install -m 0600 -o root -g root deploy/notify.env.example /etc/swu-checkin/notify.env
sudoedit /etc/swu-checkin/notify.env
sudo systemctl enable --now swu-checkin-notify.timer
```

通知服务暂时以 root 运行，因为本机 OpenClaw CLI 使用 root 所有的通道配置与状态；单元仍保留只读 home、空 capability 集合，并仅开放 `/root/.openclaw/state` 和专用 cache 的必要写权限。主签到服务和 probe 继续使用专用 `swu-checkin` 用户。

查看状态与日志：

```bash
systemctl start swu-checkin-probe.service
systemctl status swu-checkin-probe.service
systemctl status swu-checkin.timer
systemctl status swu-checkin-notify.timer
systemctl list-timers swu-checkin.timer
journalctl -u swu-checkin.service
journalctl -u swu-checkin-notify.service
```

systemd 单元继续调用稳定的 `swu-checkin` console script。项目内部已将 CLI 展示、业务服务、HTTP client 与状态存储解耦；这不改变 timer 时间、环境变量、退出码或 `/var/lib/swu-checkin/status.json` 格式。

本 fork 的部署增强（受限 systemd、只读 probe、状态文件权限和 Telegram 汇总）由 `Maximora-byte/swu-checkin` 独立维护，不应据此要求原上游项目提供兼容或运维支持。

停用：

```bash
sudo systemctl disable --now swu-checkin.timer
sudo systemctl disable --now swu-checkin-notify.timer
```
