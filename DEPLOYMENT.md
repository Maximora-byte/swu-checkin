# Linux systemd 部署

macOS 手动桌面预览请参见 [macOS 指南](docs/macos-desktop.md)，Android 手动客户端请参见 [Android 指南](docs/android-client.md)；这些前端不使用本文的 systemd timer。

本文适用于可信的长期在线 Linux 主机。项目是一次性任务，不需要常驻 Web 服务；systemd timer 在北京时间 21:15、21:45 调度，第二次运行会识别已签到状态。units 设置 `AccuracySec=30s`，不承诺精确到秒；电脑关机、网络异常或学校服务不可用仍可能导致漏签。

> [!IMPORTANT]
> 只使用 [Maximora-byte/swu-checkin](https://github.com/Maximora-byte/swu-checkin) 同一稳定 tag 的代码、文档、`uv.lock` 和 units。不要混用上游、第三方 fork 或不同版本的文件。

启用自动任务表示允许以后按时正式提交，不会每次再确认。程序使用学校记录的寝室坐标，不测量本人实际 GPS、不能证明本人在寝；仅在能确保每次运行都符合学校规则时启用，不符合时提前停用。

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
- 账号密码保存在 `/etc/swu-checkin/credentials.env`，权限 `0600 root:root`；认证 token 另由受限缓存保存，不能把缓存当成普通状态文件分享；
- 正式服务显式使用 `/var/lib/swu-checkin/checkin.lock`，避免定时与手动 service 并发；
- timer 设置 `Persistent=false`，主机错过窗口后不会补跑过期任务；
- 启用 timer 前必须通过只读 probe。

运行锁只协调同一主机上使用同一锁路径的进程，不能阻止 Actions、Windows 或另一台主机同时运行；同一账号应只保留一套正式自动调度。

## 1. 准备用户和目录

先安装 Git 与 [uv](https://docs.astral.sh/uv/getting-started/installation/)，然后：

```bash
if ! id -u swu-checkin >/dev/null 2>&1; then
  sudo useradd --system --no-create-home --shell /usr/sbin/nologin swu-checkin
fi
sudo install -d -m 0755 /opt/swu-checkin-releases
sudo install -d -m 0700 -o root -g root /etc/swu-checkin
```

服务使用 `ProtectHome=true`。虚拟环境引用的 Python 解释器也必须位于服务可读的系统路径，不能依赖 `/root`、`/home` 下的个人 Python。以下示例将 uv 管理的 Python 放在本项目独占、root 管理的 `/opt/swu-checkin-python`；不要将后面的递归权限命令用于已有共享 Python 或其他服务目录。安装目录配置见 [uv 文档](https://docs.astral.sh/uv/reference/storage/)。

```bash
uv_bin="$(command -v uv)"
sudo install -d -m 0755 /opt/swu-checkin-python
sudo env UV_PYTHON_INSTALL_DIR=/opt/swu-checkin-python \
  "$uv_bin" python install 3.13 --no-bin
```

## 2. 安装稳定 release

以下使用最新公开的 [`v2.0.0`](https://github.com/Maximora-byte/swu-checkin/releases/tag/v2.0.0) 作为稳定安装示例。当前源码已同步为 **2.1.0 预发布候选**，尚未创建新 tag/Release，不直接替换此处生产安装标签。后续部署先在 [Releases](https://github.com/Maximora-byte/swu-checkin/releases) 确认实际 tag、完整 CI、资产与限制，再将 `release_tag` 替换为所选版本，并使用该 tag 的完整代码、文档、锁文件与 units。候选预检不连接学校、不自动启用任务，也不能替代部署后的只读检查；差异见 [发布准备](docs/releases/release-readiness.md)。

```bash
release_tag=v2.0.0
release_dir="/opt/swu-checkin-releases/$release_tag"

sudo git clone --branch "$release_tag" --depth 1 \
  https://github.com/Maximora-byte/swu-checkin.git "$release_dir"
sudo env UV_PROJECT_ENVIRONMENT="$release_dir/.venv" \
  UV_PYTHON_INSTALL_DIR=/opt/swu-checkin-python \
  "$uv_bin" sync --locked --no-dev --no-editable --project "$release_dir" \
  --python 3.13 --managed-python
sudo chown -R root:root "$release_dir"
sudo chmod -R u=rwX,go=rX "$release_dir" /opt/swu-checkin-python
sudo -u swu-checkin "$release_dir/.venv/bin/swu-checkin" --help
sudo ln -sfn "$release_dir" /opt/swu-checkin.next
sudo mv -Tf /opt/swu-checkin.next /opt/swu-checkin
```

`uv_bin` 使用上一步确认的 uv 路径，避免 `sudo` 的 PATH 找不到个人安装的 uv。`--no-editable` 将项目安装进虚拟环境；它不消除对基础 Python 解释器的依赖。`/opt/swu-checkin` 应为 symlink 或尚不存在，不能用此命令覆盖已有的真实目录。部署前可在 [Releases](https://github.com/Maximora-byte/swu-checkin/releases) 核对版本、CI 和资产。

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

账号输入会回显，密码与再次确认使用无回显输入；录入器随后原子写入 `credentials.env`，启动不提交签到的 `swu-checkin-probe.service`。探测成功后才执行启用主 timer，并根据现有 `notify.env` 同步通知 timer。

更换已有凭据前先按下文停用两个 timer，并等待已经运行的 service 结束。录入器在探测前就替换旧凭据；探测失败不会还原旧文件，也不会关闭此前已经启用的 timer。失败后保持停用，修复凭据并重新探测，不要直接启用 timer。

不要用 `echo` 把真实密码拼进 shell 命令，也不要把凭据写入仓库或普通 `.env` 文件。

## 5. 可选 Telegram 汇总

Telegram 通知依赖 `/usr/bin/openclaw`，以及 root 账号下已经可用的 Telegram 通道（默认 account 为 `default`）。目标只写在 root-only 文件：

```bash
sudo install -m 0600 -o root -g root \
  /opt/swu-checkin/deploy/notify.env.example /etc/swu-checkin/notify.env
sudoedit /etc/swu-checkin/notify.env
sudo swu-checkin-set-credentials --sync-notify
```

必须先替换示例中的 `your-telegram-chat-id`。不要直接 `enable` notifier timer。`--sync-notify` 仅检查环境文件语法与 `SWUDK_NOTIFY_TARGET` 非空；缺失或无效会禁用 timer，但它不会核实收件人、登录状态或实际送达，示例占位符也会通过非空检查。

通知服务以 `root:swu-checkin` 运行，以读取 root 的 OpenClaw 配置并通过组权限读取状态；unit 清空 capabilities、启用 `NoNewPrivileges` 并限制可写路径。不要把主签到或 probe 服务改成 root，或放宽凭据/状态目录权限来修复通知。

通知按上海日期汇总已有运行记录：当天任一条状态 1/2 优先报告成功；否则有状态 5 时报告请假；否则报告最后失败，缺失或过期状态也会发出提醒。OpenClaw 命令返回 0 后写入 `notified-YYYY-MM-DD`（`0600`），当天后续执行跳过；这不等同于收件人已读。失败或超时不写标记。手动提前运行会占用当天通知机会；`SWUDK_NOTIFY_DRY_RUN=1` 也会在命令返回 0 后写标记，不应在正式状态目录中用它试发。

## 6. 验证

```bash
sudo systemctl start swu-checkin-probe.service
systemctl status swu-checkin-probe.service --no-pager -l
systemctl status swu-checkin.timer --no-pager -l
systemctl list-timers swu-checkin.timer swu-checkin-notify.timer --no-pager
```

查看非敏感状态：

```bash
sudo -u swu-checkin /opt/swu-checkin/.venv/bin/swu-checkin status \
  --file /var/lib/swu-checkin/status.json
```

查看日志：

```bash
sudo journalctl -u swu-checkin-probe.service -n 50 --no-pager
sudo journalctl -u swu-checkin.service -n 100 --no-pager
sudo journalctl -u swu-checkin-notify.service -n 50 --no-pager
```

正式服务创建 `/var/lib/swu-checkin`（`0770 swu-checkin:swu-checkin`），原子写入 `status.json`（`0640`）。它只保留当天最近 10 次顶层运行；probe 不写运行状态，首次正式运行前没有状态文件是正常情况。认证缓存为同目录的 `auth-token-cache`（POSIX `0600`，不是加密文件）；不得随状态文件一起上传或打印。

提供的 probe unit 没有设置正式服务的 `SWUDK_STATUS_FILE`，因此不保证读取 `/var/lib/swu-checkin/auth-token-cache`；它适合验证凭据和只读接口，不应拿它的成功证明正式服务缓存一定正常。

probe 是 oneshot，正常完成后通常显示 `inactive (dead)`；结合 `systemctl start` 的退出码、`Result` 和 `ExecMainStatus` 判断，不要仅凭 inactive 判为失败：

```bash
systemctl show swu-checkin-probe.service -p Result -p ExecMainStatus
```

不要把包含敏感数据的完整 journal 直接贴到公开 Issue。报告问题前按 [故障排查](docs/troubleshooting.md) 脱敏。

日志中的 `业务码已返回` 是隐私保护后的固定分类，不会显示学校返回的原值。`请求超时`、`连接异常` 或 `HTTP <状态>` 也只表示传输结果；遇到这些分类时先读取状态并运行只读 probe，不要连续手动启动正式 service。

## 升级与回滚

升级前保留当前 symlink 目标：

```bash
readlink -f /opt/swu-checkin
```

先记录原先启用的 timer，停用两者，并等待主任务、probe、notifier 均结束；停止 timer 不会终止已经运行的 service。不要为了升级中断可能正在提交的请求。把新 tag 按前面的安装步骤同步到新的 release 目录，但暂不切换 symlink，再执行下列步骤（`release_dir` 必须是新版本的绝对路径）：

```bash
sudo systemctl disable --now swu-checkin.timer swu-checkin-notify.timer
systemctl is-active swu-checkin.service swu-checkin-probe.service swu-checkin-notify.service
# 确认没有 activating/active/deactivating 的任务后，再执行：
sudo -u swu-checkin "$release_dir/.venv/bin/swu-checkin" --help
sudo ln -sfn "$release_dir" /opt/swu-checkin.next
sudo mv -Tf /opt/swu-checkin.next /opt/swu-checkin
sudo install -m 0644 /opt/swu-checkin/deploy/systemd/*.service /etc/systemd/system/
sudo install -m 0644 /opt/swu-checkin/deploy/systemd/*.timer /etc/systemd/system/
sudo install -m 0755 /opt/swu-checkin/deploy/swu-checkin-set-credentials.py \
  /usr/local/sbin/swu-checkin-set-credentials
sudo systemctl daemon-reload
sudo systemd-analyze verify /etc/systemd/system/swu-checkin*.service \
  /etc/systemd/system/swu-checkin*.timer
sudo systemctl start swu-checkin-probe.service
```

probe 失败时保持 timer 停用。成功后只恢复原先有意启用的调度：主任务用 `sudo systemctl enable --now swu-checkin.timer`；原先启用通知时再运行 `sudo swu-checkin-set-credentials --sync-notify`。确认 probe 和 timer 正常后再考虑删除旧 release，不要删除仍被虚拟环境引用的 Python 安装。

回滚同样先停用 timer 并等待 service 结束，把 symlink 指回旧目录、重装旧 units 和凭据录入器、`daemon-reload`、重新 probe，再恢复原先的调度。

## 手动控制

停用自动签到与通知：

```bash
sudo systemctl disable --now swu-checkin.timer
sudo systemctl disable --now swu-checkin-notify.timer
```

这只停止未来调度，不会取消已经运行的正式签到或通知。

重新验证凭据并按配置恢复：

```bash
sudo swu-checkin-set-credentials
```

该命令在 probe 成功后已经同步通知 timer。若只修改 `notify.env`，使用 `sudo swu-checkin-set-credentials --sync-notify`，无需重新录入账号密码。

## 故障排查

- unit 无法启动：检查 `/opt/swu-checkin` symlink、虚拟环境和 `credentials.env` 权限；
- timer 没触发：检查 `systemctl list-timers` 和系统时钟；units 使用显式 `Asia/Shanghai`；
- 提示运行锁：已有正式 service 正在执行，等待结束，不要删除活跃锁文件；
- 状态 3/4：运行 probe、查看脱敏异常类型，并按 [故障排查](docs/troubleshooting.md) 处理；
- 通知未发：先确认签到状态文件，再检查 `notify.env` 和 OpenClaw Telegram 通道。

本 fork 的 systemd、状态文件、锁和 notifier 由当前仓库独立维护；相关问题请提交到 [当前仓库 Issues](https://github.com/Maximora-byte/swu-checkin/issues)。
