# v2.1.0 发布准备（2026-10-03）

本轮预发布工程门槛已通过，采用 **数字版本 2.1.0 + GitHub Pre-release** 发行流程。实际发布与下载状态见 [v2.1.0 发布页](https://github.com/Maximora-byte/swu-checkin/releases/tag/v2.1.0)，来源、run 与哈希以该次 tag 构建的公开清单为准。最新稳定版仍是 [v2.0.0](https://github.com/Maximora-byte/swu-checkin/releases/tag/v2.0.0)，其源码 `ccedc7b642f6391d86ba7ddfc7e42e69467c2e64` 和历史资产保持原样。Windows/macOS 保留预览声明；Android 持久签名候选单独审验，离机签名保管未完成前不公开 APK。

## 候选范围与精确来源

`pyproject.toml`、`swu_checkin.__version__` 与 `uv.lock` 为 **2.1.0**。Android 独立使用 **0.1.1-preview / versionCode=3**，release 包名为 `io.github.maximorabyte.swucheckin`，不允许调试；debug 保留 `.feasibility` 后缀和临时签名。变化与升级见 [v2.1.0 候选](v2.1.0.md)。

初次工程候选的六包验收来源为 PR #45 merge-test commit **`cf1b69eb3c9d31b17e8ce79fc4aaa406dbf93fc6`**，源码树 **`9c4c7c9928d4aa71aa7512683d38950fdb0e204d`**，记录见 [初次验收清单](v2.1.0-acceptance.json)。随后只修正 Android 环境页的旧说明，最终持久签名 APK 来源为分支 commit **`f62e76f9e3940de830d5cbaee89516e00fdbe89b`**，树 **`7679ef1fcf86227cb0f768729d96e91aefb3d9cd`**，三组各 20 项重新完整通过，见 [最终 Android 验收清单](v2.1.0-android-final-acceptance.json)。两份记录都为干净源码；不改写既有包来源或把两个候选测试数合计。

PR 的临时 merge-test commit 与合并后 main commit 可能不同。正式发行应选定 main/tag commit，由发行流程重新构建并记录自己的来源、run 和 SHA256；即使代码树相同，也不能将这些候选文件的来源改写成 main/tag commit。每次版本或依赖变化都要重新盘点许可与产物。

## 发布前必做项的处理结果

| 必做项 | 本轮处理与实际证据 | 发行操作时的要求 |
| --- | --- | --- |
| 版本与固定来源 | 三处 Python 版本一致；Android 独立版本/包名；实际包内来源核对通过 | 选定 main commit；tag 精确匹配数字版本且为 main 祖先；不移动 v2.0.0 |
| 明确 Pre-release 流程 | PR/手动只读预检已成功；同 SHA 调用所有平台；只有 tag publish 有写权限；已有 Release 拒覆 | 新 tag 运行全部成功后，使用固定发行说明、`--prerelease --latest=false` 创建预发布 |
| 分发版权材料 | Windows Portable 和两架构 `.app` 内原始许可/hash 复核通过；生产 APK 的 78 份许可资产、14 份嵌套 notice、101 个 Maven 组件和原生运行库检查通过 | 保留项目 MIT、原文、notice 和内外清单；依赖变化重新核对，不替旧包补声明 |
| 实际资产审核 | 六个用户包实际下载复核；版本、同源 commit、干净源码、内外 BUILD-INFO、producer SHA、许可和 ZIP CRC 通过；共 17 个暂存文件 | 从同一次最终 run 的暂存集交付；再次检查最后的字节哈希和 17 文件数量 |
| Android 签名与覆盖安装 | 仓库外 RSA-4096 PKCS12/DPAPI/受限 ACL；应用与测试包同证书；三组生产模拟器各 20 项、共 60 项通过；同版本覆盖后合成账号可解密 | APK 单独审核；离机保管/恢复方案完成前不公开；旧 debug 包不能覆盖迁移账号 |

数字 `2.1.0` 配合 GitHub 预发布属性满足 Windows 安装器三段数字要求，不是 Python `2.1.0rc1`。PR/手动预检不创建公开发布，不接触发行签名秘密或学校账号。实现见 [release.yml](../../.github/workflows/release.yml)，发行步骤见 [开发与发布](../development.md)。

## 实际暂存资产

[发布预检 37031347112](https://github.com/Maximora-byte/swu-checkin/actions/runs/37031347112) 已成功生成 `release-staged-cf1b69eb3c9d31b17e8ce79fc4aaa406dbf93fc6`，artifact ID **11237861712**，外层 ZIP SHA256 为 `9e79488768e2f1c00fa74331b43f6bd3a4f0dd6225e6f8e0ce6c2e8fd909014b`。`release-publish` 按设计跳过。

- Python `swu_checkin-2.1.0-py3-none-any.whl` 与 `swu_checkin-2.1.0.tar.gz`
- Windows x64 `SWUCheckin-2.1.0-win-x64-Setup.exe` 与 `SWUCheckin-2.1.0-win-x64-Portable.zip`
- macOS 15 `SWUCheckin-2.1.0-macos15-arm64-preview.zip` 与 `SWUCheckin-2.1.0-macos15-x86_64-preview.zip`

六个包加十一份来源、许可清单、项目 MIT、固定说明、`ASSET-MANIFEST.json` 和 `SHA256SUMS.txt` 共 **17 文件**，artifact 保留 14 天。Actions 外层 ZIP 与用户安装包是不同交付物。总 artifact 超出连接器 512 MiB 下载上限；本机分别下载全部 producer artifacts、核对官方外层摘要，再独立执行 stage 校验六包及附属文件，三个用户 ZIP 的 CRC 也通过。不能声称本机重新下载验证了总 ZIP。

**Android 不在 tag 自动公开集内。** CI debug 临时证书 APK 只供验证；本机持久签名 canonical APK、公开证书、内嵌来源、许可与 60 项验收报告已单独准备。尚未发布 APK，也没有把发行私钥或密码配置到 PR/CI。

## 本轮验证与限制

| 平台 | 本轮实际证据 | 保留的限制 |
| --- | --- | --- |
| Python/CLI | [CI 37031346637](https://github.com/Maximora-byte/swu-checkin/actions/runs/37031346637)：**1218 passed / 1 skipped**；Ruff、format、mypy、依赖审计等门禁通过；预检分别干净安装新 wheel/sdist | 完整 Linux 门禁不等于所有用户系统实机验收 |
| Windows x64 | 预检中的冻结 smoke、安装/GUI/卸载、Portable 和许可校验通过；最终 Setup/Portable 已实际下载复核 | 未签名；干净 Windows 10/11 标准用户验收未完成 |
| macOS 15 两架构 | arm64 和 Intel 原生构建、测试、合成 Keychain、冻结 GUI/OCR 及最终许可/来源审核通过 | ad-hoc 签名；无 Developer ID/公证，实体 Mac 干净用户验收未完成 |
| Android debug | 同源三组 API24/4 KB、API35/4 KB、API35/16 KB，每组七项 × 三安装状态，共 **63 项通过** | 临时证书、`.feasibility` 包名，不是公开生产 APK |
| Android release | 同一持久签名非调试 APK，在上述三组本机模拟器各 **20 项**，共 **60 项通过**；包括合成加密账号保存和覆盖后读取；138 个 ELF LOAD 与 ZIP 的 16 KB 对齐通过 | 这里的生产运行测试为 x86_64 模拟器；16 KB 真机、真实学校账号和任意跨版本迁移未验证 |

精确测试身份与 APK 哈希见 [Android 客户端](../android-client.md#011-preview-候选验证状态)。0.1.0 debug 的 vivo Android 16 / 4 KB 真机、历史本机/云端各 63 项只证明旧包，未累计为新生产包的证据。

失败保留：之前 Windows 路径检查 **31 passed / 1 failed**，随后路径修复定向 70 项通过；新完整 CI 为上表结果。macOS 首轮实际 Tk.framework 路径失败已改为读取实际链接 Tk 库并在两架构重验通过。[旧源预检 37028970415](https://github.com/Maximora-byte/swu-checkin/actions/runs/37028970415) 的 16 KB ART JIT 崩溃保留。本机初次 `cf1b69e` 生产候选的 16 KB 首次尝试又遇到输入法 `system_server` 空指针导致 `DeadSystemException`；该次失败报告保留，系统恢复后同一 APK 完整重跑 20 项通过。没有关闭 JIT、删除失败测试或把失败改记为成功。

## 签名保管与升级

Android 持久公开证书 SHA256 为 `77ad72b44323fa7917470442e21fb258b5b8bc8a367e87c83ba6fa22d08f811a`。私钥/DPAPI 密码在 `%LOCALAPPDATA%\SWUCheckin\ReleaseSigning\Android`。本轮另在仓库外的 `ReleaseSigningBackups\Android\20261003-preview-77ad72b4` 建立受限当前用户/SYSTEM 的备份，实际解密恢复并签名，匹配同一证书；没有输出私钥或密码。它只验证同电脑、同 Windows 用户恢复，**不是离机容灾或异机恢复**；维护者公开 APK 前仍须完成离机保管与恢复方案。备份、私钥和 DPAPI 密码不作为 Release 资产。

正式包与旧 debug 包可共存，账号因包名/AAD/Keystore 绑定须重输；不自动拷贝密文。通过的是同证书、同版本覆盖后的合成账号保持，不宣称旧包迁移或任意跨版本更新完成。详见 [Android 签名与迁移](../android-client.md#持久签名构建与保管)。

Windows Authenticode、macOS Developer ID/公证和真实用户环境验收仍缺失，因此保留预览。哈希清单证明完整性与所记录来源，不替代平台可信数字签名。

## 稳定版额外验收

升级为稳定版前，仍须完成所声明支持范围内的干净用户环境、平台签名、跨版本更新及真实设备验收。真实学校账号只读登录/查询需账号持有人明确授权；实际签到由本人在符合规则时主动操作，不作为自动发布测试。公共 HTTPS、合成业务、模拟器和云端 runner 不能替代这些项目。

本轮结果支持明确标记限制的 Pre-release。公开资产须由所选 main/tag 源码运行完整发布流程，交付对应实际来源和字节；本页候选验收记录不替代发布页上的该次构建清单。
