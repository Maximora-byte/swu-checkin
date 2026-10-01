# Windows desktop preview（开发构建）

本页描述 `feat/windows-desktop` 的 Windows desktop preview / development build。已在 GitHub-hosted Windows Server 2022 x64 完成构建与安装冒烟测试，最新提交的验收结果见 [草稿 PR #33](https://github.com/Maximora-byte/swu-checkin/pull/33)。这不是正式发布、稳定版或 Windows 10/11 全面支持承诺。产物没有代码签名。

## 面向使用者

开发构建的分发文件为 `SWUCheckin-<版本>-win-x64-Setup.exe`。双击安装，然后从开始菜单打开 **SWU Checkin**；用户无需另装 Python、uv 或 OCR 模型。支持目标是 Windows 10/11 x64，其他架构未验收。

- 默认安装到 `%LOCALAPPDATA%\Programs\SWUCheckin`，仅当前用户可用，无需管理员权限
- 默认打开图形窗口；安装程序不会登录账号、注册计划任务或自动启动程序
- 保留现有账号认证与安全校验。请在自己的设备上输入账号信息，勿向仓库、构建日志或问题报告提交密码、验证码、token、地址或坐标
- 定时运行默认关闭。只读探测与实际打卡是不同模式；启用实际打卡前必须阅读并确认界面的说明
- 本工具使用学校寝室坐标并沿用原有 GPS/范围字段，不测量实际 GPS，不能验证人在宿舍。技术提交成功不证明申报的位置真实；本人不在寝或不符合校方规则时，不应执行正式签到
- 后台入口是 `SWUCheckin.exe --scheduled`，按已确认保存的模式运行。不要在任务参数、快捷方式或命令行传递密码/token
- 计划任务依赖 Windows 用户会话、电脑电源和网络。关机、休眠、退出登录或认证过期均可能导致任务无法运行，不能视为云端托管

升级前关闭窗口；路径保持稳定，避免计划任务引用旧目录。安装不会注册任务；卸载会尝试用系统 `schtasks.exe` 删除本程序自己的 `SWUCheckin-Desktop` 任务，任务不存在时继续卸载，不删除其他任务。建议卸载前先在窗口中关闭任务，并在卸载后检查任务计划程序，尤其是在系统策略阻止删除时。

设置与受 Windows DPAPI 保护的认证材料保存在 `%LOCALAPPDATA%\SWUCheckin`；卸载默认保留该目录。需要彻底清理时，在关闭任务并退出应用后自行删除该目录，勿将其中内容发给他人。

从旧脚本迁移时：若检测到旧 `SWUCheckin-Daily` 任务仍已注册（即使已禁用），桌面版会拒绝启用新任务，以免保留两套调度。先使用旧版管理脚本或 Windows 任务计划程序删除旧任务注册，再启用桌面任务；安装与卸载都不会改动旧任务。

## 构建环境（开发者）

请使用 Windows x64。PyInstaller 不支持从 Linux 跨平台生成 Windows 可执行文件。

1. 从 [Python 官方站点](https://www.python.org/downloads/windows/) 安装 Python 3.13 x64，包含 Tcl/Tk；CI 固定为 3.13.15
2. 安装 uv **0.12.15**，并确保 `uv` 与 `python` 在 PATH 中
3. 安装 [Inno Setup 官方 6.7.3](https://github.com/jrsoftware/issrc/releases/tag/is-6_7_3)；CI 从该官方 release 下载并校验固定 SHA256 `9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732`
4. 在此仓库执行：

```powershell
.\scripts\windows\build.ps1
# 指定本机已安装的解释器 / 编译器时：
.\scripts\windows\build.ps1 -Python 'C:\Path\Python313\python.exe' -Iscc 'C:\Path\Inno Setup 6\ISCC.exe'
```

脚本不会更改系统执行策略。若设备策略禁止脚本，请遵守设备管理规则，由有权限的开发者构建。

构建过程使用独立的 `build/windows/venv`，执行 `uv sync --locked --no-dev --no-editable`；不更新 `pyproject.toml` 或 `uv.lock`。PyInstaller 6.16.0、hooks 2025.9 及构建工具依赖使用脚本里的精确版本，仅安装到构建环境。已有生产依赖不会由构建工具重新解析。

产物使用 PyInstaller **onedir** 布局，包含 Python、Tk/Tcl、ddddocr 模型、ONNX Runtime、OpenCV、NumPy、tzdata 与 certifi 证书数据。安装包包含整个目录；便携调试时也必须保留整个 `SWUCheckin` 目录，不能只复制其中的 EXE。

## 产物、校验与来源

`dist/windows/` 包含：

- `SWUCheckin-<版本>-win-x64-Setup.exe`：当前用户安装程序
- `SWUCheckin/`：完整冻结应用，内含自己的 `SHA256SUMS.txt`
- `BUILD-INFO.json`：版本、Git commit、工作区是否脏、源码树摘要、uv.lock 摘要、Python 与全部已安装依赖版本
- `TOOLCHAIN.txt`：uv、Inno Setup 版本与源码提交时间
- `SHA256SUMS.txt`：按路径排序的文件 SHA256 清单（不包含其自身）

源文件清单由 Git 跟踪文件和未忽略的新文件组成。摘要能区分本地未提交改动，但不是数字签名或可信发布证明。打包明确保留 MIT `LICENSE`、Python 许可、各依赖分发包提供的许可/NOTICE 与元数据。对外分发前仍需审查依赖和模型许可完整性。

可用 `Get-FileHash -Algorithm SHA256 <安装包路径>` 与可信渠道提供的清单核对。构建固定依赖版本、排序清单、哈希种子及源码时间以提高可追溯性；操作系统、编译器、签名及压缩差异仍可能影响二进制，因此不声称跨机器逐字节可重现。

## CI 与离线冒烟测试

[Windows desktop 工作流](../.github/workflows/windows-desktop.yml) 支持手动 `workflow_dispatch` 和相关文件变动的 `pull_request` 触发：Windows x64 构建，运行冻结 EXE 的 `--self-test`，再生成安装包、执行隔离安装/GUI/卸载冒烟测试，并上传保留 14 天的 Actions artifact。它不在普通 push 时自动触发、不发布 Release、没有账号 secret，也不会运行真实签到或计划任务。

`--self-test` 使用合成数据检查运行时资源；构建在非零退出或 180 秒超时时失败。`scripts/windows/verify-install.ps1` 仅允许在一次性的 GitHub-hosted Windows runner 运行：先确认不存在本应用的进程、任务、安装注册与开始菜单快捷方式，再将安装包静默安装到独立的 `RUNNER_TEMP` 随机目录。启动应用时使用空的隔离 `LOCALAPPDATA`，验证已安装 EXE 的离线自测、无参数启动的主窗口出现且响应、正常关闭、再次打开、再次关闭及卸载；子进程 PATH 仅包含 Windows 系统目录，并移除 Python/虚拟环境变量；验证应用不依赖 PATH 中的 Python 或 uv。最后检查安装目录没有残留文件、本次进程全部退出、空配置目录未被写入、安装注册和本应用任务均不存在。它不会注册任务、填入账号、点击提交或执行 `--scheduled`，清理仅限本次创建的进程和目录。

上述 CI 使用构建机上的隔离空配置目录，不是全新 Windows 用户，也没有卸载 runner 原有的 Python/uv。它不替代下面的干净标准用户验收，也不能证明校方接口、账号或打卡规则有效。

正式支持前仍需人工在没有 Python、uv 和开发环境的干净 Windows 10/11 x64 标准用户虚拟机验证（尚未执行）：

1. 使用新的标准用户和默认安装路径；安装不触发 UAC 提权，开始菜单双击打开 GUI，无控制台依赖；关闭后重新打开，再正常关闭
2. OCR/时区/TLS/Tk 资源加载成功，中文路径与含空格路径可用
3. 默认没有已启用的定时任务；先验收只读任务，禁止以真实打卡作为构建测试
4. 关闭/重开、重复点击、离线、认证失败与取消操作不会误触发提交
5. 升级后路径与设置正确；卸载后确认应用进程、安装目录文件、快捷方式和卸载注册均消失，仅保留明确说明的 `%LOCALAPPDATA%\SWUCheckin` 配置；卸载只删除 `SWUCheckin-Desktop`、不影响旧任务或其他任务，任务不存在时卸载仍可完成，用户设置默认保留
6. 未签名安装包可能触发 SmartScreen/安全软件提示；本项目不建议关闭系统防护或绕过安全警告，发布者应建立可信签名与分发渠道

构建实现参考：[PyInstaller 使用文档](https://pyinstaller.org/en/v6.16.0/usage.html)、[Inno Setup 非管理员安装](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm)。

新增 workflow 首次尚未进入默认分支时，GitHub 手动 dispatch 可能不可用；可在获得授权后创建 PR，由只读权限的 PR 构建生成 artifacts，或在本地 Windows 运行构建脚本。当前工作保留在草稿 PR #33；未合并、未启用自动合并、未发布 Release。

## 体积审查

最初安装包约 138 MiB，主要来自 OpenCV、OCR ONNX 模型、ONNX Runtime 和 NumPy 的本机运行库。预览构建只剔除收集的数据目录中的 tests/test/__pycache__ 和可由冻结 Python 模块提供的重复 .py 源文件；不删模型、证书、时区、许可或未经证明无用的 DLL，不修改业务依赖。最终大小以该提交的 CI artifact 为准。
