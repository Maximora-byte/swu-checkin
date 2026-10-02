# Android 运行环境与历史验收（开发预览）

本文记录 Android 移植的运行环境验证和原可行性 APK 历史验收。当前源码已扩展为 [0.1.0 手动客户端](android-client.md)，支持登录、人工验证码、加密账号、只读查询和确认后的手动签到。启动不会联网；环境检测页仍不接触账号或学校服务，公共 HTTPS 检查仅访问 `https://www.python.org/robots.txt`。

截至 2026-10-02，功能版已通过 [PR #38](https://github.com/Maximora-byte/swu-checkin/pull/38) 合并；本机三组共 63 项、云端三组共 63 项验收及功能版 APK 哈希见 [客户端记录](android-client.md#2026-10-02-功能版验收记录)。没有 Android Release 资产；调试签名、分发许可、真实学校账号与 16 KB 真机的发布条件见 [新版本评估](releases/release-readiness.md)。以下四项/12 项结果明确属于旧环境 APK，不代表功能版的七项测试。

## 选型与官方依据

2026-10-02 核对官方资料：

- [Chaquopy 版本矩阵](https://chaquo.com/chaquopy/doc/current/versions.html)：固定 17.0.0，支持 Python 3.13，最低 API 24（Android 7.0）
- [Chaquopy Gradle 配置](https://chaquo.com/chaquopy/doc/current/android.html)：Python 3.12+ 只有 64 位；本 APK 固定 `arm64-v8a` 与 `x86_64`，宿主构建同样使用 Python 3.13
- [AGP 8.13 官方兼容说明](https://developer.android.com/build/releases/agp-8-13-0-release-notes)：固定 AGP 8.13.2 / Gradle 8.13 / JDK 17，compile/target SDK 36
- [Compose 编译器配置](https://developer.android.com/develop/ui/compose/setup-compose-dependencies-and-compiler)：Kotlin 与 Compose compiler plugin 同版本；这里采用可独立更新的固定兼容组合 Kotlin 2.2.21 / Compose BOM 2025.12.01，而非动态 latest

版本矩阵只是构建候选依据，不证明某台手机可运行。`minSdk=24` 不代表支持 Android 7 的 32 位手机；32 位 ABI 不在支持范围。

## 边界

- Kotlin + Jetpack Compose 提供手动客户端与独立环境检测页；Chaquopy 加载仓库原有 Python 核心，不复制签到逻辑
- Android 单独固定纯 Python 运行依赖于 [`requirements-android.txt`](../android/requirements-android.txt)，包括明确打包的 tzdata；默认桌面/CLI 依赖与 uv.lock 不变
- 不打包 ddddocr、Pillow、ONNX、OpenCV，不假设桌面原生 wheel 能在 Android 工作；核心依赖验证码提供器的惰性 OCR 接缝
- 只声明 INTERNET，无位置、后台定位、闹钟、启动广播、外部存储或通知权限；无 WorkManager/自动签到
- 禁用应用备份，测试文件位于应用 `noBackupFilesDir` 下，不写 Python 源码/解压目录
- 环境测试使用无网络锁争用函数；客户端使用同一 `RuntimeLock` 实现，合成业务测试不向学校发出请求
- 学校返回的宿舍坐标不是真实 GPS，也不能证明本人在寝；后续手动签到仍必须由用户确认本人在寝并遵守学校规定

## 构建与 CI

已安装官方 Android SDK 且已自行接受 SDK 条款的开发环境：

```bash
uv python install 3.13
export PATH="$(dirname "$(uv python find 3.13)"):$PATH"
cd android
./gradlew :app:assembleDebug :app:assembleDebugAndroidTest :app:lintDebug
./gradlew :app:connectedDebugAndroidTest
```

Gradle wrapper 与 distribution 都校验固定 SHA256。SDK 路径放本地 `android/local.properties` 或 `ANDROID_HOME`，不得提交。工作流使用 GitHub runner 已安装的官方工具和已有 SDK 许可，不自动接受新条款。较新的 x86_64 Android 在纯软件模拟下可能发生系统 watchdog/进程崩溃；CI 要求硬件加速，限定 GitHub-hosted 一次性 VM，只给当前测试用户 `/dev/kvm` 的 0600 访问权限。拒绝在自托管机器上修改设备权限，不开放世界可写权限，不修改用户电脑的虚拟化设置。

CI API24 保留 1536 MB / 2 核的轻量配置；API35 普通镜像固定 4096 MB 内存，16 KB 镜像固定 6144 MB，均为 4 核并记录配置。16 KB 官方 Google 镜像在默认 2560 MB 下曾触发 `lowmemorykiller`，前台测试进程被系统杀死；该失败必须保留系统日志并通过增加模拟器内存重新验证，不能忽略失败或降低测试要求。本机启动 API35 对应镜像也应显式传入 `-memory 4096` / `-memory 6144` 和 `-accel on`。

[`android-feasibility.yml`](../.github/workflows/android-feasibility.yml) 分别构建双 ABI debug APK、运行 Android lint、检查 APK 中的 Python/ABI，并在 API24/4 KB、API35/4 KB、API35/16 KB x86_64 模拟器执行真实 embedded Python instrumentation。API35 的实际页大小必须匹配矩阵，否则失败。当前每次安装状态执行七项测试，包括加密账号、人工验证码、手动签到确认、实际按钮点击和 Activity 重建；首次安装、同版本覆盖安装、清数据共三轮。测试公共 HTTPS 需网络，失败不会被改写为通过。模拟器安装的是 package job 的同一 APK/test APK，先核对源 commit 与两个 APK 的 SHA256，不独立重建。证据包含源码、APK hash、原始测试结果、真实界面、完整一次性模拟器系统日志；debug APK 使用临时 debug 签名，不是生产签名、Release 或自动发布。

### Windows 本机构建与明确设备验收

官方 JDK 17、Android SDK 可以独立放在项目的 `.local-tools/` 下（已忽略，不提交下载文件）。将 JDK 放在 `.local-tools/jdk17*/jdk-*`，SDK 放在 `.local-tools/android-sdk`；Python 3.13 需可执行。当前终端加载：

```powershell
. ./scripts/android/env.ps1
# 如需要使用已有下载代理，可传 -DownloadProxy http://127.0.0.1:7897
./android/gradlew.bat -p android --no-daemon :app:assembleDebug :app:assembleDebugAndroidTest :app:lintDebug
emulator -accel-check
adb devices
```

创建并启动 Google 官方 API35 普通/`google_apis_ps16k` 镜像后，使用明确的 adb serial 测试。`verify_device.py` 不选取列表中的第一台设备；API、ABI、真实页大小必须匹配，证据目录必须是新目录，避免旧的成功报告掩盖本次失败：

```powershell
python scripts/android/verify_device.py --adb "$env:ANDROID_HOME/platform-tools/adb.exe" `
  --serial emulator-5556 --api 35 --abi x86_64 --page-size 16384 `
  --apk android/app/build/outputs/apk/debug/app-debug.apk `
  --test-apk android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk `
  --evidence-dir .local-tools/evidence/api35-16k-run1 --system-logs
```

系统日志开关仅允许一次性模拟器。脚本只卸载/清除无已保存账号的测试安装，不清除整个设备；同版本覆盖安装不代表跨版本升级迁移。普通镜像应使用 `--page-size 4096`，真实 arm64 手机应使用 `--abi arm64-v8a` 并填入实测页大小。

真实手机需要解锁、保持亮屏并让验证应用留在前台；系统出现 USB 安装提示时，允许验证 APK 与测试包安装。脚本每轮会先打开验证应用，避免从后台启动页面被设备限制。Android 7 缺少 `getconf` 时读取 `/proc/self/smaps` 的真实 `KernelPageSize`；读取失败仍算失败，不假定为 4 KB。界面测试包含启动和清理阶段在内的 300 秒超时，超时仍算失败。当前客户端验收每轮七项；脚本发现已有加密账号或无法确认测试安装为空时，拒绝卸载/清数据。

### 2026-10-02 原可行性 APK 真机验收（历史）

vivo X200 Pro，Android 16 / API36，`arm64-v8a`，实际内存页大小 `4096`。修复前发现标题与状态栏重叠；按 [Compose 官方系统边距说明](https://developer.android.com/develop/ui/compose/system/insets-ui)使用安全显示区域边距，并允许页面滚动后，真机界面已确认避开系统栏。首次测试遇到前台中断和持续等待，主动停止并保留失败记录；修复版保持在前台重新验收，三种安装状态各四项、共 12 项全部通过。

覆盖 embedded Python 核心、私有存储、时区、跨进程锁及持有进程退出后的释放、校验证书的公共 HTTPS、实际按钮点击与 Activity 重建。已核对本机修复版 APK SHA256 `d8926afa3e20cbc3500d4a902caa7e0eb42c40309853d4ba474d18c6f0268d4f`；不记录手机序列号和个人信息。

同一修复版 APK 在本机官方 API24 / 4 KB 与 API35 / 16 KB x86_64 模拟器上各通过三轮、12 项测试；验收脚本相关主机回归 31 passed。云端当前结果与原始失败证据记录在 PR，不用本机结果改写云端结果。

以上 SHA256 和 12 项结果属于原可行性 APK，不能用于证明后来新增的账号界面通过。当前手动客户端须核对自己的源码、包哈希和七项测试结果；16 KB 真机、跨版本数据迁移和真实学校账号网络登录仍未验证。

## 运行环境完成门槛与待验证项

必须区分本机 Python 单元测试、APK 构建、Android 模拟器、真实设备四类证据。PR 中记录实际 commit、run 与结果；没有执行的项目保持“未验证”。

- [x] 双 ABI APK 构建与 lint 通过，APK 中确有 Python 3.13 且无桌面 OCR 依赖
- [x] API24/4 KB、API35/4 KB 和 API35/16 KB 模拟器：核心 import、tzdata、app-private 读写、统一运行锁、验证证书的 HTTPS、按钮点击及页面重建（具体本机/云端证据与各次失败见 PR）
- [x] arm64 / 4 KB 真机：以上全部检查；记录 Android 版本、ABI、页大小，不记录序列号/个人信息
- [ ] 真机 16 KB 页大小兼容性（若支持范围内），模拟器不能替代对应真机结果
- [x] Android 跨进程锁与进程被杀后的释放（debug-only 私有第二进程测试，arm64 / 4 KB 真机与模拟器均通过）
- [x] 同版本覆盖安装与清除数据后的重新启动（真机与模拟器均通过）；跨版本升级迁移仍待后续验证

Windows 可通过项目内工具链构建和验收。应用户明确要求继续到可用状态，当前范围推进到人工验证码、AndroidKeystore、中文只读诊断、任务待签/已签与确认后的单次手动签到，并独立验证新增界面；16 KB 真机没有可用设备，继续明确保留未验证，不宣称全部设备兼容或生产发布。任何真实学校账号测试须另行授权；不把真实签到用作验收。

对外分发的 APK 必须另外核对项目、Chaquopy、Python 和依赖许可原文，不能用环境测试通过代替发行许可检查。当前验收包还缺少项目/Chaquopy 版权材料，详细核对范围和待办见发布评估；补齐打包内容后应对新的最终 APK 重新记录来源、哈希和相关验收。
