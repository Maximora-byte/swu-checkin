# SWU 查寝打卡（Maximora 独立维护版）

[![CI](https://github.com/Maximora-byte/swu-checkin/actions/workflows/ci.yml/badge.svg)](https://github.com/Maximora-byte/swu-checkin/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Maximora-byte/swu-checkin)](https://github.com/Maximora-byte/swu-checkin/releases/latest)
[![License](https://img.shields.io/github/license/Maximora-byte/swu-checkin)](LICENSE)

西南大学钉钉查寝工具，提供 Python CLI、Windows / macOS 桌面预览版、Android 手动客户端、Windows 脚本计划任务、GitHub Actions 和受限 systemd timer 部署。各入口共用认证与签到业务核心。

> [!IMPORTANT]
> 这是由 [Maximora-byte](https://github.com/Maximora-byte) 独立维护的非官方社区项目，源自 [Sorynthia/swu-checkin](https://github.com/Sorynthia/swu-checkin)。本仓库保留原项目署名与 MIT 许可证，但路线、发布和支持均由当前仓库独立负责；它不代表西南大学、钉钉或原上游作者。

## 为什么维护这个版本

- **可靠判断**：提交后回读学校接口，HTTP 200 不会被直接当作签到成功。
- **安全认证**：动态发现并严格校验 SWU OAuth/CAS 登录链，异常主机、协议和参数均 fail closed。
- **保守执行**：请假、宿舍、任务或响应结构无法安全确认时停止提交，不猜测数据。
- **只读诊断**：`setup`、`doctor`、`status` 和 `probe` 不提交签到；`probe` 不写运行状态，也不对业务阶段失效的 cache 自动恢复。
- **脱敏日志**：提交异常只记录固定分类；学校返回的未知业务码、响应正文和 message 不写入日志。
- **并发保护**：正式 CLI 与桌面签到共用跨进程非阻塞锁；同一锁域内的定时和手动运行不会同时提交。锁不协调不同机器或不同锁路径。
- **跨平台部署**：支持 GitHub Actions、Windows Task Scheduler 与 systemd timer。
- **可追溯交付**：Python 3.13、`uv.lock`、Linux/Windows CI、wheel/sdist 安装验证和依赖审计。

## Windows desktop preview（2.0.0）

桌面功能已通过 [PR #33](https://github.com/Maximora-byte/swu-checkin/pull/33) 合入 `main`：中文窗口、当前用户 DPAPI 保存、只读检测、确认后的手动签到，以及默认关闭的可选定时任务。Windows x64 安装包内置 Python 与运行所需资源，使用者无需另装 Python、uv 或 OCR 模型。

当前源码版本为 `2.0.0`；Windows 桌面产物仍是未签名预览版。发布范围与升级说明见 [v2.0.0 发布说明](docs/releases/v2.0.0.md)，实际发布状态和可下载资产以 [GitHub Releases](https://github.com/Maximora-byte/swu-checkin/releases) 为准。Windows Server 2022 x64 CI 已覆盖冻结自测、安装、GUI 关闭重开、卸载，以及独立无害计划任务的注册/查询/删除；尚未完成干净 Windows 10/11 标准用户验收。使用步骤与限制见 [桌面版与构建指南](docs/windows-desktop.md)。

本工具使用学校记录的寝室坐标，不测量实际 GPS，技术提交成功不证明人在寝。仅在本人确实在寝并符合学校规则时使用正式签到；自动模式必须单独授权，不满足条件时提前停用。

### Windows 免安装 ZIP

已有 v2.0.0 的完整 onedir ZIP 可全部解压后运行 `SWUCheckin/SWUCheckin.exe`。新的构建同时生成明确命名的 `*-win-x64-Portable.zip`，内附中文使用说明、来源信息及校验清单；无需安装程序、Python、uv 或管理员权限。免安装只涵盖程序文件，DPAPI 账号数据仍保存在当前用户目录，不承诺跨电脑迁移。下载、升级和计划任务路径注意事项见 [免安装版指南](docs/windows-portable.md)。新构建先提供 Actions 预览 artifact，实际 Release 资产以发布页为准。

## macOS desktop preview

新增 macOS 15 手动桌面预览：启动不联网、不读取账号；可显式使用系统钥匙串保存/读取/清除账号，token 仅在内存。分别构建 Apple Silicon 与 Intel `.app`，不启用后台任务。产物为 ad-hoc 签名、未 Developer ID 签名/公证的预览；以各架构成功 CI artifact 为准，尚未完成真实 Mac 干净用户验收。见 [macOS 指南与构建边界](docs/macos-desktop.md)。

## 选择运行方式

Android 0.1.0 手动预览支持校园账号登录、人工验证码、可选加密保存、只读查询与诊断，以及明确确认后的单次手动签到。启动不联网，没有后台自动签到。最低 Android 7.0，仅支持 64 位设备；调试签名安装包、使用步骤和验收范围见 [Android 客户端指南](docs/android-client.md)。

| 场景 | 推荐方式 | 特点 |
| --- | --- | --- |
| 先确认账号和接口是否可用 | [本地 CLI](docs/quickstart.md) | 最快；先 `setup` / `probe`，再决定是否正式运行 |
| 长期在线 Linux 主机 | [systemd 部署](DEPLOYMENT.md) | 时间稳定、权限隔离、双次 timer、可选 Telegram 汇总 |
| 想使用 Windows 中文窗口 | [桌面预览版](docs/windows-desktop.md) | 独立 EXE；默认不联网、不启用任务；未签名，下载以 Releases 资产为准 |
| 想使用 macOS 中文窗口 | [macOS 手动预览](docs/macos-desktop.md) | 原生分架构 .app；可选钥匙串、内存 token；无后台任务、未公证 |
| 想在 Android 手机手动使用 | [Android 手动预览](docs/android-client.md) | 人工验证码、可选密钥库加密保存、先查询再确认提交；无后台任务 |
| 已使用 Windows Python 脚本部署 | [Windows 脚本指南](docs/windows.md) | 需要 uv/Python；安装诊断成功后会启用正式定时任务 |
| 没有自己的服务器 | [GitHub Actions](GITHUB_ACTIONS.md) | 配置简单，但 cron 可能排队延迟，不保证准点 |

## 当前源码的本地验证

要求：Git、[uv](https://docs.astral.sh/uv/getting-started/installation/) 和可访问学校认证/业务接口的网络。

```bash
git clone https://github.com/Maximora-byte/swu-checkin.git
cd swu-checkin
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

`run` / `probe` / `doctor` 的环境凭据缺失时会交互询问；`setup` 总是交互输入。密码无回显，`setup` 不保存凭据。无人值守运行必须使用 GitHub Secrets、Windows DPAPI 或权限受限的 systemd 环境文件。

> [!TIP]
> 上例检出当前默认分支，不等于安装已发布版本。需要 Python 发布版时，请从 [Releases](https://github.com/Maximora-byte/swu-checkin/releases) 选择 tag，并同时使用该 tag 的代码、文档和 `uv.lock`。当前源码以 `v2.0.0` 为发布目标；旧 [v1.1.5](https://github.com/Maximora-byte/swu-checkin/releases/tag/v1.1.5) 只有 wheel/sdist，不含桌面功能。版本号本身不能证明资产已发布或通过验收，桌面构建还需核对 commit、`BUILD-INFO.json` 与校验清单。

## 常用命令

```bash
swu-checkin setup          # 交互式只读配置检查，不保存密码
swu-checkin doctor         # 7 项只读诊断，不读写 token cache
swu-checkin probe          # 登录并读取请假/学生/宿舍/任务信息，不提交
swu-checkin run            # 正式签到；有瞬时失败重试和运行锁
swu-checkin status         # 只读本地状态文件，不发网络请求
swu-checkin run --json     # 完成业务执行时输出 schema v1 JSON
swu-checkin probe --json   # probe 的 schema v1 JSON，不提交签到
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

常见诊断分类包括 `请求超时`、`连接异常`、`HTTP 503`、`业务码已返回` 和 `响应结构异常`。其中 `业务码已返回` 只表示被分类的响应含有 `code/status` 字段；项目有意不记录其原值，不能据此判断具体账号或学校端原因。JSON 模式把诊断转到 stderr；锁忙等业务前退出可能没有 JSON，完整契约见 CLI 参考。

## 安全边界

- 密码只通过交互输入或受控的环境变量、GitHub Secrets、Windows DPAPI、root-only 环境文件提供。旧 Windows 脚本的账号保存在本地配置 JSON；任何凭据都不得写入仓库、Issue、截图或日志。
- 日志不输出账号值、密码、验证码、token、ticket、OAuth state/code、完整回调 URL、宿舍地址或坐标。
- 项目使用学校接口返回的宿舍坐标并沿用现有提交字段，不测量用户实际 GPS，也不能证明本人在寝；不得将技术提交成功当作真实位置证明。不提供新增反检测或认证绕过功能。
- `probe`、`doctor`、`setup` 和 `status` 不调用签到提交接口；CLI `run`、无子命令兼容入口、桌面确认后的手动签到及已授权自动签到可进入正式流程。`probe` 会复用有效 cache，若 cache 在身份校验阶段明确失效，则可能 fresh-auth 并替换本地 cache。
- 签到提交 POST 发生超时、连接中断或 5xx 等不明确结果时，不会通过重新登录再发第二次签到提交 POST。
- 有效 cache 必须先通过账号身份校验；正式流程仅在提交前业务读取阶段明确 401/403 时清理并 fresh-auth 一次，不把任意网络错误当成 session 失效。

详见 [安全模型](docs/security.md) 和 [OAuth 登录发现说明](docs/oauth-login-discovery.md)。

## 文档导航

- [快速上手](docs/quickstart.md)：安装、首次只读验证、正式运行和升级
- [CLI 与状态码参考](docs/cli-reference.md)：命令、环境变量、JSON schema v1 和退出码
- [Windows 桌面预览版](docs/windows-desktop.md)：EXE、DPAPI、显式授权、构建与验收
- [Windows 免安装版](docs/windows-portable.md)：ZIP 解压运行、数据边界、移动与升级
- [Windows 脚本指南](docs/windows.md)：旧式 Python 部署、计划任务及迁移
- [服务器部署](DEPLOYMENT.md)：systemd、权限、timer、日志、升级与回滚
- [GitHub Actions 指南](GITHUB_ACTIONS.md)：Secrets、多账号、通知和排队延迟
- [故障排查](docs/troubleshooting.md)：状态 3/4、缓存 session、锁、Actions 和安全报告
- [安全模型](docs/security.md)：认证、TokenStore、提交安全、日志与支持边界
- [v2.0.0 发布说明](docs/releases/v2.0.0.md)：相对 v1.1.5 的变化、交付目标与已知限制
- [开发、CI 与发布](docs/development.md)：模块分工、离线验证、发布边界
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

普通 CI 的 `quality` 汇总 Linux、Windows 与 Python 包三组门禁，包括 PowerShell/DPAPI、跨进程运行锁、Actions 语法、systemd units、Unix 状态权限、wheel/sdist 安装与锁定生产依赖审计。桌面安装包使用独立的路径过滤工作流；文档-only PR 不会自动重建 EXE。详见 [开发、CI 与发布](docs/development.md)。

## 支持、署名与许可证

- 权威仓库：[Maximora-byte/swu-checkin](https://github.com/Maximora-byte/swu-checkin)
- 版本发布：[GitHub Releases](https://github.com/Maximora-byte/swu-checkin/releases)
- 问题反馈：[GitHub Issues](https://github.com/Maximora-byte/swu-checkin/issues)
- 原始项目：[Sorynthia/swu-checkin](https://github.com/Sorynthia/swu-checkin)

报告问题前请阅读 [故障排查](docs/troubleshooting.md)，并只附脱敏结构信息。当前 fork 使用 MIT License；复制或修改时必须保留许可证文本与原作者署名。

## Android 移植验证

Android 目前仅有独立的[可行性验证工程](docs/android-feasibility.md)，用于 Python 3.13 打包及运行环境验证；没有学校登录/签到 UI，不是已发布的手机客户端。完整 UI 需等待模拟器与真实设备门槛。
