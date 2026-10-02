# v2.1.0 发布准备（2026-10-02）

本轮已经实现下一版的版本同步、只读预检、原生资产审核、许可收集和 Android 持久签名路线，准备 **数字版本 2.1.0 + GitHub Pre-release 标记**。当前只做发布准备，**未创建 v2.1.0 tag 或 Release**。最新公开版本仍是 [v2.0.0](https://github.com/Maximora-byte/swu-checkin/releases/tag/v2.0.0)，其源码 `ccedc7b642f6391d86ba7ddfc7e42e69467c2e64` 和历史资产保持原样。

## 候选范围与来源

`pyproject.toml`、`swu_checkin.__version__` 与 `uv.lock` 已同步为 **2.1.0**。Android 独立使用 **0.1.1-preview / versionCode=3**，release 包名为 `io.github.maximorabyte.swucheckin`；debug 保留 `.feasibility` 后缀和临时签名。说明见 [v2.1.0 候选](v2.1.0.md)，历史发行见 [v2.0.0](v2.0.0.md)。

候选包含 v2.0.0 后已合入的依赖/安全检查、Actions 执行结果门禁、人工验证码接缝、macOS 手动预览、Windows Portable 和 Android 手动客户端，并新增本轮发布准备。CLI 状态码和 JSON `schema_version=1` 沿用；各前端仍共享原 OAuth/CAS、身份/请假/任务校验与提交回查，不增加定位证明或后台手机签到。

最终发行 commit 尚需在变更合入 main 后选定。PR 构建使用同一 `github.sha` 的临时 merge-test commit；即使其树与合并后 main 相同，也不能把产物来源改写成 main commit。正式发行须从所选 main/tag commit 重建或重新运行，记录 `SOURCE-INFO.json` / `BUILD-INFO.json` / APK 内嵌来源、测试 run 与实际哈希。

## 发布前必做项的处理状态

| 必做项 | 已实现 | 最终发行前仍须核对 |
| --- | --- | --- |
| 版本与固定来源 | 三处 Python 版本为 2.1.0；Android 有独立版本/包名；tag 校验要求数字版本精确匹配，已有 Release 拒绝覆盖 | 合入后选定 main commit，确认普通 CI 和该 commit 的全部最终产物；不移动 v2.0.0 |
| 明确 Pre-release 流程 | PR/手动只读 dry-run；同 SHA 调用四平台；tag 需在 main、质量和 stage 全成功；固定说明、`--prerelease --latest=false`；只有 publish 有写权限 | 新流程的实际云端 dry-run、actionlint 和全部平台/stage 结果，不用旧 CI 代替 |
| 分发版权材料 | Android 新增项目/Chaquopy/实际 Python/原生库/Maven/Python 依赖/vendor 原文与受审核清单；桌面新增真实 CPython、Tcl/Tk 和包内 vendor 原文及逐文件清单 | 最终 APK/Portable/两架构 `.app` 内实际字节与许可 SHA；版本或依赖变更后重新盘点 |
| 最终资产审核 | stage 校验版本、同源 commit、干净源码、内外 BUILD-INFO、producer SHA、项目 MIT、每项许可哈希；旧包重命名、篡改或缺失均失败 | 取得此次成功构建的实际用户包与最终 SHA；人工复核来源/签名/限制，保留原始失败和报告 |
| Android 签名/升级路线 | 仓库外持久 RSA-4096 PKCS12，当前 Windows 用户 DPAPI 密码与受限 ACL；非调试 canonical 包；同证书 release 测试与合成账号覆盖检查 | 最终生产包 20 项/行模拟器验收；公开前维护者完成受保护备份/保管，异机恢复和真实跨版本迁移尚未验证 |

数字 `2.1.0` 配合 GitHub 的预发布属性，继续满足 Windows 安装器三段数字要求；不是 Python `2.1.0rc1`。PR/手动预检不触发公开发布，不接触发行签名秘密或学校账号。[GitHub CLI 参数](https://cli.github.com/manual/gh_release_create)与实际实现见 [release.yml](../../.github/workflows/release.yml)。

## 拟暂存的自动发布资产

发布预检只收集真实用户包，不把 Actions 外层容器 ZIP 当安装包：

- Python `swu_checkin-2.1.0-py3-none-any.whl` 与 `swu_checkin-2.1.0.tar.gz`
- Windows x64 `SWUCheckin-2.1.0-win-x64-Setup.exe` 与 `SWUCheckin-2.1.0-win-x64-Portable.zip`
- macOS 15 `SWUCheckin-2.1.0-macos15-arm64-preview.zip` 与 `SWUCheckin-2.1.0-macos15-x86_64-preview.zip`

这六个包连同十一份来源、许可清单、项目 MIT、固定说明、`ASSET-MANIFEST.json` 和 `SHA256SUMS.txt` 组成 `release-staged-<SHA>`，保留 14 天。当前未断言最终暂存已经成功；下载状态以对应 run 为准。将来 tag job 只下载同一次运行的已审核暂存集，重验最终字节，再拒覆创建 Pre-release。

**Android 不在自动公开资产内。** CI 临时 debug 证书 APK 仅供验证；本机持久签名的 canonical APK、公开证书、内嵌来源、许可与验收报告单独准备审核。暂存清单明确记录 Android omission。尚未发布 APK，也没有配置受保护发行密钥到 CI。

## 已有证据与本轮待验

| 平台 | 历史证据 | 本轮变化后的状态与限制 |
| --- | --- | --- |
| Python/CLI | PR #38 质量 CI 1142 passed / 1 skipped；[合并后 CI](https://github.com/Maximora-byte/swu-checkin/actions/runs/37020944703)成功 | 已同步版本并修复归档安全兼容；新 wheel/sdist、完整 CI 与发布 dry-run 待对应报告 |
| Windows | [历史构建](https://github.com/Maximora-byte/swu-checkin/actions/runs/37019007437)覆盖冻结、Portable、安装/GUI/卸载 | 新版来源/许可与可复用构建待验；仍未签名，缺少干净 Windows 10/11 标准用户验收 |
| macOS 15 两架构 | [历史双架构 CI](https://github.com/Maximora-byte/swu-checkin/actions/runs/37019008388)含 Keychain 合成项与冻结 smoke | 新版许可与版号 ZIP 待双架构结果；仍 ad-hoc 签名、未 Developer ID/公证，缺少实体 Mac 用户验收 |
| Android | 0.1.0 debug 本机 63 项与[云端三组 63 项](https://github.com/Maximora-byte/swu-checkin/actions/runs/37019008427)，含 vivo Android 16 / 4 KB 真机 | 0.1.1-preview 新包名、许可与持久签名需独立实际验收；真实学校账号/签到、16 KB 真机、旧包迁移未验证 |

历史 APK 哈希、各测试身份、页大小、失败与重跑见 [Android 客户端](../android-client.md)和 [环境验收](../android-feasibility.md)。历史通过数不累计冒充新 APK 的证据；4 KB 手机不代表 16 KB 实体手机通过。

之前 Windows 发布/部署定向检查 **31 passed / 1 failed**，失败为宿主 `Path.is_absolute()` 未拒绝 `/absolute/path`；这个原始结果保留。现改为独立的 POSIX/Windows 路径判断，并覆盖盘符、UNC、反斜杠、遍历、ADS、NUL/控制字符、重复路径、尾随别名与归档链接；本轮发布定向 **70 passed**，格式检查通过。官方 Linux 完整质量门禁与新的实际分发包仍须独立执行，不把一个修复测试代替全平台发布验收。

## 签名保管与升级

Android 持久公开证书 SHA256：`77ad72b44323fa7917470442e21fb258b5b8bc8a367e87c83ba6fa22d08f811a`。默认私钥/DPAPI 密码放在 `%LOCALAPPDATA%\SWUCheckin\ReleaseSigning\Android`，不提交、不公开。维护者公开 APK 前应建立受保护备份和保管；本机保存不保证异机恢复已验。正式包与旧 debug 包可共存，账号因包名/AAD/Keystore 绑定须重输，不自动拷贝密文。详情见 [Android 签名与迁移](../android-client.md#持久签名构建与保管)及 [Android 官方签名说明](https://developer.android.com/studio/publish/app-signing)。

Windows Authenticode、macOS Developer ID/公证和真实用户环境验收仍缺失，继续明确预览；不提供关闭系统防护或绕过警告的安装方案。哈希清单用于完整性与来源核对，不是这些平台的可信数字签名。

## 稳定版额外验收

原生客户端保留预览标签，直至完成所声明支持范围内的干净用户环境、签名和跨版本更新验收。Android 学校账号只读登录/查询须由账号持有人明确授权；实际签到由本人在符合规则时主动操作，不作为自动发布测试。没有 16 KB 真机或物理 Mac 等设备时，明确保留限制，不能把模拟器或云端 runner 结果写成这些设备已通过。

发布说明应列出实际可下载包、确切来源/签名、验证结果与未验证项。构建成功、版本同步、文档更新和 Pre-release 流程实现均不等于 Release 已发布。
