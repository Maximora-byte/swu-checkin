# 快速上手

本文从空目录开始，完成安装、只读验证、一次正式运行和后续升级。自动化部署请在本地验证成功后，再选择 [systemd](../DEPLOYMENT.md)、[Windows](windows.md) 或 [GitHub Actions](../GITHUB_ACTIONS.md)。

## 1. 准备环境

需要 Git、[uv](https://docs.astral.sh/uv/getting-started/installation/)、可访问学校认证/业务接口的网络，以及支持 Python 3.13 的系统。Python 可由 uv 自动安装。

项目当前不发布到 PyPI。请从权威仓库或 GitHub Release 获取代码，不要安装同名第三方包。

## 2. 获取稳定版本

```bash
git clone https://github.com/Maximora-byte/swu-checkin.git
cd swu-checkin
git checkout v1.1.3
uv sync --locked --no-dev --python 3.13
```

`uv sync --locked` 会严格使用当前 tag 的 `uv.lock`。如果锁文件与项目元数据不一致，命令会失败，而不是悄悄更新依赖。

## 3. 运行只读检查

首次使用先运行：

```bash
uv run --locked --no-dev swu-checkin setup
```

它会交互读取学号和无回显密码，检查认证、请假、学生信息、宿舍 schema 和今日任务接口；不会保存密码、创建自动任务或调用签到提交接口。

再运行只读 probe：

```bash
uv run --locked --no-dev swu-checkin probe
```

可能看到：

- `[0] 今日无签到记录`：当前没有可处理任务；
- `[2] 今日已签到`：学校端已经记录成功；
- `[5] 请假中，跳过打卡`：请假策略命中；
- `[6] 检测到待签到任务（未提交）`：任务存在，但 probe 按设计没有提交；
- `[3]` / `[4]`：按 [故障排查](troubleshooting.md) 处理，不要盲目重复正式运行。

`probe` 是只读诊断：不会写状态文件、删除/刷新 cached token，也不会获取正式运行锁。

## 4. 正式运行一次

只有在你理解任务并确认只读检查正常后，才执行：

```bash
uv run --locked --no-dev swu-checkin run
```

没有设置环境变量时，CLI 会再次交互询问凭据。正式运行会：

1. 非阻塞获取本机运行锁；
2. 读取并验证 cached session，必要时只在提交前明确 401/403 时 fresh-auth 一次；
3. 检查请假、学生、宿舍和今日任务；
4. 仅在确认“待签到”后提交一次；
5. 回读学校接口确认最终状态。

同一用户下已经有正式任务运行时，第二个进程会立即跳过，不等待也不提交。

## 5. 无人值守凭据

临时 shell 可以使用环境变量：

```bash
export SWUDK_USERNAME="你的学号"
export SWUDK_PASSWORD="你的密码"
uv run --locked --no-dev swu-checkin probe
```

不要把这些命令连同真实值写入 shell 历史、脚本或仓库。长期运行应使用：

- GitHub Actions：Repository Secrets；
- Windows：安装器生成的当前用户 DPAPI 密文；
- Linux systemd：`/etc/swu-checkin/credentials.env`，`0600 root:root`。

## 6. 读取状态与 JSON

普通本地运行默认不创建状态文件。需要持久化非敏感结果时显式指定：

```bash
export SWUDK_STATUS_FILE="$PWD/status.json"
uv run --locked --no-dev swu-checkin run
uv run --locked --no-dev swu-checkin status --file "$PWD/status.json"
```

自动化解析使用 JSON 模式：

```bash
uv run --locked --no-dev swu-checkin run --json
uv run --locked --no-dev swu-checkin probe --json
```

stdout 只包含一个 `schema_version=1` JSON document；重试与诊断信息进入 stderr。字段和退出语义见 [CLI 参考](cli-reference.md)。

### 安全解读 stderr

stderr 只提供排障分类，不是服务端原始响应：

- `请求超时`：提交连接在结果可确认前超时；
- `连接异常`：连接中断，无法判断服务端是否已经处理；
- `HTTP 503`：只保留 HTTP 状态，不保留异常文本或响应正文；
- `业务码已返回`：响应包含非成功的 `code/status`，但原值有意不记录；
- `响应结构异常`：返回值不是可识别的对象结构。

提交结果不明确时，程序只回读学校状态，不在同一进程发送第二次 POST。不要根据某个分类连续手动重跑；先运行 `status`、`doctor` 和 `probe`，再按 [故障排查](troubleshooting.md) 判断。

## 7. 升级

先查看 [Releases](https://github.com/Maximora-byte/swu-checkin/releases) 的版本说明和 CI，再切换 tag：

```bash
git fetch --tags origin
git checkout <新的稳定版本标签>
uv sync --locked --no-dev --python 3.13
uv run --locked --no-dev swu-checkin doctor
uv run --locked --no-dev swu-checkin probe
```

不要只复制单个 Python 文件，也不要把新代码与旧 `uv.lock`、Windows 脚本或 systemd unit 混用。

升级后按部署方式继续检查：

- 本地：确认 `doctor` 7 项通过，再运行一次只读 `probe`；
- systemd：保留旧 release，原子切换 symlink 后启动 `swu-checkin-probe.service`；
- Windows：从新 tag 根目录重新运行安装器，确认同一个计划任务被更新；
- GitHub Actions：同步整个稳定 tag，并确认 workflow、源码和 `uv.lock` 来自同一版本。

## 下一步

- 长期 Linux 主机：[服务器部署](../DEPLOYMENT.md)
- Windows 电脑：[Windows 使用指南](windows.md)
- 无服务器方案：[GitHub Actions](../GITHUB_ACTIONS.md)
- 命令和环境变量：[CLI 与状态码参考](cli-reference.md)
- 异常排查：[故障排查](troubleshooting.md)
