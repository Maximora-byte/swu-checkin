# macOS 桌面预览版

这是 macOS 手动桌面预览，不属于已发布的 [v2.0.0](https://github.com/Maximora-byte/swu-checkin/releases/tag/v2.0.0) 资产。当前源码为 2.1.0 Pre-release，macOS 构建新增版号、真实运行库/依赖版权清单和同源发布审核；两架构 ZIP 的实际下载见 [v2.1.0 发布页](https://github.com/Maximora-byte/swu-checkin/releases/tag/v2.1.0)，仍无 Developer ID 签名或公证。独立 workflow 上传限时 artifact，tag 发布流程审核两架构 ZIP 后纳入六包集。它不创建后台任务、开机启动项或修改学校接口。见 [版本说明](releases/v2.1.0.md)与 [发布准备](releases/release-readiness.md)。使用者仍须真实在寝并遵守规则；程序不测量 GPS，也不证明本人在寝。

## 支持范围与交付

- 中文 Tk 窗口复用桌面服务与原认证/签到核心，包含检测登录、只读检测、确认后的手动签到及本地状态
- 分别在 GitHub-hosted **macOS 15 arm64** 和 **macOS 15 Intel x86_64** runner 原生构建 `.app`，归档为保留符号链接的 ZIP；不是 universal2，也没有承诺 Rosetta 支持
- 声明最低 macOS 15.0；只以成功运行的具体 CI OS/架构为验证依据，没有验证旧系统，也不能由配置文件推断两种架构都构建成功
- 产物带 PyInstaller 必需的 **ad-hoc 签名**，没有 Apple Developer ID 签名或公证（notarization）。它不是可绕过 Gatekeeper 的已认证安装包
- 不提供自动签到或只读定时：`--scheduled` 在 macOS 直接拒绝，不读取账号、不访问学校
- macOS 桌面与 CLI 使用同一个 `formal_execution` 入口及默认跨进程锁。自定义了不同 `SWUDK_LOCK_FILE` 的入口不在同一锁域

在本仓库 [macOS desktop preview workflow](https://github.com/Maximora-byte/swu-checkin/actions/workflows/macos-desktop.yml)的成功运行中选取匹配架构的 artifact。新版 ZIP 为 `SWUCheckin-2.1.0-macos15-<架构>-preview.zip`，带 `BUILD-INFO.json`、`LICENSE-INVENTORY.json` 与 `SHA256SUMS.txt`；保留 14 天，可能要求登录。PR/手动默认 `github.sha`，发布预检通过 `workflow_call(ref)` 指定同一精确 SHA。检查实际 commit、版本、架构、OS 与自测记录；不存在新版成功 artifact 时，不能视为该架构已交付。

当前功能合并前的 [双架构原生构建与验证](https://github.com/Maximora-byte/swu-checkin/actions/runs/37019008388) 已通过；覆盖两个 runner 的单元测试、生产依赖审计、合成钥匙串项与冻结应用离线自测。该 PR 工作流默认检出 GitHub 的临时 merge-test commit，不能只看 PR head 或版本字符串判断产物来源；应以 `BUILD-INFO.json` 和 run 记录为准。它证明对应源码上的云端验证，不能充当未来新 tag 的发布构建或真实 Mac 验收。

下载包会受到 macOS 安全检查。若系统阻止运行，请停下并查看 [Apple 官方安全说明](https://support.apple.com/en-us/102445)。本项目不提供关闭 Gatekeeper、移除隔离属性或绕过警告的命令。正式分发前仍需要 Developer ID 签名、公证、发布审查和真实用户验收。

## 窗口操作与凭据

1. 打开只显示界面：不联网、不读取钥匙串、不自动登录或提交
2. 输入账号和密码，默认仅保留在当前进程内存。点击“检测登录”或“只读检测”才访问学校服务；只读指不提交签到，认证可能使用 HTTP POST
3. “手动签到…”每次先显示默认“否”的确认；只有本人确实在寝且符合规则才确认。重复点击与进行中关闭会被阻止
4. 如需跨次使用，主动点击“保存账号”，将账号和密码一起存入 macOS **默认文件型钥匙串**的加密 generic-password 项；使用当前应用的默认访问控制，不开放给所有应用，不启用 iCloud 同步
5. 下次启动仍不读取账号。点击“读取已存账号”才请求钥匙串访问；系统可能要求解锁或授权。取消、锁定、拒绝、损坏或未知结果都会使用固定安全提示，不会回退到明文文件
6. “清除已存账号…”确认后只删除本应用的钥匙串项，成功后清空窗口账号和内存令牌。也可由用户在 Keychain Access 管理本应用项（service `io.github.maximora-byte.swu-checkin.desktop-preview`，account `desktop-credentials-v1`）

所有认证 token **仅保存在当前窗口进程内存**，不写 macOS 文件缓存或钥匙串。读取本地状态只读 `~/Library/Application Support/SWUCheckin/status.json` 中的非敏感执行状态。删除 `.app` 不会自动删除钥匙串项或本地状态；要移除已存账号，应先在界面清除，再删除应用。

开发版/预览版更新可能改变代码签名身份，从而触发钥匙串重新授权；这不是登录成功证明。文件型钥匙串不等于 entitlement 保护的数据保护钥匙串，也不声称 Touch ID、Secure Enclave 或沙盒保护。已解锁账号下的恶意进程、管理员、调试器和运行时内存不属于该保护边界。CLI 的既有 POSIX 文件 token cache 行为不因桌面预览改变。

## 构建与离线验证

在目标架构的 macOS 15 上使用 Python **3.13.15**（带 Tcl/Tk）、uv **0.12.15**，从仓库根目录执行：

```bash
uv sync --locked --all-groups --python "$(command -v python3)"
uv run --locked pytest -q
PYTHON=python3 ./scripts/macos/build.sh
```

构建严格使用 `uv.lock`，业务核心不变。官方 ONNX Runtime 1.30.0 不提供 Intel macOS wheel；仅 Darwin/x86_64 使用最后提供 CPython 3.13 Intel wheel 的 1.23.2，其他平台仍保持现有 1.30.0。新增的该分支依赖须通过各原生 job 的生产依赖漏洞审计，不以降级掩盖不可用状态。PyInstaller 6.16.0 与构建依赖固定在脚本中。不能在 Linux/Windows 交叉构建此 `.app`；各架构的原生 OCR/numpy/ONNX Runtime 扩展必须真实可安装和加载。

新版包在 `Contents/Resources/` 保留项目 MIT，`build-info/` 保留来源、实际 CPython 3.13.15、Tcl/Tk 8.6.18、依赖分发包与包内 vendor 的原文及逐文件哈希。许可目录与对应文件必须直接可读，不能以软链接遗漏材料；缺项或哈希不一致使构建失败。资源在签名前冻结，签名后不改 `.app`。公开 ZIP 的审核再次比较包内外来源/许可字节；源码里的清单不代替实际两架构包检查。

CI 单独执行 `packaging/macos/keychain_smoke.py`，在 runner 默认钥匙串建立独立随机命名的**合成测试项**，验证新增、读取、更新、删除、缺失；不修改/解锁钥匙串，也不访问生产应用项。锁定或不可用会明确失败。此脚本仅接受一次性 GitHub macOS runner；本地构建不运行它，构建元数据如实记录该项是否执行。构建脚本随后运行冻结 `.app` 的 `--self-test`：实际创建 Tk 窗口、检查初始空账号与无后台调度、加载 OCR 模型进行合成图片推理、验证 TLS 信任资源、时区和运行锁。该冻结自测本身不访问钥匙串或学校。构建还验证 Mach-O 架构、ad-hoc 签名完整性以及拒绝 `--scheduled`。

GitHub runner 的窗口/钥匙串 smoke 不等于物理 Mac、干净标准用户或从浏览器下载的 Gatekeeper 验收。尚须人工验证：两种架构的真实设备；全新用户首次打开；系统访问取消/锁定；预览升级的钥匙串访问；关闭重开和删除流程；实际显示/中文字体/高 DPI。不要将这些未完成项目记为通过，也不要把学校账号注入 CI。

## 官方依据

- [PyInstaller 平台与构建说明](https://pyinstaller.org/en/stable/usage.html)：各操作系统分别构建
- [PyInstaller macOS 架构、签名与 Tk 事件说明](https://pyinstaller.org/en/stable/feature-notes.html)：原生扩展架构检查、ad-hoc 签名、Tk 禁用 argv emulation
- [Apple TN3137: macOS Keychains](https://developer.apple.com/documentation/technotes/tn3137-on-mac-keychains)：文件型与数据保护钥匙串边界
- [Apple SecItemAdd](https://developer.apple.com/documentation/security/secitemadd(_:_:))：密码项由钥匙串加密
- [Apple 公证说明](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
- [ONNX Runtime 1.23.2 官方 wheel](https://pypi.org/project/onnxruntime/1.23.2/#files) 与 [1.30.0](https://pypi.org/project/onnxruntime/1.30.0/#files)：Intel macOS 兼容分支依据
- [GitHub runner 架构/标签](https://github.com/actions/runner-images)：macos-15 arm64 与 macos-15-intel 分开构建
