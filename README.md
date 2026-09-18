# SWU 查寝打卡脚本

西南大学钉钉查寝自动打卡脚本，支持 GitHub Actions 以及受限 systemd timer 部署。

> 本仓库是 [Sorynthia/swu-checkin](https://github.com/Sorynthia/swu-checkin) 的增强维护版，保留原项目的核心签到流程和 MIT 许可证，并重点加强认证安全、结果校验、部署可靠性与可测试性。下文“上游原版”以 **2026-09-18** 的上游 `main` 为比较基准。

## 与上游原版的主要区别

| 方面 | 上游原版 | 本增强版 |
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

- **长期在线 Linux 主机：**优先使用 [systemd 部署方式](DEPLOYMENT.md)，触发时间更稳定，并提供只读 probe、凭据保护和 Telegram 汇总。
- **不维护服务器：**使用 GitHub Actions，但需接受公共 runner 可能排队延迟。
- **临时验证：**使用本地命令行运行；正式启用前建议先执行只读 probe。

### 方式一：GitHub Actions 自动签到

⚠️ **重要提示：GitHub Actions 存在严重的排队延迟问题**
- 定时任务可能延迟数分钟、数十分钟，甚至数小时才执行
- 免费账户优先级低，高峰期延迟更严重
- 无法保证准时签到，可能因延迟错过签到时间窗口
- **如对签到时间有严格要求，建议使用云服务器或本地部署**

基本配置：
1. Fork 本仓库到你的账号
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
# 设置环境变量后运行
export SWUDK_USERNAME="你的学号"
export SWUDK_PASSWORD="你的密码"
swu-checkin
```

本地交互运行时也可以直接执行 `swu-checkin`；如果未设置上述环境变量，程序会分别通过 `input()` 和 `getpass()` 安全询问账号与密码。GitHub Actions、systemd 等无人值守部署必须通过 Secrets 或受限环境文件提供凭据。

只验证登录与任务读取、不执行签到：

```bash
SWUDK_PROBE_ONLY=1 swu-checkin
```

或作为 Python 模块调用：

```python
import os

from swu_checkin import check_in

result = check_in(os.environ["SWUDK_USERNAME"], os.environ["SWUDK_PASSWORD"])
```

##### Windows PowerShell

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

## 项目结构

```
.
├── .github/
│   └── workflows/
│       └── checkin.yml       # GitHub Actions 工作流
├── src/
│   └── swu_checkin/
│       ├── __init__.py
│       ├── check_in.py       # 主打卡脚本
│       ├── get_info.py       # 信息获取模块
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
├── pyproject.toml            # 项目配置和依赖
├── uv.lock                   # 锁定依赖版本
├── README.md
├── DEPLOYMENT.md             # systemd 部署说明
└── GITHUB_ACTIONS.md         # Actions 配置指南
```

## 工作流程

1. 从可信 SWU HTTPS 入口逐跳发现并校验统一身份认证流程
2. 通过 OCR 识别验证码自动登录
3. 获取 token 和打卡任务信息
4. 检测请假状态
5. 自动填写宿舍位置信息并提交打卡

## 环境变量配置

### 自动化运行的必需配置
- `SWUDK_USERNAME` - 校园网账号（学号）
- `SWUDK_PASSWORD` - 校园网密码

本地交互运行可不设置这两个变量，程序会在启动后询问账号和密码；无人值守运行不能依赖交互输入。

### 可选配置
- `SWUDK_MAX_ATTEMPTS` - 签到失败重试次数（默认 3 次）
- `SWUDK_RETRY_DELAY` - 首次重试等待秒数，后续指数退避（默认 8 秒）
- `SWUDK_PROBE_ONLY` - 设为 `1` 时只登录并读取任务，绝不提交签到
- `SWUDK_STATUS_FILE` - 可选的非敏感运行状态文件路径，主要供 systemd 通知任务使用
- `SWUDK_DEBUG_CREDENTIALS` - 输出不含凭据值的结构化诊断信息（`1` 启用，默认关闭）

## 注意事项

### 安全性
- ⚠️ **自动化部署从环境变量、GitHub Secrets 或 root-only 环境文件读取凭据；本地运行在环境变量缺失时使用 `input()` / `getpass()` 交互输入。任何方式都不得硬编码或提交凭据**
- ⚠️ **GitHub Actions 使用 Secrets 存储敏感信息，代码不会主动打印账号或凭据值**
- ⚠️ **正常与诊断模式都不会输出密码、token、ticket、验证码、OAuth state/code 或完整回调 URL**
- ⚠️ **所有实际认证请求只发送到 allowlist 中的 SWU 官方 HTTPS 主机；精确匹配的 legacy IDM HTTP Location 仅作为服务端数据接受校验并原地升级为 HTTPS，客户端绝不向 HTTP 地址发请求；发现失败时不会回退到猜测 URL**
- ⚠️ **项目只验证并使用学校接口返回的位置数据，不提供 GPS 欺骗、反检测或绕过安全机制的功能**

认证链的可信主机、剩余固定参数和排障边界见 [OAuth 登录发现说明](docs/oauth-login-discovery.md)。服务器凭据与权限模型见 [部署文档](DEPLOYMENT.md)。

### 功能特性
- ✅ 验证码识别失败自动重试（每次登录尝试最多识别 3 次验证码）
- ✅ 登录失败自动重试（验证码错误时自动重新登录，最多 3 次）
- ✅ 网络异常、今日任务暂未生成时自动重试 3 次，打满才算失败
- ✅ 一次签到流程中复用 token、学号、宿舍信息等，避免重复请求
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

- **[swu-login](https://github.com/Sorynthia/swu-login)** - 西南大学统一身份认证独立登录模块
- **[swudk-dingtalk](https://github.com/Sorynthia/swudk-dingtalk)** - 钉钉扫码打卡前端工具

## 贡献指南

欢迎提交 Issue 和 Pull Request！请查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解详细信息。

## 引用与归属

如果你在项目中使用或参考了本代码，建议按以下方式标注：

```
基于 Sorynthia/swu-checkin 开发
GitHub: https://github.com/Sorynthia/swu-checkin
```

本项目采用 MIT 许可证，欢迎使用和修改，但请保留原作者信息。

## 许可证

MIT License
