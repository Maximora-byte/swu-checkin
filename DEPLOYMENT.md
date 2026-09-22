# Linux systemd 部署

本文适用于可信的长期在线 Linux 主机。项目是一次性任务，不需要常驻 Web 服务；systemd timer 会在北京时间 21:15、21:45 各启动一次，第二次运行会识别已签到状态。

> [!IMPORTANT]
> 只使用 [Maximora-byte/swu-checkin](https://github.com/Maximora-byte/swu-checkin) 同一稳定 tag 的代码、文档、`uv.lock` 和 units。不要混用上游、第三方 fork 或不同版本的文件。

## 部署模型

```text
swu-checkin.timer (21:15 / 21:45)
        ↓
swu-checkin.service (专用 swu-checkin 用户)
        ↓
/var/lib/swu-checkin/status.json + checkin.lock + token cache

可选：swu-checkin-notify.timer (21:50) → Telegram 汇总
```

安全边界：

- Python 3.13，严格使用 `uv.lock`；
- 代码位于版本化 release 目录，`/opt/swu-checkin` 是可回滚 symlink；
- 主任务和 probe 使用无登录 shell 的 `swu-checkin` 用户；
- 凭据仅保存在 `/etc/swu-checkin/credentials.env`，权限 `0600 root:root`；
- 正式服务显式使用 `/var/lib/swu-checkin/checkin.lock`，避免定时与手动 service 并发；
- timer 设置 `Persistent=false`，主机错过窗口后不会补跑过期任务；
- 启用 timer 前必须通过只读 probe。

## 1. 准备用户和目录

先安装 Git 与 [uv](https://docs.astral.sh/uv/getting-started/installation/)，然后：

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin swu-checkin 2>/dev/null || true
sudo install -d -m 0755 /opt/swu-checkin-releases
sudo install -d -m 0700 -o root -g root /etc/swu-checkin
```

## 2. 安装稳定 release

以下以 `v1.1.3` 为例。升级时替换为新的稳定 tag：

```bash
release_tag=v1.1.3
release_dir="/opt/swu-checkin-releases/$release_tag"

sudo git clone --branch "$release_tag" --depth 1 \
  https://github.com/Maximora-byte/swu-checkin.git "$release_dir"
sudo env UV_PROJECT_ENVIRONMENT="$release_dir/.venv" \
  uv sync --locked --no-dev --no-editable --project "$release_dir" --python 3.13
sudo chown -R root:root "$release_dir"
sudo ln -sfn "$release_dir" /opt/swu-checkin
```

`--no-editable` 确保虚拟环境不依赖可修改源码路径。发布前可在 [Releases](https://github.com/Maximora-byte/swu-checkin/releases) 核对版本、CI 和资产。

## 3. 安装 units 与凭据录入器

```bash
sudo install -m 0644 /opt/swu-checkin/deploy/systemd/*.service /etc/systemd/system/
sudo install -m 0644 /opt/swu-checkin/deploy/systemd/*.timer /etc/systemd/system/
sudo install -m 0755 /opt/swu-checkin/deploy/swu-checkin-set-credentials.py \
  /usr/local/sbin/swu-checkin-set-credentials
sudo systemctl daemon-reload
```

先验证 unit：

```bash
systemd-analyze verify /etc/systemd/system/swu-checkin*.service \
  /etc/systemd/system/swu-checkin*.timer
```

## 4. 安全录入凭据并启用 timer

```bash
sudo swu-checkin-set-credentials
```

录入器使用无回显输入并原子写入 `credentials.env`。随后启动 `swu-checkin-probe.service`；只有只读探测成功才启用 `swu-checkin.timer`。

不要用 `echo` 把真实密码拼进 shell 命令，也不要把凭据写入仓库或普通 `.env` 文件。

## 5. 可选 Telegram 汇总

Telegram 通知依赖本机已经可用的 OpenClaw Telegram 通道。目标只写在 root-only 文件：

```bash
sudo install -m 0600 -o root -g root \
  /opt/swu-checkin/deploy/notify.env.example /etc/swu-checkin/notify.env
sudoedit /etc/swu-checkin/notify.env
sudo swu-checkin-set-credentials --sync-notify
```

不要直接 `enable` notifier timer。`--sync-notify` 会验证目标配置；无效或缺失时保持禁用。通知服务因为需要读取 root 的 OpenClaw 通道状态而以 root 运行，但 unit 移除了 capabilities，并限制可写路径。

## 6. 验证

```bash
systemctl start swu-checkin-probe.service
systemctl status swu-checkin-probe.service --no-pager -l
systemctl status swu-checkin.timer --no-pager -l
systemctl list-timers swu-checkin.timer swu-checkin-notify.timer --no-pager
```

查看非敏感状态：

```bash
/opt/swu-checkin/.venv/bin/swu-checkin status \
  --file /var/lib/swu-checkin/status.json
```

查看日志：

```bash
journalctl -u swu-checkin-probe.service -n 50 --no-pager
journalctl -u swu-checkin.service -n 100 --no-pager
journalctl -u swu-checkin-notify.service -n 50 --no-pager
```

不要把包含敏感数据的完整 journal 直接贴到公开 Issue。报告问题前按 [故障排查](docs/troubleshooting.md) 脱敏。

## 升级与回滚

升级前保留当前 symlink 目标：

```bash
readlink -f /opt/swu-checkin
```

将新 tag 安装到新的 `/opt/swu-checkin-releases/<tag>`，完成以下验证后再原子切换：

```bash
sudo -u swu-checkin /opt/swu-checkin-releases/<tag>/.venv/bin/swu-checkin --help
sudo ln -sfn /opt/swu-checkin-releases/<tag> /opt/swu-checkin
sudo install -m 0644 /opt/swu-checkin/deploy/systemd/*.service /etc/systemd/system/
sudo install -m 0644 /opt/swu-checkin/deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start swu-checkin-probe.service
```

确认 probe 和 timer 正常后再删除旧 release。回滚时把 symlink 指回旧目录、重装旧 units、`daemon-reload` 并重新运行 probe。不要在 timer 正在执行时切换。

## 手动控制

停用自动签到与通知：

```bash
sudo systemctl disable --now swu-checkin.timer
sudo systemctl disable --now swu-checkin-notify.timer
```

重新验证凭据并按配置恢复：

```bash
sudo swu-checkin-set-credentials
sudo swu-checkin-set-credentials --sync-notify
```

## 故障排查

- unit 无法启动：检查 `/opt/swu-checkin` symlink、虚拟环境和 `credentials.env` 权限；
- timer 没触发：检查 `systemctl list-timers` 和系统时钟；units 使用显式 `Asia/Shanghai`；
- 提示运行锁：已有正式 service 正在执行，等待结束，不要删除活跃锁文件；
- 状态 3/4：运行 probe、查看脱敏异常类型，并按 [故障排查](docs/troubleshooting.md) 处理；
- 通知未发：先确认签到状态文件，再检查 `notify.env` 和 OpenClaw Telegram 通道。

本 fork 的 systemd、状态文件、锁和 notifier 由当前仓库独立维护；相关问题请提交到 [当前仓库 Issues](https://github.com/Maximora-byte/swu-checkin/issues)。
