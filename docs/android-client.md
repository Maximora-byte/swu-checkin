# Android 手动客户端（0.1.1-preview 候选）

Android 客户端已经接入仓库原有认证与签到核心。打开应用不会联网，也不会自动读取账号或签到。需要网络时由你主动点击查询、诊断或确认提交。

## 安装与使用

最低 Android 7.0 / API24，只支持 `arm64-v8a` 和 `x86_64` 的 64 位设备。截至 2026-10-03，Android 尚无公开 Release 资产；最新 v2.0.0 不包含本客户端。当前准备 **0.1.1-preview / versionCode=3**：正式包名 `io.github.maximorabyte.swucheckin`，release 变体不允许调试，使用仓库外受保护的持久签名。它仍是预览，不代表真实学校账号或全部设备已经验收。

云端 [Android 工作流](https://github.com/Maximora-byte/swu-checkin/actions/workflows/android-feasibility.yml)继续提供保留 14 天的 debug 验证 artifact。`app-debug.apk` 使用旧 `.feasibility` 包名与临时 debug 证书，版本带 `-debug`；测试 APK 只供开发验收，日常使用不用安装。持久签名候选来自 `android/app/build/outputs/apk/release/app-release.apk`，有独立的证书、来源与验收报告，不由 CI debug artifact 自动发布。核对具体包的 SHA256、内嵌来源、签名指纹与实际测试；不要混用不同运行的包。

当前新增 `assets/licenses/` 内项目 MIT、Chaquopy、实际 CPython 3.13.9、运行库、Python/Maven 依赖与 vendor 的原文/notice及受审核的逐文件清单；APK 检查器要求实际内容和哈希一致，依赖版本变化必须更新清单。旧验收 debug 包仍保留其许可缺失记录，不作为新候选分发。整体计划见 [v2.1.0 候选说明](releases/v2.1.0.md)和 [发布准备](releases/release-readiness.md)。仓库不提交 APK、私钥或密码。

1. 安装后打开 **SWU 查寝**，输入校园账号和密码。
2. 点击 **查询今日状态**。出现验证码时，输入图片中的英文字母和数字；当前验证码与同一登录会话绑定，两分钟未填写会取消。
3. 查询显示待签到后，**手动签到**才可用。点击会显示确认框；勾选本人当前在寝并符合规定，再点击 **确认提交一次**。
4. 应用重新读取身份、请假和当前任务，提交一次并查询学校状态。只有服务端确认已签到，才显示成功。网络或数据异常时先重新查询，应用不会自动重发提交。

**只读诊断**显示登录、请假数据、账号身份、宿舍数据和签到查询是否通过，不调用提交接口。已有签到、请假中或没有任务时不会重复提交。修改账号或密码后，需要重新查询。

学校返回的宿舍坐标不是真实 GPS，本应用不请求位置权限。技术提交成功不能证明本人在寝，请仅在本人在寝并符合学校规定时使用。没有自动签到、闹钟、开机广播、后台任务或通知功能。

## 账号与取消

默认不保存账号密码。勾选 **在此设备加密保存账号与密码** 后，下一次主动操作前使用 AndroidKeyStore 的 AES-256-GCM 加密保存到应用私有 `noBackupFilesDir`；随机 IV、认证标签和应用/格式绑定可检测修改。密钥不能导出，没有明文降级。令牌只保存在进程内存，并校验所属身份；账号或密码变化会清除旧会话。

**读取已保存账号**由你主动触发；**清除账号**删除密钥、加密记录和会话。关闭保存选项也会删除加密记录。账号界面禁止系统截图/录屏，不把密码或验证码写入 Activity 保存状态、日志或错误消息。旋转屏幕保留当前进程内的输入与验证码；进程结束后未保存的输入消失。

验证码可取消；离开前台会取消正在等待的登录并阻止尚未发出的提交。已经发出的网络请求无法撤回，返回后请刷新查询学校状态。取消提示不会声称提交已经撤销。

密钥丢失、存储损坏或密文被修改时停止读取，不猜测或明文保存。清除旧账号后可重新输入。密码仍需要在应用进程内用于认证，密钥库加密并不代表应用运行期间没有明文内存。[官方密钥库说明](https://developer.android.com/privacy-and-security/keystore)、[AES-GCM 参数示例](https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec)。

## 开发与验收

构建命令与运行环境见 [Android 运行环境验收](android-feasibility.md)。release 使用正式包名 `io.github.maximorabyte.swucheckin`；debug 保留 `io.github.maximorabyte.swucheckin.feasibility`，两者可以共存。新正式包不是旧 debug 包的覆盖升级；账号密文与应用 ID/AAD、设备 Keystore 绑定，不自动复制或迁移。新包首次使用须重新输入账号，确认需要后再加密保存；旧包的账号可由用户在旧应用显式清除，验证器不会擅自删除。

debug CI 每个设备在首次安装、同版本覆盖、清数据三种状态下各运行七项 instrumentation：Python 核心/存储/时区、公共 HTTPS、跨进程锁、诊断按钮与重建、加密/篡改/密钥丢失、验证码取消/超时/旧答复和完整人工操作流程，共 21 项/行。跨进程探针为 debug-only，不进入非调试 release 包。

release 验收使用与应用相同持久证书的测试包，在一次性模拟器执行六项共享生产测试 × 三安装状态，另保存合成账号、覆盖安装后验证账号仍可解密，共 20 项/行。验证器拒绝已有正式包名或测试包的设备，测试不会处理用户现有账号。这只验证同版本、同证书重装和合成账号保持，不声称旧 debug 迁移、任意跨版本迁移或异机密钥恢复已完成。

两种变体的合成登录保留原 OAuth 检查，合成业务保留原签到核心；测试数据和替代传输仅在测试 APK，客户端 APK 不含测试账号或学校接口替代实现。最终候选测试结果须按实际包记录，下面 0.1.0 的历史通过数不用于证明新包通过。

设备验收脚本只操作本应用及测试包，并在卸载/清数据前检查已保存账号；发现账号或无法确认时拒绝继续。真实手机只收集本应用报告及环境检测页，一次性模拟器才允许完整系统日志。

验收结果与包哈希记录在 PR 和交付报告。16 KB 真机与真实学校账号网络登录未验证；4 KB 真机或合成业务测试不能替代这些证据。真实学校账号验收须由账号持有人另行明确授权，不使用真实签到作为自动验收。

### 持久签名构建与保管

Windows 本机准备好官方工具链后，在仓库根目录执行：

```powershell
./scripts/android/build-signed-preview.ps1 -IncludeTests
```

首次创建 RSA-4096 PKCS12，后续复用同一密钥；不允许缺失一半的密钥/密码记录时悄悄换钥。默认位于 `%LOCALAPPDATA%\SWUCheckin\ReleaseSigning\Android`：`preview.p12` 存储加密私钥，密码由当前 Windows 用户 DPAPI 保护，专用目录 ACL 限制当前用户和 SYSTEM。脚本通过进程环境暂时传递密码，结束后清理环境；不向日志、Git 或 PR 暴露秘密。公钥证书可公开，当前持久证书 SHA256 为 `77ad72b44323fa7917470442e21fb258b5b8bc8a367e87c83ba6fa22d08f811a`；实际 APK 必须再次匹配这一指纹。

公开 APK 前，维护者应完成密钥的受保护备份与保管方案；不要只把 DPAPI 密文复制到另一电脑后假定可解密，不要把私钥、明文密码或解密脚本作为 Release 资产。本轮已在仓库外建立受限 ACL 的本机备份，并从备份恢复密码/密钥实际签名，匹配同一公开证书。这只证明同电脑、同 Windows 用户恢复；离机副本保管和异机恢复尚未验证，公开 APK 前仍须完成。发行密钥没有配置到 CI。持久证书使后续同包名更新有连续身份，但最终跨版本更新仍须独立验收；丢失密钥不能通过换一个签名继续覆盖原应用。见 [Android 官方签名说明](https://developer.android.com/studio/publish/app-signing)和 [Microsoft DPAPI](https://learn.microsoft.com/en-us/dotnet/api/system.security.cryptography.protecteddata?view=windowsdesktop-9.0)。

### 0.1.1-preview 候选验证状态

本轮候选来源为 PR #45 的精确 merge-test commit `cf1b69eb3c9d31b17e8ce79fc4aaa406dbf93fc6`，源码树 `9c4c7c9928d4aa71aa7512683d38950fdb0e204d`；后续文档补充不改写此 APK 的内嵌来源。非调试生产 APK 与同持久证书测试包已在下列环境完成验收：

| 模拟器 | 实际页大小 | 首装 / 覆盖 / 清数据共享测试 | 合成账号保存 / 覆盖后解密 | 合计 |
| --- | ---: | --- | --- | ---: |
| 官方 API24 / x86_64 | 4096 | 6 / 6 / 6 passed | 1 / 1 passed | 20 |
| 官方 API35 / x86_64 | 4096 | 6 / 6 / 6 passed | 1 / 1 passed | 20 |
| 官方 API35 / x86_64 | 16384 | 6 / 6 / 6 passed | 1 / 1 passed | 20 |

本机生产验收共 **60 项通过**，未使用真实学校账号。API35/16 KB 首次尝试的清数据阶段遇到 `system_server` 输入法服务 `AdditionalSubtypeUtils` 空指针崩溃，应用收到 `DeadSystemException`，该次仍记失败；保留原报告后，系统恢复，同一 APK 从首次安装完整重跑 20 项通过。此前云端旧源码的 ART JIT 崩溃也保留，不把一次重跑当作所有设备稳定的证明。

- 生产应用 SHA256：`c13751d0aa406b3fa516b54abe851c3167f9c64572d7b2066dbbb67e14e55937`
- 对应测试包 SHA256：`838f6b188e9e3acee60e847089404a8e2221a14e1e6d21482f8aa99a37642153`
- 公开证书 SHA256：`77ad72b44323fa7917470442e21fb258b5b8bc8a367e87c83ba6fa22d08f811a`

逐行测试身份、原报告摘要及字节哈希见 [验收清单](releases/v2.1.0-acceptance.json)。同源 [发布预检 37031347112](https://github.com/Maximora-byte/swu-checkin/actions/runs/37031347112) 的三组 debug 验证另为 63 项通过；debug 和生产包分别记录，不累计冒充同一 APK 的测试数。发行构建要求干净工作区，内嵌 `assets/BUILD-INFO.json` 记录精确 commit/tree、项目与 Android 版本、锁文件摘要；验证器反查所选源码，拒绝不一致。`verify_signed_apk.py` 还检查非 debuggable、实际许可、证书、全部 ELF LOAD 与 16 KB ZIP 对齐；signed 构建和 debug CI 核对 Maven runtime 依赖集。`verify_release_device.py` 执行上述 20 项/行，并将 instrumentation 非零退出视为失败，不因打印 OK 忽略。尚未公开发布 APK。

### 2026-10-02 功能版验收记录

[PR #38](https://github.com/Maximora-byte/swu-checkin/pull/38) 已合并，`main` commit `783932b84437a8e3c2509f24cbb7aa28fec40250` 与验收源码树一致。本机与云端使用各自记录的 APK，业务流程只使用合成认证/学校传输；公共 HTTPS 是实际网络检查。

| 环境 | 实际页大小 | 七项测试 × 三种安装状态 |
| --- | ---: | ---: |
| vivo X200 Pro，Android 16 / API36，arm64-v8a | 4096 | 21 passed |
| 本机官方 API24，x86_64 | 4096 | 21 passed |
| 本机官方 API35，x86_64，小屏 320×640 / 160 dpi | 16384 | 21 passed |
| 云端官方 API24，x86_64 | 4096 | 21 passed |
| 云端官方 API35，x86_64 | 4096 | 21 passed |
| 云端官方 API35，x86_64 | 16384 | 21 passed |

本机共 63 项，[云端运行 37019008427](https://github.com/Maximora-byte/swu-checkin/actions/runs/37019008427) 共 63 项；主机 Android 回归 40 passed。lint 为 0 errors / 6 版本建议 warnings，两个 APK 通过 16 KB zipalign，138 个 ELF 库的 LOAD 对齐通过。云端 16 KB 初次运行的系统桌面 ANR 遮住界面验收，整项仍记为失败；保留证据后，同一包完整重跑通过。历史失败没有改写为成功，详见 PR。

- 本机应用 SHA256：`7f677a5fedc7193cbad5c2032dbca17d0d0331229ce6a9e6e65389c8881c3050`
- 本机测试包 SHA256：`35b0ce173dcdce79b57a21e67a9f824532e74176bae770ed9ee2bd1bd86dd99c`
- 云端应用 SHA256：`8e45db8ff150da14284deb9dfaeb98b6afff7be68c9276ef0ce961bff6a579b0`
- 云端测试包 SHA256：`c4bdbeef16ff3d02156b795a1447bb9499dd77bf95e463ceb10bffbad26bf741`

这些哈希只适用于历史 0.1.0-manual / `.feasibility` debug 构建；独立构建因工具链和临时签名可能不同。其许可缺失曾作为发布阻塞记录，新的许可与持久签名不能改变旧文件内容。真实学校账号登录/实际签到、16 KB 真机和公开签名发布仍无验收证据。
