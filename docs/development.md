# 开发、CI 与发布

本页面向本仓库的贡献者与维护者，说明当前 `main` 的代码边界、可执行检查与交付渠道。使用说明从 [文档中心](README.md) 开始；提交要求见 [贡献指南](../CONTRIBUTING.md)。所有验证示例均应使用自己审阅过的代码，不要把真实凭据注入构建、单元测试或 PR 工作流。

## 1. 版本与分发边界

当前源码以 `v2.0.0` 为发布目标：

- `pyproject.toml`、`swu_checkin.__version__` 与 `uv.lock` 的项目版本为 `2.0.0`；变更摘要与交付目标见 [v2.0.0 发布说明](releases/v2.0.0.md)
- 旧 [`v1.1.5`](https://github.com/Maximora-byte/swu-checkin/releases/tag/v1.1.5) 只提供 Python `.whl` 与 `.tar.gz`，不含桌面功能
- Windows desktop preview 来自 [PR #33](https://github.com/Maximora-byte/swu-checkin/pull/33)，合并 commit 为 `e900fd17d3c0d4325c666b1fc573cf33015911ef`；版本准备不会替代该发布 commit 自身的验证
- 实际发布状态与可下载资产以 [GitHub Releases](https://github.com/Maximora-byte/swu-checkin/releases) 为准。版本号或源码说明不证明已经完成发布；Release 应记录 tag commit、对应 CI run 与资产来源
- 桌面产物仍为未签名预览版；已做 GitHub-hosted Windows Server 2022 x64 构建/安装 smoke，干净 Windows 10/11 x64 标准用户验收仍未完成

Python Release、Windows Actions artifact、源码 checkout 是不同交付物。不要把桌面预览构建描述为已签名、稳定版或已完成 Windows 10/11 全面验收。具体桌面使用、构建环境和人工验收清单见 [桌面版指南](windows-desktop.md)。

## 2. 代码结构

| 目录/模块 | 主要职责 |
| --- | --- |
| [`src/swu_checkin/cli.py`](../src/swu_checkin/cli.py) | 参数、交互、JSON stdout、退出码与本地状态展示 |
| [`service.py`](../src/swu_checkin/service.py) | probe/正式流程编排、有限重试、缓存会话恢复、提交后的服务端确认 |
| [`auth.py`](../src/swu_checkin/auth.py)、[`oauth_flow.py`](../src/swu_checkin/oauth_flow.py) | 认证与可信 OAuth/CAS 跳转验证 |
| [`client.py`](../src/swu_checkin/client.py)、[`api_models.py`](../src/swu_checkin/api_models.py) | HTTP 接口与学校响应结构校验 |
| [`models.py`](../src/swu_checkin/models.py)、[`status.py`](../src/swu_checkin/status.py) | schema v1 JSON、固定状态名称/消息与模式对应关系 |
| [`formal_execution.py`](../src/swu_checkin/formal_execution.py)、[`runtime_lock.py`](../src/swu_checkin/runtime_lock.py) | CLI 与桌面正式签到共享的跨进程锁边界 |
| [`token_store.py`](../src/swu_checkin/token_store.py)、[`storage.py`](../src/swu_checkin/storage.py) | 受限认证缓存与非敏感运行状态，二者不能混为一谈 |
| [`desktop.py`](../src/swu_checkin/desktop.py)、[`desktop_backend.py`](../src/swu_checkin/desktop_backend.py)、[`desktop_errors.py`](../src/swu_checkin/desktop_errors.py) | 中文 GUI、DPAPI/计划任务/运行入口与固定安全错误文案 |
| [`actions_result.py`](../src/swu_checkin/actions_result.py)、[`notify.py`](../src/swu_checkin/notify.py) | Actions JSON 适配、可选 OpenClaw Telegram 日汇总 |
| [`deploy/`](../deploy/) | Linux units、凭据录入器、Unix 权限验证 |
| [`scripts/windows/`](../scripts/windows/)、[`packaging/windows/`](../packaging/windows/) | 旧式 Python 部署脚本、桌面冻结构建与 Inno Setup 安装包 |
| [`scripts/release/`](../scripts/release/)、[`tests/`](../tests/) | Python 发布校验、单元/集成与安全回归测试 |

业务修改优先落在共享服务与模型层，不应在 GUI、Actions 或计划任务中复制一套弱化校验的签到实现。正式提交使用学校返回的宿舍信息；程序不测量真实 GPS，不证明本人在寝。不得新增位置伪造、反检测、认证绕过或敏感日志，安全约束见 [安全模型](security.md)。

### 手工验证码前端接入

共享认证入口 `authenticate_token(username, password, timeout, *, captcha_provider=None)` 支持可选的同步回调 `Callable[[bytes], str | None]`；兼容入口 `get_token` 接受相同的关键字参数，失败仍返回空字符串。可用 `functools.partial(authenticate_token, captcha_provider=callback)` 作为现有 `CheckinService(token_provider=...)` 的认证函数，不应在前端复制 OAuth/CAS 流程。

- 回调只收到当前验证码图片的原始 bytes；图片由核心通过当前登录的同一个 `requests.Session` 获取，回调不接收账号、密码、cookie 或认证 URL
- 回调返回至少 3 位 ASCII 字母/数字答案；返回 `None` 表示取消。空值、无效答案、空图片与回调异常（包括 UI 超时）均以 `CAPTCHA_FAILED` 终止本次认证，不提交登录、不回退到 OCR，也不触发服务层完整登录重试
- 回调在认证调用线程同步执行。前端必须在工作线程调用认证，并自行限制等待用户输入的时间、处理关闭/取消与释放图片；网络 `timeout` 不会中断同步 UI 回调
- 仅服务端明确拒绝验证码才重新获取图片并调用回调；仍使用原登录会话和服务端发现的表单，最多提交 3 次。网络错误、账号密码拒绝、无 ticket 或不可信跳转不会在此循环中重新提示。服务层既有网络重试策略不变，新完整尝试必须重新发现登录流程和获取图片
- 回调不改变可信 HTTPS 主机、跳转、state、ticket、响应结构或正式签到权限边界。图片和答案不得写入日志、磁盘或诊断报告
- 未提供回调时 CLI/Windows desktop 仍使用既有 OCR 和有限重试。`ddddocr`、Pillow 及其 ONNX 依赖仅在使用 OCR 时导入；生产依赖声明和锁文件未变，手工前端需自行配置其平台打包依赖

这些是前端接入接口，并非 Android UI、后台签到或新发布渠道；新增前端还必须独立验证 UI 取消、重复触发、凭据存储与平台生命周期。

## 3. 本地开发与离线业务检查

从仓库根目录运行。CI 使用 uv **0.12.15** 和 Python **3.13**；桌面构建脚本会强制检查 uv 版本。安装 Python/依赖可能联网，但下面的测试不应登录学校账号或提交签到。

```bash
uv python install 3.13
uv sync --locked --all-groups --python 3.13
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src/swu_checkin
uv lock --check
```

`--locked` 在项目与锁文件不一致时失败，不会替你更新依赖。变更依赖应作为单独、可审查的修改同时更新 `pyproject.toml` 和 `uv.lock`。不要为了通过文档或功能 PR 顺便升级生产依赖。

无网络业务 smoke 入口：

```bash
uv run --locked swu-checkin --help
uv run --locked swu-checkin status --help
```

`setup`、`doctor`、`probe` 是不提交签到的在线诊断，不属于离线测试；`run`、无子命令兼容入口和 `--scheduled` 可能正式提交，不应用作构建 smoke。JSON 适配器、服务与 GUI 状态机测试应使用合成数据或模拟依赖。

### Windows 检查

基础 PowerShell 脚本检查（可在已安装 PowerShell 7 的 Linux 上运行）：

```powershell
./tests/windows/test_windows_scripts.ps1
```

在一次性 Windows 测试环境，分别用 Windows PowerShell 5.1 与 PowerShell 7 运行：

```powershell
.\tests\windows\test_windows_scripts.ps1 -WindowsIntegration
uv run --locked pytest -q .\tests\test_runtime_lock.py
uv run --locked python .\tests\windows\python_dpapi_smoke.py
```

`-WindowsIntegration` 会用随机测试值验证 DPAPI，并注册、查询、清理一个 `SWUCheckin-CI-<随机值>` 临时任务；任务只运行 `exit 0`，不含真实账号、不调用学校接口。它不是完全只读检查，不应在不允许创建临时任务的环境中运行。Linux mock 通过不能替代 Windows DPAPI、跨进程锁或任务计划程序集成验证。

### workflow、systemd 与权限检查

Linux CI 还执行以下类型检查：

- actionlint `v1.7.7` 校验所有 `.github/workflows/*.yml`
- `systemd-analyze verify` 校验 service/timer，需要预先存在专用用户、占位可执行文件和环境文件，完整准备步骤见 [`ci.yml`](../.github/workflows/ci.yml)
- `deploy/verify-state-permissions.sh` 需要 root、运行中的 systemd 和 `swu-checkin` 用户；它在临时目录验证状态 `0640`、同组读取/写通知标记、无关用户读取被拒绝
- 导出锁定的生产依赖，再运行 `pip-audit`；漏洞数据库查询需要网络

```bash
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.7 .github/workflows/*.yml
uv export --locked --no-dev --no-emit-project --format requirements-txt \
  | uv run --locked pip-audit -r /dev/stdin
```

不要在生产机上照搬 CI 的占位文件准备步骤，它会覆盖安装路径。systemd/DAC 检查应在一次性 Linux VM/runner 运行；无 systemd 的容器不能声称已完成该集成验证。

## 4. 普通 CI 的门禁

[`ci.yml`](../.github/workflows/ci.yml) 在所有 PR 和 `main` push 触发，没有文档路径排除规则。默认权限为 `contents: read`，不需要学校账号 Secrets。

| job | 执行内容 |
| --- | --- |
| `linux-quality`（Ubuntu 24.04） | 全部 pytest、Ruff lint/format、mypy、PowerShell 基础检查、actionlint、systemd unit 校验、真实 Unix DAC 检查与锁定生产依赖审计 |
| `windows-quality`（windows-latest） | PowerShell 5.1/7 集成检查；locked 非 editable 安装后临时隐藏源码，验证安装后的 CLI 可用；Windows 跨进程锁与 Python ctypes DPAPI smoke |
| `package-quality`（Ubuntu 24.04） | 构建 wheel/sdist、检查归档内容，并分别在干净环境安装和验证版本/CLI |
| `quality` | `always()` 运行并依赖以上三个 job，要求三者都为 `success`，不会把跳过或取消视作通过 |

`quality` **不包含** Windows desktop 构建 job。纯文档 PR 会运行普通 CI，但不会因文档变更自动生成新 EXE。具体是否要求某个 check 由仓库分支规则决定，不要仅凭工作流名称推断分支保护配置。

## 5. Python 打包与 Release

本地打包验证只生成与检查文件，不发布：

```bash
uv build
project_version="$(uv run --locked python scripts/release/verify_release_tag.py)"
uv run --locked python scripts/release/verify_artifacts.py \
  --expected-version "$project_version"
```

确保 `dist/` 顶层没有旧版本的 wheel/sdist；校验器要求恰好各一个，也可用 `--dist` 指定产物目录。不要盲目清空包含需要保留文件的目录。

[`verify_artifacts.py`](../scripts/release/verify_artifacts.py) 拒绝危险归档路径和已列出的私密文件/目录，分别安装 wheel 与 sdist，执行 `--help`、`status --help` 并核对项目/分发包版本。干净安装通过 `uv pip install` 解析分发包依赖，可能联网；这项检查证明包可安装，不等同于部署时按 `uv.lock` 安装，也不是完整敏感内容扫描。

[`release.yml`](../.github/workflows/release.yml) 只由推送 `v*` tag 触发：

1. `release-build-verify` 使用只读仓库权限，确认 tag commit 是 `origin/main` 的祖先；校验 tag 去掉 `v` 后与 `pyproject.toml` 版本完全相同
2. 安装 locked 开发环境，运行 pytest、Ruff、mypy 和 `uv lock --check`，再构建并验证 wheel/sdist
3. 仅上传这两类已验证分发包作为保留 1 天的中间 artifact
4. `release-publish` 才取得 `contents: write`；它不 checkout 或运行项目代码，只下载对应 artifact、核对数量，并用已存在的 tag 创建 GitHub Release、生成 notes
5. 已有同名 Release 时拒绝覆盖；该流程没有 PyPI 上传，也不上传 Windows EXE

如发布同时包含 Windows 桌面预览，需另行取得与 tag commit 一致的 Windows 构建产物，核对 `BUILD-INFO.json`、工具链与校验清单，并在发布说明中标明来源 run、未签名状态与验收限制。不要把旧版本或其他 commit 的 artifact 改名后作为新版本上传；完整 onedir 分发需保留全部资源与许可。重新封装 ZIP 时还需为上传文件计算校验值，目录内的原始清单不会自动覆盖新 ZIP。

Release 自身不会重跑普通 CI 的所有平台/systemd/DAC/漏洞审计 job。发布前仍需确认目标 commit 的普通 CI 与适用平台验证；tag 匹配和祖先检查不能替代这些证据。版本变更需保持 `pyproject.toml`、`src/swu_checkin/__init__.py` 与锁文件一致；不要移动已发布 tag 或用同名版本重新包装不同内容。

## 6. Windows desktop 构建与验收

[`windows-desktop.yml`](../.github/workflows/windows-desktop.yml) 有两个入口：

- `workflow_dispatch` 手动选择 revision
- PR 修改 `src/**`、`tests/**`、`packaging/windows/**`、`scripts/windows/build.ps1`、`scripts/windows/verify-install.ps1`、`pyproject.toml`、`uv.lock` 或该 workflow 时触发

它不在普通 push 时自动运行；只改 Markdown 的 PR 不命中这些路径。合入 `main` 也不会自动发布桌面 Release。

构建运行在 `windows-2022`，使用官方 Python 3.13.15 x64（含 Tcl/Tk）、uv 0.12.15、校验固定 SHA256 的 Inno Setup 6.7.3。`build.ps1` 建立独立构建环境，安装 locked 生产依赖与精确版本的构建工具，执行只读原生任务查询、冻结 EXE 离线自测，输出 onedir 应用、当前用户安装包、来源元数据和 SHA256 清单。

随后 `verify-install.ps1` 仅在一次性 GitHub-hosted Windows runner 运行，验证隔离安装、无参数 GUI 启动/关闭/重开、离线自测及卸载清理。不会输入账号、注册实际签到任务或执行真实签到。构建/安装验证是主机集成测试，会安装程序和写临时文件，不能在生产用户电脑上当普通单元测试运行。

成功后上传名为 `swu-checkin-windows-x64-<commit SHA>` 的 Actions artifact，保留 **14 天**。其中安装包未签名，哈希与来源信息用于核对构建，不是数字签名或可信发布证明。artifact 不存在或已过期时，选择已审阅 revision 重建，不要假设 Releases 有相同安装包。

完整产物说明、构建命令与尚未完成的标准用户验收见 [桌面版指南](windows-desktop.md)。不要为运行未签名构建而关闭系统防护或绕过安全警告，也不要把学校真实签到作为发布验收步骤。

## 7. 修改与验证记录

PR 描述应区分“已通过”“平台跳过”“因环境无法运行”和“未执行”，并记录 commit 与工作流 run。不要硬编码测试数量或把历史构建的绿色结果当成本次 revision 的验证。

文档改动至少检查仓库内相对链接、命令与当前参数、稳定 tag/`main` 的差异、只读/正式模式说明以及敏感示例。跨平台安装、任务注册、卸载、权限或发布流程改动应执行对应平台验证，并保留安全失败路径测试；不要只测成功路径。

## Android 移植验证

Android 目前仅有独立的[可行性验证工程](android-feasibility.md)，用于 Python 3.13 打包及运行环境验证；没有学校登录/签到 UI，不是已发布的手机客户端。完整 UI 需等待模拟器与真实设备门槛。

## macOS 桌面预览验证

[macOS 指南](macos-desktop.md) 说明原生 arm64/x86_64 CI、Keychain 合成测试、冻结 GUI/OCR smoke 和未公证交付限制。共享 `desktop_operations.py` 负责正式/只读服务调用与运行锁；`desktop_backend.py` 保留 Windows DPAPI/Task Scheduler，`macos_backend.py` 提供内存 token 与显式 Keychain 操作。业务核心和 CLI 不变。macOS 构建同 Windows desktop 一样是独立路径过滤工作流，不属于普通 `quality` 汇总；两个架构的成功结果须单独检查。
