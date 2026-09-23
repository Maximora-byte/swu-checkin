# SWU 查寝打卡（Maximora 独立维护版）

[![CI](https://github.com/Maximora-byte/swu-checkin/actions/workflows/ci.yml/badge.svg)](https://github.com/Maximora-byte/swu-checkin/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Maximora-byte/swu-checkin)](https://github.com/Maximora-byte/swu-checkin/releases/latest)
[![License](https://img.shields.io/github/license/Maximora-byte/swu-checkin)](LICENSE)

西南大学钉钉查寝自动签到脚本，提供本地 CLI、Windows 计划任务、GitHub Actions 和受限 systemd timer 部署。

> [!IMPORTANT]
> 这是由 [Maximora-byte](https://github.com/Maximora-byte) 独立维护的非官方社区项目，源自 [Sorynthia/swu-checkin](https://github.com/Sorynthia/swu-checkin)。本仓库保留原项目署名与 MIT 许可证，但路线、发布和支持均由当前仓库独立负责；它不代表西南大学、钉钉或原上游作者。

## 为什么维护这个版本

- **可靠判断**：提交后回读学校接口，HTTP 200 不会被直接当作签到成功。
- **安全认证**：动态发现并严格校验 SWU OAuth/CAS 登录链，异常主机、协议和参数均 fail closed。
- **保守执行**：请假、宿舍、任务或响应结构无法安全确认时停止提交，不猜测数据。
- **只读诊断**：`setup`、`doctor`、`status` 和 `probe` 不提交签到；`probe` 不写运行状态，也不对业务阶段失效的 cache 自动恢复。
- **脱敏日志**：提交异常只记录固定分类；学校返回的未知业务码、响应正文和 message 不写入日志。
- **并发保护**：正式 CLI 使用跨进程非阻塞锁，定时任务与手动运行不会同时提交。
- **跨平台部署**：支持 GitHub Actions、Windows Task Scheduler 与 systemd timer。
- **可复现交付**：Python 3.13、`uv.lock`、Linux/Windows CI、wheel/sdist 安装验证和依赖审计。

## 选择运行方式

| 场景 | 推荐方式 | 特点 |
| --- | --- | --- |
| 先确认账号和接口是否可用 | [本地 CLI](docs/quickstart.md) | 最快；先 `setup` / `probe`，再决定是否正式运行 |
| 长期在线 Linux 主机 | [systemd 部署](DEPLOYMENT.md) | 时间稳定、权限隔离、双次 timer、可选 Telegram 汇总 |
| Windows 日常电脑 | [Windows 安装](docs/windows.md) | DPAPI 加密密码、固定计划任务、无需常驻进程 |
| 没有自己的服务器 | [GitHub Actions](GITHUB_ACTIONS.md) | 配置简单，但 cron 可能排队延迟，不保证准点 |

## 五分钟本地验证

要求：Git、[uv](https://docs.astral.sh/uv/getting-started/installation/) 和可访问学校认证/业务接口的网络。

```bash
git clone https://github.com/Maximora-byte/swu-checkin.git
cd swu-checkin
git checkout v1.1.4
uv sync --locked --no-dev --python 3.13
```

先运行只读验证：

```bash
uv run --locked --no-dev swu-checkin setup
uv run --locked --no-dev swu-checkin probe
```

确认无误后，才执行正式签到：

```bash
uv run --locked --no-dev swu-checkin run
```

环境变量缺失时，CLI 会交互询问学号并使用无回显密码输入；`setup` 不保存密码。无人值守运行必须使用 GitHub Secrets、Windows DPAPI 或权限受限的 systemd 环境文件。

> [!TIP]
> 示例固定到已发布的 `v1.1.4`。部署前可在 [Releases](https://github.com/Maximora-byte/swu-checkin/releases) 查看最新稳定版本，并同时使用该版本的代码、文档和 `uv.lock`，不要混用不同 tag 的文件。

## 常用命令

```bash
swu-checkin setup          # 交互式只读配置检查，不保存密码
swu-checkin doctor         # 7 项只读诊断，不读写 token cache
swu-checkin probe          # 登录并读取请假/学生/宿舍/任务信息，不提交
swu-checkin run            # 正式签到；有瞬时失败重试和运行锁
swu-checkin status         # 只读本地状态文件，不发网络请求
swu-checkin run --json     # stdout 仅输出 schema v1 JSON
swu-checkin probe --json   # 只读 probe 的 schema v1 JSON
```

完整参数、环境变量、JSON 字段和退出语义见 [CLI 与状态码参考](docs/cli-reference.md)。

## 状态码

| 代码 | 含义 | 正式签到是否正常终态 |
| ---: | --- | :---: |
| 0 | 今日无签到记录 | 否 |
| 1 | 签到成功 | 是 |
| 2 | 今日已签到 | 是 |
| 3 | 账号或密码验证失败 | 否 |
| 4 | 网络错误或服务端数据异常 | 否 |
| 5 | 请假中，跳过签到 | 是 |
| 6 | probe 检测到待签到任务，未提交 | 仅 probe 正常 |

状态 `4` 是 fail-closed 聚合状态：网络、JSON、schema 或学校服务异常无法安全区分时，都不会继续猜测或提交。排查步骤见 [故障排查](docs/troubleshooting.md)。

常见 stderr 分类包括 `请求超时`、`连接异常`、`HTTP 503`、`业务码已返回` 和 `响应结构异常`。其中 `业务码已返回` 只表示响应含有非成功的 `code/status` 字段；项目有意不记录其原值，不能据此判断具体账号或学校端原因。

## 安全边界

- 凭据只能进入环境变量、GitHub Secrets、Windows DPAPI 或 root-only 环境文件；不得写入仓库、Issue、截图或日志。
- 日志不输出账号值、密码、验证码、token、ticket、OAuth state/code、完整回调 URL、宿舍地址或坐标。
- 项目只使用学校接口返回并经过校验的数据，不提供定位伪造、反检测或认证绕过。
- `probe`、`doctor`、`setup` 和 `status` 不调用签到提交接口；只有显式 `run` 或无子命令兼容入口会进入正式流程。`probe` 会复用有效 cache，若 cache 在身份校验阶段明确失效，则可能 fresh-auth 并替换本地 cache。
- POST 发生超时、连接中断或 5xx 等不明确结果时，不会通过重新登录再发第二次 POST。
- cached session 只有在提交前只读阶段出现明确 401/403 时才会被清理并 fresh-auth 一次。

详见 [安全模型](docs/security.md) 和 [OAuth 登录发现说明](docs/oauth-login-discovery.md)。

## 文档导航

- [快速上手](docs/quickstart.md)：安装、首次只读验证、正式运行和升级
- [CLI 与状态码参考](docs/cli-reference.md)：命令、环境变量、JSON schema v1 和退出码
- [Windows 使用指南](docs/windows.md)：DPAPI、计划任务、升级与卸载
- [服务器部署](DEPLOYMENT.md)：systemd、权限、timer、日志、升级与回滚
- [GitHub Actions 指南](GITHUB_ACTIONS.md)：Secrets、多账号、通知和排队延迟
- [故障排查](docs/troubleshooting.md)：状态 3/4、缓存 session、锁、Actions 和安全报告
- [安全模型](docs/security.md)：认证、TokenStore、提交安全、日志与支持边界
- [贡献指南](CONTRIBUTING.md) / [维护与归属](MAINTAINERS.md)

## 开发与质量门禁

```bash
uv sync --locked --all-groups --python 3.13
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src/swu_checkin
uv lock --check
```

CI 还会验证 Windows PowerShell/DPAPI、跨进程运行锁、GitHub Actions 语法、systemd units、Unix 状态权限、wheel/sdist clean install 与锁定生产依赖漏洞。

## 支持、署名与许可证

- 权威仓库：[Maximora-byte/swu-checkin](https://github.com/Maximora-byte/swu-checkin)
- 版本发布：[GitHub Releases](https://github.com/Maximora-byte/swu-checkin/releases)
- 问题反馈：[GitHub Issues](https://github.com/Maximora-byte/swu-checkin/issues)
- 原始项目：[Sorynthia/swu-checkin](https://github.com/Sorynthia/swu-checkin)

报告问题前请阅读 [故障排查](docs/troubleshooting.md)，并只附脱敏结构信息。当前 fork 使用 MIT License；复制或修改时必须保留许可证文本与原作者署名。
