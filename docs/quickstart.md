# 快速上手

本文面向当前源码的 Python CLI。Windows 用户可选 [桌面版](windows-desktop.md) 或 [免安装 ZIP](windows-portable.md)，Android 用户可直接安装 [Android 客户端](android-client.md)，无需执行 uv/Python 步骤。macOS 继续为 [桌面预览](macos-desktop.md)。自动化部署见 [systemd](../DEPLOYMENT.md)、[Windows 脚本](windows.md) 或 [GitHub Actions](../GITHUB_ACTIONS.md)。

## 1. 准备环境

需要 Git、[uv](https://docs.astral.sh/uv/getting-started/installation/)、可访问学校认证/业务接口的网络，以及支持 Python 3.13 的系统。Python 可由 uv 自动安装。

项目当前不发布到 PyPI。请从权威仓库或 GitHub Release 获取代码，不要安装同名第三方包。

## 2. 获取与本文对应的源码

```bash
git clone https://github.com/Maximora-byte/swu-checkin.git
cd swu-checkin
uv sync --locked --no-dev --python 3.13
```

上例使用当前默认分支。要使用本次发行，执行 `git checkout v2.1.1`，并使用同一 tag 的文档与 `uv.lock`；发行文件见 [v2.1.1](https://github.com/Maximora-byte/swu-checkin/releases/tag/v2.1.1)。Python 项目版本为 2.1.1，Android 独立版本为 1.0.0。macOS 附件仍为预览，Windows 尚未获得 Authenticode 签名。

`uv sync --locked` 会严格使用检出版本的 `uv.lock`。如果锁文件与项目元数据不一致，命令会失败，而不是悄悄更新依赖。

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
- `[2] 已签到`：学校端已经记录成功；
- `[5] 请假期间无需签到`：请假策略命中；
- `[6] 检测到待签到任务（未提交）`：任务存在，但 probe 按设计没有提交；
- `[3]` / `[4]`：按 [故障排查](troubleshooting.md) 处理，不要盲目重复正式运行。

`probe` 是业务只读诊断：不会提交签到、写运行状态文件或获取正式运行锁，但不是零本地写入。它会复用有效 cached token；无 cache 或 token 在最初身份校验阶段明确失效时，认证层可能 fresh-auth 并创建或替换本地 cache。若 cache 通过身份校验、但在后续业务读取阶段失效，probe 会 fail closed，不执行正式流程的 stale-session 自动恢复。

## 4. 正式运行一次

只有在本人当前确实在寝、符合学校规则，且只读检查正常后，才执行。程序使用学校记录的寝室坐标，不测量实际 GPS，技术成功不能证明人在寝：

```bash
uv run --locked --no-dev swu-checkin run
```

没有设置环境变量时，CLI 会再次交互询问凭据。正式运行会：

1. 非阻塞获取本机运行锁；
2. 读取并验证 cached session；初始 cache 缺失/失效时重新认证，后续业务读取阶段明确 401/403 时只恢复一次；
3. 读取请假和今日任务；无任务、已签到或请假时提前返回；
4. 待签到时读取学生与宿舍，验证 payload 后最多发送一次签到提交 POST；
5. 在可回查的响应路径中有界读取学校状态，确认结果；无法安全解析时返回数据异常。

同一锁路径下已经有正式 CLI 或桌面任务运行时，第二个正式操作不等待、不提交。锁是本机协调，不阻止另一台机器或不同锁域的提交；不要让多种部署同时负责同一账号。

## 5. 无人值守凭据

临时 shell 可以使用环境变量：

```bash
export SWUDK_USERNAME="你的学号"
export SWUDK_PASSWORD="你的密码"
uv run --locked --no-dev swu-checkin probe
```

不要把这些命令连同真实值写入 shell 历史、脚本或仓库。需要保存账号或为部署提供凭据时，按实际入口选择：

- GitHub Actions：Repository Secrets；
- Windows 桌面预览版：点击“保存账号”后生成的当前用户 DPAPI 密文；
- macOS 桌面预览版：显式保存到钥匙串，按需显式读取，仅支持手动操作；
- Android 手动预览版：可选保存到设备 Keystore 保护的密文，仅支持手动操作；
- Windows 脚本部署：脚本安装器生成的当前用户 DPAPI 密文，使用方式与桌面版不同；
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

完成业务执行时，stdout 输出一个 `schema_version=1` JSON document，重试与诊断信息进入 stderr。运行锁忙、锁错误、安全开关拒绝和参数错误等业务前退出可能没有 JSON；退出 0 也可能只是锁忙跳过。字段、特殊退出和 `status --file` 路径优先级见 [CLI 参考](cli-reference.md)。

### 安全解读诊断

诊断提供固定排障分类，不是服务端原始响应；JSON 模式将其放在 stderr：

- `请求超时`：请求超时；结合阶段判断是提交前失败还是提交结果未知；
- `连接异常`：连接中断；发生在 submit 阶段时不能据此判断服务端是否已经处理；
- `HTTP 503`：只保留 HTTP 状态，不保留异常文本或响应正文；
- `业务码已返回`：被分类的响应包含 `code/status`，但原值有意不记录；
- `响应结构异常`：返回值不是可识别的对象结构。

提交传输结果不明确时，程序执行有界只读回查；提交响应无法解析时也可能直接返回数据异常。不论哪种情况，同一次正式调用都不会再发第二次签到提交 POST。不要根据某个分类连续手动重跑；先运行 `status`、`doctor` 和 `probe`，再按 [故障排查](troubleshooting.md) 判断。

## 7. 升级

先查看 [Releases](https://github.com/Maximora-byte/swu-checkin/releases) 的版本说明和 CI，再切换 tag：

```bash
git fetch --tags origin
new_tag="替换为已确认的稳定版本标签"
git checkout "$new_tag"
uv sync --locked --no-dev --python 3.13
uv run --locked --no-dev swu-checkin doctor
uv run --locked --no-dev swu-checkin probe
```

不要只复制单个 Python 文件，也不要把新代码与旧 `uv.lock`、Windows 脚本或 systemd unit 混用。

升级后按部署方式继续检查：

- 本地：确认 `doctor` 7 项通过，再运行一次只读 `probe`；
- systemd：保留旧 release，原子切换 symlink 后启动 `swu-checkin-probe.service`；
- Windows 脚本：先停用旧任务，再从新 tag 根目录重新运行脚本安装器；它会在 doctor 成功后更新并启用同一个任务；
- Windows 桌面预览版：按 [桌面指南](windows-desktop.md) 检查构建来源，先关闭任务与窗口，再更新安装包；
- macOS / Android 预览：按各自指南核对源码、平台和签名，使用完整匹配的新包；账号存储不会随应用文件跨设备迁移；
- GitHub Actions：同步整个稳定 tag，并确认 workflow、源码和 `uv.lock` 来自同一版本。

## 下一步

- 长期 Linux 主机：[服务器部署](../DEPLOYMENT.md)
- Windows 桌面预览版：[独立 EXE 使用与构建](windows-desktop.md)
- Windows Python 脚本：[部署与迁移](windows.md)
- macOS 手动桌面预览：[构建与钥匙串](macos-desktop.md)
- Android 手动预览：[安装、验证码与账号保存](android-client.md)
- 无服务器方案：[GitHub Actions](../GITHUB_ACTIONS.md)
- 命令和环境变量：[CLI 与状态码参考](cli-reference.md)
- 异常排查：[故障排查](troubleshooting.md)
