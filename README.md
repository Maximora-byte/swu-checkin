# SWU 查寝打卡脚本（Maximora 独立维护版）

西南大学钉钉查寝自动打卡脚本，支持 GitHub Actions 以及受限 systemd timer 部署。

> [!IMPORTANT]
> **本仓库由 [Maximora-byte](https://github.com/Maximora-byte) 独立维护。** 项目源自 [Sorynthia/swu-checkin](https://github.com/Sorynthia/swu-checkin)，保留原项目署名与 MIT 许可证，但本 fork 的路线、发布、问题处理和技术支持均由本仓库独立负责。它不是西南大学、钉钉或原上游作者提供的官方服务。

本仓库的权威地址是 **[Maximora-byte/swu-checkin](https://github.com/Maximora-byte/swu-checkin)**。请将本 fork 的问题提交到[本仓库 Issues](https://github.com/Maximora-byte/swu-checkin/issues)，不要要求上游项目为本 fork 的改动提供支持。下文“上游原版”以 **2026-09-18** 的上游 `main` 为比较基准。

## 与上游原版的主要区别

| 方面 | 上游原版 | Maximora 独立维护版 |
|---|---|---|
| 统一身份认证 | 使用固定 OAuth/CAS 元数据 | 从可信 SWU HTTPS 响应逐跳发现 Redirect、state、form 和 hidden input；未知主机、降级 HTTP、异常端口或歧义参数均 fail closed |
| 特殊回调 | 依赖 `requests` 默认自动重定向和最终响应 URL | 对学校实际出现的 412 / 404 回调使用精确 host、path、port 和 ticket 规则，其他 HTTP 错误继续失败 |
| 签到成功判断 | 主要依赖请求结果 | 同时检查 HTTP、业务响应，并在提交后回读“已签到”状态，避免 HTTP 200 假成功 |
| 请假检测 | 基础记录判断 | 遍历有效记录；网络、HTTP、JSON 或字段异常时返回数据错误并停止提交，避免 fail-open |
| 时间处理 | 依赖运行环境本地时间 | 统一使用 timezone-aware `Asia/Shanghai`，本地、systemd 与 Actions 语义一致 |
| 宿舍位置数据 | 直接使用接口返回值 | 校验经纬度类型、有限性和合法范围；不增加定位伪造能力 |
| 服务器部署 | 主要依赖 Actions / 手动运行 | 提供 systemd 一次性服务、21:15/21:45 timer、只读 probe、无回显凭据录入和沙箱限制 |
| 结果通知 | Actions 失败邮件 | 额外支持服务器端每日 Telegram 汇总，状态文件采用最小 Unix 权限并防重复通知 |
| 工程质量 | 常规依赖安装 | Python 3.13 + `uv.lock` 可复现安装，配套 pytest、Ruff、actionlint、systemd 校验、Unix 权限测试和依赖漏洞审计 |

## 功能特性

### 签到与认证

- ✅ 自动获取当日任务、识别已签到状态并避免重复提交
- ✅ OCR 自动识别验证码，验证码及登录瞬时失败自动重试
- ✅ 从学校当前响应动态发现并严格校验 OAuth / CAS 登录链
- ✅ 支持本科生、研究生等身份选择，认证关键字段由程序控制
- ✅ 自动读取学校返回的宿舍、房间与位置数据，并在提交前验证坐标

### 可靠性与安全

- ✅ 请假状态 fail closed：无法确认时不继续签到
- ✅ 校验 API 业务成功信号，并在提交后回读确认最终状态
- ✅ 全链路使用北京时间语义，统一 CLI、Actions、systemd 和通知状态码
- ✅ 日志不输出账号、密码、验证码、state、code、ticket、token 或完整回调 URL
- ✅ 只读 probe 可验证登录和任务查询，绝不提交签到
- ✅ 提供 schema v1 结构化 JSON 结果，供脚本和 GitHub Actions 稳定解析

### 自动化与运维

- ✅ GitHub Actions 每晚两次执行，并支持失败邮件通知
- ✅ systemd timer 每晚两次执行，不在错过窗口后持久补跑
- ✅ 可选 Telegram 每日结果汇总，成功不会重复发送
- ✅ 锁文件可复现安装、自动测试、静态检查、systemd 校验与依赖审计

## 环境要求

- Python 3.13+
- 依赖库：requests, beautifulsoup4, Pillow, ddddocr

## 快速开始

推荐按运行环境选择：

- **长期在线 Linux 主机：**优先使用本仓库的 [systemd 部署方式](DEPLOYMENT.md)，触发时间更稳定，并提供只读 probe、凭据保护和 Telegram 汇总。
- **不维护服务器：**使用 GitHub Actions，但需接受公共 runner 可能排队延迟。
- **临时验证：**使用本地命令行运行；正式启用前建议先执行只读 probe。

### 方式一：GitHub Actions 自动签到

⚠️ **重要提示：GitHub Actions 存在严重的排队延迟问题**
- 定时任务可能延迟数分钟、数十分钟，甚至数小时才执行
- 免费账户优先级低，高峰期延迟更严重
- 无法保证准时签到，可能因延迟错过签到时间窗口
- **如对签到时间有严格要求，建议使用云服务器或本地部署**

基本配置：
1. Fork [Maximora-byte/swu-checkin](https://github.com/Maximora-byte/swu-checkin) 到你的账号
2. 在仓库 **Settings** → **Secrets** 中配置账号密码
3. 设置每天北京时间 21:15、21:45 自动签到（实际执行时间不可控）

**详细配置教程**: [GITHUB_ACTIONS.md](GITHUB_ACTIONS.md)

### 方式二：本地运行

#### 1. 安装依赖

```bash
# 使用锁文件安装生产依赖
uv sync --locked --no-dev --python 3.13
```

#### 2. 运行脚本

安装后可直接使用命令行工具：

```bash
# 首次使用：交互验证账号和只读接口，不保存密码
swu-checkin setup

# 只读诊断运行环境、认证和接口
swu-checkin doctor

# 读取已有的本地状态文件（不发网络请求）
swu-checkin status

# 明确执行正式签到
swu-checkin run

# 只读检测，不提交签到
swu-checkin probe
```

`setup` 复用现有 Service/Client 执行完整只读 preflight，验证认证、请假接口与策略、学生信息、宿舍 schema 和今日任务接口；它不会调用签到提交接口。本版本尚未实现跨平台安全 credential store，因此不会把密码写入 JSON、TOML、YAML 或其他配置文件。自动化部署仍应使用 GitHub Secrets 或权限受限的 systemd 环境文件。

`status` 不会创建状态数据：systemd 部署默认读取 `/var/lib/swu-checkin/status.json`；普通本地 `swu-checkin run` 只有在设置 `SWUDK_STATUS_FILE` 时才会记录状态。Windows 或普通本地用户若未配置该变量，看到“尚无本地运行状态”属于正常行为。

也可以先设置环境变量，避免 `run`、`probe` 和 `doctor` 重复询问凭据：

```bash
export SWUDK_USERNAME="你的学号"
export SWUDK_PASSWORD="你的密码"
swu-checkin run
```

如果未设置上述环境变量，程序会分别通过 `input()` 和 `getpass()` 安全询问账号与密码。GitHub Actions、systemd 等无人值守部署必须通过 Secrets 或受限环境文件提供凭据。

原有命令全部保持兼容：不带子命令的 `swu-checkin` 等价于正式签到，旧 `--probe` 和 JSON 参数仍可使用。

只验证登录与任务读取、不执行签到：

```bash
swu-checkin --probe
```

`SWUDK_PROBE_ONLY=1 swu-checkin` 仍保持兼容，语义与 `--probe` 相同。

需要机器可读结果时使用 JSON 模式：

```bash
swu-checkin --json
swu-checkin --probe --json
swu-checkin run --json
swu-checkin probe --json
```

JSON 模式的 stdout 只包含一个 `schema_version=1` JSON document；重试和诊断信息写入 stderr。退出码与人类可读模式完全一致。

或作为 Python 模块调用：

```python
import os

from swu_checkin import check_in

result = check_in(os.environ["SWUDK_USERNAME"], os.environ["SWUDK_PASSWORD"])
```

##### Windows PowerShell

在仓库根目录运行开箱即用安装脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows\install.ps1
```

安装器仅支持 Windows，并执行以下操作：

- 安装到 `%LOCALAPPDATA%\SWUCheckin`，使用 uv、Python 3.13 和仓库中的 `uv.lock` 创建独立虚拟环境；项目以非 editable 方式安装，不依赖后续保留原 Git checkout。
- 如果系统没有 uv，从 Astral 官方 GitHub Release 下载固定版本的 ZIP，并在解压前校验官方 SHA256；不会执行未经验证的远程脚本。
- 交互读取账号与密码；账号写入本地 JSON，密码通过 Windows DPAPI 加密保存，不写入 `.env`、JSON、任务参数或日志。
- 先执行 `swu-checkin doctor`；只有诊断成功才创建一个 `SWUCheckin-Daily` 任务，任务内包含北京时间 21:15、21:45 两个 daily trigger。两个触发共用 `IgnoreNew` 并发策略，错过触发后补跑也不会相互重叠；重复安装会更新同一任务，不会追加重复任务或 trigger。
- 任务使用当前 Windows 用户的交互登录令牌运行，因此执行时该用户需要处于登录状态。

DPAPI 密文只保证同一 Windows 用户、同一台机器可以解密。卸载时运行：

```powershell
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\SWUCheckin\uninstall.ps1"
```

卸载器只删除本项目的 `SWUCheckin-Daily` 计划任务和 `%LOCALAPPDATA%\SWUCheckin`；不会卸载或修改用户已有的 uv、Python 或其他任务。

也可以不安装任务，手动配置环境变量运行：

```powershell
$env:SWUDK_USERNAME="你的学号"
$env:SWUDK_PASSWORD="你的密码"
swu-checkin
```

##### Linux / macOS

```bash
export SWUDK_USERNAME="你的学号"
export SWUDK_PASSWORD="你的密码"
swu-checkin
```

## 返回状态码

| 状态码 | 含义 |
|-------|------|
| 0 | 今日暂无签到任务 |
| 1 | 签到成功 |
| 2 | 今日已签到，无需重复操作 |
| 3 | 账号或密码验证失败 |
| 4 | 网络错误或服务端数据异常 |
| 5 | 请假中，跳过打卡 |
| 6 | 只读 probe 检测到待签到任务，未提交 |

> 状态 `1`、`2`、`5` 是正式签到的正常终态；状态 `6` 仅由只读 probe 返回。状态 `4` 同时表示网络错误或服务端数据无法安全确认。

结构化结果示例：

```json
{"schema_version":1,"mode":"checkin","status":"success","code":1,"message":"签到成功","attempts":1,"duration_ms":1842}
```

## 项目结构

```
.
├── .github/
│   └── workflows/
│       └── checkin.yml       # GitHub Actions 工作流
├── src/
│   └── swu_checkin/
│       ├── __init__.py
│       ├── cli.py            # 参数、凭据、输出、退出码与状态记录
│       ├── models.py         # 稳定的 CheckinResult / JSON schema v1
│       ├── client.py         # 已认证 SWU 业务 HTTP API
│       ├── service.py        # 签到、probe、重试与业务决策
│       ├── storage.py        # notifier 兼容的原子状态文件
│       ├── actions_result.py # GitHub Actions JSON 严格解析器
│       ├── check_in.py       # 旧公共 API 与模块入口兼容层
│       ├── get_info.py       # OAuth 登录及旧信息 API 兼容层
│       ├── oauth_flow.py      # 可信 SWU OAuth/CAS 登录链发现与校验
│       ├── notify.py          # Telegram 每日汇总通知
│       ├── status.py         # 统一状态码语义
│       ├── time_utils.py     # Asia/Shanghai 时间处理
│       ├── verify.py         # 登录验证模块
│       ├── identity.py       # 身份选择处理
│       └── des.py            # DES 加密工具
├── deploy/
│   ├── systemd/              # 受限服务、probe 与 timers
│   └── verify-state-permissions.sh
├── docs/
│   └── oauth-login-discovery.md
├── tests/                    # 离线回归、安全与部署测试
├── MAINTAINERS.md            # 独立维护范围与支持入口
├── pyproject.toml            # 项目配置和依赖
├── uv.lock                   # 锁定依赖版本
├── README.md
├── DEPLOYMENT.md             # systemd 部署说明
└── GITHUB_ACTIONS.md         # Actions 配置指南
```

## 工作流程

```text
OAuth / get_token
       ↓
    SwuClient
       ↓
 CheckinService
       ↓
 CheckinResult
       ↓
CLI / JSON / systemd / Actions
```

`SwuClient` 只处理带 token 的 HTTP transport 与基础响应结构；`CheckinService` 负责认证失败映射、已验证 token cache、请假、任务、payload、提交后回读和重试；CLI 负责展示与状态文件。旧 `check_in()`、`probe_check_in()`、`check_in_with_retry()` 继续返回 `CheckinStatus`。

## 环境变量配置

### 自动化运行的必需配置
- `SWUDK_USERNAME` - 校园网账号（学号）
- `SWUDK_PASSWORD` - 校园网密码

本地交互运行可不设置这两个变量，程序会在启动后询问账号和密码；无人值守运行不能依赖交互输入。

### 可选配置
- `SWUDK_MAX_ATTEMPTS` - 签到失败重试次数（默认 3 次）
- `SWUDK_RETRY_DELAY` - 首次重试等待秒数，后续指数退避（默认 8 秒）
- `SWUDK_PROBE_ONLY` - 设为 `1` 时禁止正式提交：旧无子命令入口执行只读 probe，显式 `run` 会 fail closed
- `SWUDK_STATUS_FILE` - 可选的非敏感运行状态文件路径，主要供 systemd 通知任务使用
- `SWUDK_DEBUG_CREDENTIALS` - 输出不含凭据值的结构化诊断信息（`1` 启用，默认关闭）

## 注意事项

### 安全性
- ⚠️ **自动化部署从环境变量、GitHub Secrets 或 root-only 环境文件读取凭据；本地运行在环境变量缺失时使用 `input()` / `getpass()` 交互输入。任何方式都不得硬编码或提交凭据**
- ⚠️ **GitHub Actions 使用 Secrets 存储敏感信息，代码不会主动打印账号或凭据值**
- ⚠️ **正常与诊断模式都不会输出密码、token、ticket、验证码、OAuth state/code 或完整回调 URL**
- ⚠️ **token 只有通过现有学生信息接口验证后才会缓存；Windows 使用当前用户 DPAPI，Linux 使用用户 cache/state 目录中的原子 `0600` 文件。cache 不保存密码，失效 token 会先删除再重新认证**
- ⚠️ **所有实际认证请求只发送到 allowlist 中的 SWU 官方 HTTPS 主机；精确匹配的 legacy IDM HTTP Location 仅作为服务端数据接受校验并原地升级为 HTTPS，客户端绝不向 HTTP 地址发请求；发现失败时不会回退到猜测 URL**
- ⚠️ **项目只验证并使用学校接口返回的位置数据，不提供 GPS 欺骗、反检测或绕过安全机制的功能**

认证链的可信主机、剩余固定参数和排障边界见 [OAuth 登录发现说明](docs/oauth-login-discovery.md)。服务器凭据与权限模型见 [部署文档](DEPLOYMENT.md)。

### 功能特性
- ✅ 验证码识别失败自动重试（每次登录尝试最多识别 3 次验证码）
- ✅ 登录失败自动重试（验证码错误时自动重新登录，最多 3 次）
- ✅ 网络异常、今日任务暂未生成时自动重试 3 次，打满才算失败
- ✅ 跨运行复用已经验证且身份一致的 token；每次命中仍先调用学生信息接口校验，失效时回退到完整登录
- ✅ 提交成功后回读学校接口，确认状态确实变为“已签到”
- ✅ 建议在正式使用前先手动测试一次

## 质量保障

每次提交到 `main` 或发起 Pull Request 时，CI 会执行：

- 锁文件安装与完整 pytest 测试
- Ruff lint 与格式检查
- GitHub Actions 语法检查（actionlint）
- systemd service / timer 校验
- 状态文件 Unix DAC 权限实测
- 锁定生产依赖漏洞审计（pip-audit）

## 相关项目

以下链接属于原上游作者的相关项目，不代表它们由本仓库维护：

- **[swu-login](https://github.com/Sorynthia/swu-login)** - 西南大学统一身份认证独立登录模块
- **[swudk-dingtalk](https://github.com/Sorynthia/swudk-dingtalk)** - 钉钉扫码打卡前端工具

## 独立维护与支持

- **维护者：**[@Maximora-byte](https://github.com/Maximora-byte)
- **权威仓库：**[Maximora-byte/swu-checkin](https://github.com/Maximora-byte/swu-checkin)
- **问题反馈：**[GitHub Issues](https://github.com/Maximora-byte/swu-checkin/issues)
- **代码贡献：**向本仓库 `main` 提交 Pull Request，具体要求见 [CONTRIBUTING.md](CONTRIBUTING.md)
- **维护策略：**本 fork 按自身安全性、可靠性和部署需求独立演进；上游更新会按需审阅，不承诺自动或即时同步
- **支持边界：**仅支持本仓库当前 `main` 及明确发布的版本；第三方二次 fork、自行修改的签到 payload 或绕过安全机制的改动不在支持范围内

更完整的维护原则见 [MAINTAINERS.md](MAINTAINERS.md)。

## 贡献指南

欢迎向本仓库提交 Issue 和 Pull Request。请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，并确保报告中不包含账号、密码、token、ticket、验证码、位置数据或完整认证回调 URL。

## 引用与归属

本 fork 的独立维护不改变原项目的著作权与许可证要求。如果你使用或参考本代码，建议同时标注原始来源和当前维护版本：

```
原始项目: Sorynthia/swu-checkin
独立维护 fork: Maximora-byte/swu-checkin
```

本项目采用 MIT 许可证。使用、复制或修改时请保留许可证文本及原作者信息；`Maximora-byte` 是本 fork 的维护者，不声称拥有原上游代码的原始作者身份。

## 许可证

MIT License
