# 新版本发布评估（2026-10-02）

当前代码适合准备下一版预发布，但还不能直接推送新 tag 并声称全平台稳定发布。建议下一版使用数字版本 **2.1.0**，首轮 GitHub Release 明确标记 **Pre-release**；这是候选方案，尚未修改版本、创建 tag 或发布资产。若先只发行 Python/CLI，可缩小资产范围，并继续把原生客户端标为源码/Actions 预览。

## 已发布版本与评估范围

最新已发布 [v2.0.0](https://github.com/Maximora-byte/swu-checkin/releases/tag/v2.0.0)，于北京时间 2026-10-02 发布，源码 commit 为 `ccedc7b642f6391d86ba7ddfc7e42e69467c2e64`。该 Release 提供 Python wheel/sdist、Windows x64 安装包和完整 onedir ZIP，以及来源、校验和 Tcl 许可材料；没有 macOS、Android 或新命名的 Portable ZIP。详细资产见 [v2.0.0 说明](v2.0.0.md)。

本评估的代码基线为 `main` commit `783932b84437a8e3c2509f24cbb7aa28fec40250`，源码树 `82beeff40646a90b3f38cecc61f5c0afa3dae680`。`pyproject.toml`、`swu_checkin.__version__` 和 `uv.lock` 仍为 `2.0.0`；Android 独立版本是 `0.1.0-manual` / `versionCode=2`。文档更新不会把历史二进制变成新版资产。

## 相对 v2.0.0 的候选变化

- [#36](https://github.com/Maximora-byte/swu-checkin/pull/36)：依赖与安全检查，加入 CodeQL、Dependency Review 和分平台依赖维护。
- [#42](https://github.com/Maximora-byte/swu-checkin/pull/42)：Actions 用执行 step 的 outcome、CLI exit code 和业务状态统一通知与最终失败判断，修复成功 JSON 配合非零退出码仍可能显示绿色的问题。
- [#37](https://github.com/Maximora-byte/swu-checkin/pull/37)：可注入验证码提供器，桌面 OCR 惰性加载，为人工验证码及纯 Python Android 依赖提供接缝；原有 OAuth/CAS 校验继续保留。
- [#39](https://github.com/Maximora-byte/swu-checkin/pull/39)：macOS 15 手动桌面、可选系统钥匙串、内存 token、Apple Silicon 与 Intel 分架构预览构建。
- [#41](https://github.com/Maximora-byte/swu-checkin/pull/41)：带使用说明、来源及校验材料的 Windows Portable ZIP；解压、离线自测和无害计划任务检查。
- [#43](https://github.com/Maximora-byte/swu-checkin/pull/43)：修正 Windows CI 的 Bash 选择，并强制执行工作流回归检查。
- [#38](https://github.com/Maximora-byte/swu-checkin/pull/38)：Android 中文手动客户端，人工验证码、AndroidKeyStore 加密保存、只读查询/诊断、确认后的单次签到，以及小屏键盘适配。

CLI 状态码和 JSON `schema_version=1` 继续沿用；新增客户端不提供实际 GPS 定位证明。正式签到需要本人在寝并符合学校规定，不能将合成测试或 HTTP 成功当作真实签到验收。

## 已有证据与平台范围

| 交付物 | 已验证 | 保留的限制 |
| --- | --- | --- |
| Python/CLI 与共享核心 | [合并后 CI](https://github.com/Maximora-byte/swu-checkin/actions/runs/37020944703) 和 [CodeQL](https://github.com/Maximora-byte/swu-checkin/actions/runs/37020944770) 成功；PR 完整质量 CI 为 1142 passed / 1 skipped | 新版本 wheel/sdist 仍须在版本同步后构建并验证安装；未使用真实学校账号作为发布测试 |
| Windows x64 | [当前代码构建](https://github.com/Maximora-byte/swu-checkin/actions/runs/37019007437) 成功，含冻结自测、Portable、安装/GUI/卸载检查 | 未签名；缺少干净 Windows 10/11 标准用户验收；此运行不是新 tag 的发布记录 |
| macOS 15 arm64 / x86_64 | [双架构 CI](https://github.com/Maximora-byte/swu-checkin/actions/runs/37019008388) 成功，含 Keychain 合成项与离线应用 smoke | ad-hoc 签名，未 Developer ID 签名/公证；缺少实体 Mac 干净用户验收和最终发行包许可盘点 |
| Android API24+ arm64-v8a / x86_64 | vivo X200 Pro Android 16 / 4 KB 真机、本机 API24 / 4 KB 与 API35 / 16 KB 模拟器共 63 项；[云端三组](https://github.com/Maximora-byte/swu-checkin/actions/runs/37019008427) 共 63 项通过 | 调试签名；真实学校账号登录/实际签到、16 KB 真机和跨版本迁移未验证；对外 APK 许可材料尚未补齐 |

上述 PR head 与云端合成合并源码的树等于评估基线；原始 commit/hash/run 均保留在 [#38](https://github.com/Maximora-byte/swu-checkin/pull/38)。这些证据说明当前代码的状态，不能替代今后版本、签名或打包方式变化后的检查。Android 详细测试身份、APK 哈希和历史失败见 [客户端指南](../android-client.md) 与 [运行环境验收](../android-feasibility.md)。

本次另在 Windows 本机运行 `tests/test_deployment.py` 与 `tests/test_release.py`，结果为 **31 passed / 1 failed**。失败是归档路径 `/absolute/path` 未被 `verify_artifacts.py` 拒绝：校验器使用宿主 `Path.is_absolute()`，Windows 对没有盘符的根路径判断与 POSIX 不同。该脚本从 v2.0.0 至评估基线未改动，官方 Release/package 门禁均在 Ubuntu 运行并能拒绝这个用例；Windows 原生构建不调用该校验器。因此它不等同于官方 Ubuntu Release 失败，但 Windows 本机归档校验尚有待修复的兼容性缺陷，不能声称所有平台发布测试全部通过。

## 发布前必须处理

1. **同步版本与固定来源**：更新 `pyproject.toml`、`src/swu_checkin/__init__.py` 和 `uv.lock`，选定已合入 `main` 的 commit。Release tag 必须精确匹配 Python 项目版本；已有 `v2.0.0` 不可覆盖。Android 使用独立版本，但也需明确本次 APK 版本、源码和签名。
2. **明确预发布流程**：现有 [release.yml](../../.github/workflows/release.yml) 在 `v*` tag 推送后直接创建普通 wheel/sdist Release，没有 `--prerelease`，不会自动上传任何原生资产。应先实现并验证 Pre-release 标记、发布说明和各平台资产审核路径，再推送 tag。GitHub 的预发布标记与 Python 版本字符串是两件独立的事，见 [官方 CLI 参数](https://cli.github.com/manual/gh_release_create)。
3. **补齐 Android 分发许可**：本机已验收 APK `7f677a…3050` 的 `assets/chaquopy/app.imy` 没有仓库 MIT LICENSE，遍历外层与全部 IMY 也未找到仓库或 Chaquo 的版权声明。部分 pip 依赖许可已经保留，但不等于全部发行材料齐全。对外分发前应保留仓库 [MIT 原文](../../LICENSE)、[Chaquopy 17 MIT 原文](https://raw.githubusercontent.com/chaquo/chaquopy/17.0.0/LICENSE.txt)，并盘点内嵌 Python 运行时及每项依赖的许可；[Python 官方许可](https://docs.python.org/3.13/license.html)不能用某个依赖的旧版 PSF 文本代替。补齐后检查最终 APK 的实际内容与哈希。macOS 许可盘点仍待执行，未断言其包内缺失。
4. **核对最终资产**：从选定 commit 构建 Python、Windows、macOS 和 Android 中实际准备交付的资产，记录版本、源码、工具链、测试、文件 SHA256 与签名指纹。选择相同源码的已验证产物时仍须核对实际文件与来源，不能只重命名旧包或把 Actions 容器 ZIP 当作用户安装包。许可、版本或签名变化后，须验证变化后的最终产物。
5. **明确签名和升级路线**：Android 跨电脑临时 debug 证书可能不同，同包名覆盖安装会失败。正式分发须使用持久受保护的签名并验证升级，私钥不得提交。Windows 签名、macOS Developer ID/公证及用户环境验收仍需准备，缺失时必须明确标注预览；不得提供关闭系统防护的安装方案。Android debug 证书不适合应用商店发布，见 [官方签名说明](https://developer.android.com/studio/publish/app-signing)。

Windows 安装器当前只接受 `major.minor.patch` 数字版本，因此 `2.1.0` 加 GitHub Pre-release 标记能沿用现有版本表达。若改用 `2.1.0rc1`，还须先协调 Python/tag 版本与 Windows 安装器的数字版本、展示版本；直接加 rc 后缀会被当前构建脚本拒绝。本评估未改动发布工作流或版本。

## 稳定版额外验收

原生客户端继续保留预览标签，直至完成所声明支持范围内的干净用户环境测试、签名与升级验证。Android 需由账号持有人明确授权真实学校账号的只读登录/查询验证；实际签到应由本人在符合规定时主动操作。16 KB 模拟器结果不代表 16 KB 实体手机已经通过；没有相应设备时须保留该限制。Windows 和 macOS 也不得用构建 runner 的测试声称真实用户电脑均已验收。

发布说明应分别列出 Python 与各原生客户端的成熟度、可下载资产和未验证项。校验清单不等于数字签名；成功构建不等于 Release 已发布；GitHub 自动提供的 Source code ZIP/tar.gz 不等于经过安装验证的 wheel/sdist 或客户端。

## 本次文档核对范围

已逐项复核仓库根目录、`docs/`、Windows 便携包使用说明与许可说明，统一当前 main、已发布 v2.0.0 和平台预览的范围。历史 v2.0.0 的功能与已知问题仍按其 tag 记录；[LICENSE](../../LICENSE) 和第三方 Tcl 许可原文保持原样。发布评估与平台指南互相引用，命令、工作流和相对链接按实际文件核对。
