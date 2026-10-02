# Windows 免安装预览版

免安装版是现有桌面应用的完整 **onedir ZIP**：全部解压后，双击 `SWUCheckin/SWUCheckin.exe` 即可打开中文窗口，不需要安装程序、Python、uv、OCR 模型或管理员权限。它与安装版使用相同的冻结 EXE 与业务核心，未增加新的签到入口。不要只复制 EXE，也不要从压缩包预览中运行。

支持目标为 Windows 10/11 x64；当前自动化验证环境为 Windows Server 2022 x64。干净 Windows 10/11 标准用户实机、SmartScreen 和组织设备策略验收仍未完成。产物未签名；请勿关闭安全防护或绕过安全警告。

## 下载、校验与启动

1. 从本仓库 [Releases](https://github.com/Maximora-byte/swu-checkin/releases) 选择实际列出的资产，并核对来源。当前最新已发布版本为 [v2.0.0](https://github.com/Maximora-byte/swu-checkin/releases/tag/v2.0.0)；当前 `main` 中新增的明确命名 `Portable.zip` 尚未作为新 Release 资产发布。新版本条件见 [发布评估](releases/release-readiness.md)
2. 新构建文件名为 `SWUCheckin-<版本>-win-x64-Portable.zip`。Actions 下载可能还包一层 artifact ZIP：先解压外层，再完整解压这个 `Portable.zip`
3. 用 PowerShell `Get-FileHash -Algorithm SHA256 '下载目录\SWUCheckin-<版本>-win-x64-Portable.zip'` 对照同一 portable artifact 的 `*-Portable.zip.sha256`（完整分发目录的 `SHA256SUMS.txt` 也包含该 ZIP）；同时核对 `BUILD-INFO.json` 的源码 commit。哈希只验证完整性，不能替代数字签名或可信来源
4. 右键 ZIP 选择“全部解压缩”，放到当前用户可访问的本地目录，例如 `文档\SWU Checkin\`。目录可以有空格和中文
5. 双击解压目录中的 `SWUCheckin.exe`。默认仅恢复本地状态，不联网、登录、提交签到或新建计划任务。先阅读包内 `README-PORTABLE.txt`

已发布 [v2.0.0](https://github.com/Maximora-byte/swu-checkin/releases/tag/v2.0.0) 的 `SWUCheckin-2.0.0-win-x64.zip` 是完整 onedir，旧名称/内容不变，再分发须保留该 Release 单独提供的 Tcl 许可。当前源码已同步 2.1.0，候选 `SWUCheckin-2.1.0-win-x64-Portable.zip` 内附说明、来源及逐文件校验，并补齐真实 Python/Tcl/Tk、依赖和 vendor 原文；构建直接验收 ZIP 解压内容。尚无新 tag/Release，最终包仍须核对自己的 BUILD-INFO commit、版本和许可清单，不只凭文件名确认来源。

GitHub 自动生成的 `Source code (zip)` 是源码，不是免安装程序。安装程序 `*-Setup.exe`、Python wheel/sdist、Actions 外层 ZIP 与内部 `*-Portable.zip` 是不同文件。

## 什么会随文件夹移动

应用及其运行资源随整个 `SWUCheckin/` 文件夹移动。账号数据**不**随它移动：

- 配置、状态、凭据与 token cache 仍在 `%LOCALAPPDATA%\SWUCheckin`；没有新增应用目录内的明文凭据文件、`portable.ini` 或自动迁移逻辑
- 显式保存的账号和密码仍由 Windows **当前用户 DPAPI** 保护；不能承诺跨电脑、跨 Windows 用户解密。复制程序到其他用户或电脑后，应重新输入并按需保存账号
- 同一用户的安装版与免安装版共用数据目录、桌面任务名与正式签到运行锁。建议同一时间只用一份应用；不要把两份应用当作独立账号配置
- 删除 ZIP 或应用目录不会删除数据或停用已有任务。清理数据前，先关闭任务和全部应用，并确认没有仍在使用该目录的旧脚本部署

DPAPI、显式保存、只读探测、正式签到确认和错误处理均沿用[桌面版说明](windows-desktop.md)。此处“免安装”不等于凭据可便携。

## 移动、升级、删除与计划任务

只手动使用且没有启用计划任务时，关闭应用后即可移动完整目录再打开。升级请完整解压新包，不要把新 EXE 与旧 `_internal` 混用或在运行时覆盖。

如果曾明确启用 `SWUCheckin-Desktop`：任务保存启用时的 EXE **绝对路径**，不会随目录移动，也不会自动升级。

1. 移动、重命名、升级、删除目录，或在安装版/免安装版之间切换前，先从旧应用关闭每日任务，并在任务计划程序确认已删除
2. 如界面提示任务状态未知、删除失败或无法确认，停止后续移动/删除，先核实任务状态。不要把未知当作已关闭，也不要盲目再注册一份
3. 关闭所有窗口，解压新包到新的固定本地目录，确认可以打开后再删除旧目录
4. 只有需要时再明确启用任务，并核对任务动作的 EXE 路径已指向新目录

应用不会替你迁移、重新注册或自动启用任务。旧路径不存在时任务会失败；旧副本仍在时可能继续运行。关闭窗口不等于停止已授权的后台任务。移动U盘、临时解压目录或会自动清理的下载目录不适合有定时任务的使用方式。

## 构建与 CI 验证

运行现有 `scripts/windows/build.ps1`，在原安装程序与 onedir 目录之外生成 `SWUCheckin-<版本>-win-x64-Portable.zip`。打包脚本不改变安装版输入；内部只有一个 `SWUCheckin/` 根目录，包含：

- `SWUCheckin.exe` 与完整 `_internal/` 资源
- `README-PORTABLE.txt`：无需联网阅读的中文启动、存储、迁移与安全说明
- `BUILD-INFO.json`、`TOOLCHAIN.txt`：与应用内来源记录一致
- `Tcl-8.6.15-LICENSE.txt`：与固定 Tcl 版本对应的上游许可原文；其他许可仍在冻结资源中
- `_internal/build-info/LICENSE-INVENTORY.json`、`PYTHON-LICENSE.txt` 与 `licenses/`：实际 Python、Tcl/Tk、依赖和 vendor 原文及 SHA256，构建缺项会失败；版本变化需重新盘点
- `SHA256SUMS.txt`：逐文件校验（不含清单自身）；外层分发清单另含 ZIP 本身的哈希

[Windows desktop 工作流](../.github/workflows/windows-desktop.yml) 在**安装程序运行前**执行 `verify-portable.ps1`，直接验收新 ZIP。脚本仅允许运行在一次性 GitHub-hosted Windows runner：使用非管理员受限进程 token，隔离用户数据目录，移除 Python/uv/虚拟环境的路径与配置，将 ZIP 解压到含中文和空格的目录，运行冻结离线自测、默认 GUI 关闭/重开/关闭，并核对文件哈希、无新增任务/安装登记/快捷方式、无用户数据持久写入、无遗留自有进程。它不创建测试账号，也不改动现有文件、桌面或设备的 ACL/安全设置；仅为新建的 CI 测试 token 初始化当前用户与 SYSTEM 的默认对象 ACL，不增加权限组或特权，不使用学校账号或调用学校接口。

受限 token 检查是 CI 无管理员权限模拟，不是干净 Windows 10/11 实机验收。安装/卸载和无害任务专项仍独立，Portable 测试不注册任务。新版工作流支持发布预检按精确同一 SHA 调用，再由 stage 对 ZIP 内外来源/许可/哈希审核；PR/手动运行不发布。Actions artifact 保留 14 天，不等同永久 Release；候选说明见 [v2.1.0](releases/v2.1.0.md)。

## 待人工验收

请仅在自己审阅来源并且安全策略允许的设备上测试，不关闭系统防护：

- 干净 Windows 10、Windows 11 x64 标准用户，没有 Python/uv；用系统解压后直接运行
- 带下载来源标记的 ZIP、SmartScreen/杀毒策略的实际表现，中文路径和正常关闭重开
- 不启用任务时移动整个目录，再打开；确认旧数据仍只在当前用户数据目录
- 显式保存测试数据后的 DPAPI 仅当前用户可读取，以及跨用户/电脑不会被误当成可迁移凭据
- 如要测试计划任务移动/升级，先停用确认删除；不得以真实学校账号执行未授权签到

本工具沿用学校记录的寝室坐标，不测量真实 GPS、不证明本人在寝。仅在本人确实在寝且符合学校规则时执行正式签到。
