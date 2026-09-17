# 服务器部署

推荐在可信的 Linux 主机上使用 systemd timer 运行本项目。任务是一次性脚本，不需要常驻 Web 服务。

## 关键要求

- 使用 Python 3.13 与仓库中的 `uv.lock`。
- 凭据仅写入 `/etc/swu-checkin/credentials.env`，权限设为 `0600`，不要提交到 Git。
- 服务进程明确设置 `TZ=Asia/Shanghai`。
- timer 不启用持久补跑，避免服务器在签到窗口外启动后提交过期任务。
- 部署前先运行 `swu-checkin-probe.service` 做只读探测；该服务只登录并读取任务，不提交签到。

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

查看状态与日志：

```bash
systemctl start swu-checkin-probe.service
systemctl status swu-checkin-probe.service
systemctl status swu-checkin.timer
systemctl list-timers swu-checkin.timer
journalctl -u swu-checkin.service
```

停用：

```bash
sudo systemctl disable --now swu-checkin.timer
```
