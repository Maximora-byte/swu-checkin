# Android 可行性验证（开发预览）

这是 Android 移植的**第一道验证门槛**，不是已完成的手机签到客户端。APK 没有账号/密码输入、学校诊断或签到入口；启动不会联网。只有点击“验证公共 HTTPS”或执行指定 instrumentation 测试时才访问 `https://www.python.org/robots.txt`，不携带账号数据，也不访问学校。

## 选型与官方依据

2026-10-02 核对官方资料：

- [Chaquopy 版本矩阵](https://chaquo.com/chaquopy/doc/current/versions.html)：固定 17.0.0，支持 Python 3.13，最低 API 24（Android 7.0）
- [Chaquopy Gradle 配置](https://chaquo.com/chaquopy/doc/current/android.html)：Python 3.12+ 只有 64 位；本 APK 固定 `arm64-v8a` 与 `x86_64`，宿主构建同样使用 Python 3.13
- [AGP 8.13 官方兼容说明](https://developer.android.com/build/releases/agp-8-13-0-release-notes)：固定 AGP 8.13.2 / Gradle 8.13 / JDK 17，compile/target SDK 36
- [Compose 编译器配置](https://developer.android.com/develop/ui/compose/setup-compose-dependencies-and-compiler)：Kotlin 与 Compose compiler plugin 同版本；这里采用可独立更新的固定兼容组合 Kotlin 2.2.21 / Compose BOM 2025.12.01，而非动态 latest

版本矩阵只是构建候选依据，不证明某台手机可运行。`minSdk=24` 不代表支持 Android 7 的 32 位手机；32 位 ABI 不在支持范围。

## 边界

- Kotlin + Jetpack Compose 只提供验证按钮；Chaquopy 加载仓库原有 Python 核心，不复制签到逻辑
- Android 单独固定纯 Python 运行依赖于 [`requirements-android.txt`](../android/requirements-android.txt)，包括明确打包的 tzdata；默认桌面/CLI 依赖与 uv.lock 不变
- 不打包 ddddocr、Pillow、ONNX、OpenCV，不假设桌面原生 wheel 能在 Android 工作；核心依赖验证码提供器的惰性 OCR 接缝
- 只声明 INTERNET，无位置、后台定位、闹钟、启动广播、外部存储或通知权限；无 WorkManager/自动签到
- 禁用应用备份，测试文件位于应用 `noBackupFilesDir` 下，不写 Python 源码/解压目录
- 测试统一 `formal_execution.execute_formal_checkin_with_lock` 边界，传入的是无网络的锁争用函数，绝不调用正式签到
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

CI 普通镜像固定 4096 MB 内存，16 KB 镜像固定 6144 MB，并记录配置。16 KB 官方 Google 镜像在默认 2560 MB 下曾触发 `lowmemorykiller`，前台测试进程被系统杀死；该失败必须保留系统日志并通过增加模拟器内存重新验证，不能忽略失败或降低测试要求。本机启动对应镜像也应显式传入 `-memory 4096` / `-memory 6144` 和 `-accel on`。

[`android-feasibility.yml`](../.github/workflows/android-feasibility.yml) 分别构建双 ABI debug APK、运行 Android lint、检查 APK 中的 Python/ABI，并在 API24/4 KB、API35/4 KB、API35/16 KB x86_64 模拟器执行真实 embedded Python instrumentation。API35 的实际页大小必须匹配矩阵，否则失败。每次安装状态执行四项测试，包括实际按钮点击和 Activity 重建；首次安装、同版本覆盖安装、清数据共三轮。测试公共 HTTPS 需网络，失败不会被改写为通过。模拟器安装的是 package job 的同一 APK/test APK，先核对源 commit 与两个 APK 的 SHA256，不独立重建。证据包含源码、APK hash、原始测试结果、真实界面、完整一次性模拟器系统日志；debug APK 使用临时 debug 签名，不是生产签名、Release 或自动发布。

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

系统日志开关仅允许一次性模拟器。脚本只卸载/清除这个不含账号的可行性应用，不清除整个设备；同版本覆盖安装不代表跨版本升级迁移。普通镜像应使用 `--page-size 4096`，真实 arm64 手机应使用 `--abi arm64-v8a` 并填入实测页大小。

## 完成门槛与待验证项

必须区分本机 Python 单元测试、APK 构建、Android 模拟器、真实设备四类证据。PR 中记录实际 commit、run 与结果；没有执行的项目保持“未验证”。

- [ ] 双 ABI APK 构建与 lint 通过，APK 中确有 Python 3.13 且无桌面 OCR 依赖
- [ ] API24/4 KB、API35/4 KB 和 API35/16 KB 模拟器：核心 import、tzdata、app-private 读写、统一运行锁、验证证书的 HTTPS、按钮点击及页面重建
- [ ] arm64 真机：以上全部检查；记录 Android 版本、ABI、页大小，不记录序列号/个人信息
- [ ] 真机 16 KB 页大小兼容性（若支持范围内），模拟器不能替代对应真机结果
- [ ] Android 跨进程锁与进程被杀后的释放（已加入 debug-only 私有第二进程测试；等待实际结果）
- [ ] 同版本覆盖安装与清除数据后的重新启动（已加入模拟器测试）；跨版本升级迁移仍待后续验证

Windows 可通过项目内工具链执行上述构建和模拟器验收。没有连接的真机时，arm64/16 KB 真机项目仍标为未验证；**实机门槛未过前，不进入完整账号/签到 UI，也不宣称首版完成。**

后续分层为验证码/AndroidKeystore 安全适配器，再接中文只读诊断、任务“待签/已签”与明确确认的手动签到。需覆盖取消、双击、旋转、切后台、断网、进程死亡、升级与清数据；只读路径永不提交，提交超时不盲目重发，结果须以服务端回读确认。任何真实学校账号测试须另行授权；不把真实签到用作验收。
