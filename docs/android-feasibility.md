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

Gradle wrapper 与 distribution 都校验固定 SHA256。SDK 路径放本地 `android/local.properties` 或 `ANDROID_HOME`，不得提交。工作流使用 GitHub runner 已安装的官方工具和已有 SDK 许可，不自动接受新条款。

[`android-feasibility.yml`](../.github/workflows/android-feasibility.yml) 分别构建双 ABI debug APK、运行 Android lint、检查 APK 中的 Python/ABI，并在 API24/35 x86_64 模拟器执行真实 embedded Python instrumentation。测试公共 HTTPS 需网络，失败不会被改写为通过。证据 artifact 包含源 commit、APK SHA256、测试 XML/HTML、模拟器版本与页大小；debug APK 使用临时 debug 签名，不是生产签名、Release 或自动发布。

## 完成门槛与待验证项

必须区分本机 Python 单元测试、APK 构建、Android 模拟器、真实设备四类证据。PR 中记录实际 commit、run 与结果；没有执行的项目保持“未验证”。

- [ ] 双 ABI APK 构建与 lint 通过，APK 中确有 Python 3.13 且无桌面 OCR 依赖
- [ ] API24 和 API35 模拟器：核心 import、tzdata、app-private 读写、统一运行锁、验证证书的 HTTPS
- [ ] arm64 真机：以上全部检查；记录 Android 版本、ABI、页大小，不记录序列号/个人信息
- [ ] 真机 16 KB 页大小兼容性（若支持范围内），模拟器不能替代对应真机结果
- [ ] Android 跨进程锁与进程被杀后的释放（同进程锁争用不等价于跨进程验收）
- [ ] 升级覆盖安装与清除数据后的重新启动

当前执行工作区没有 Android SDK、adb、emulator、`/dev/kvm` 或已连接真机；本机 Android 检查不可执行，交由上述 CI 验证可执行部分。**实机门槛未过前，不进入完整账号/签到 UI，也不宣称首版完成。**

后续分层为验证码/AndroidKeystore 安全适配器，再接中文只读诊断、任务“待签/已签”与明确确认的手动签到。需覆盖取消、双击、旋转、切后台、断网、进程死亡、升级与清数据；只读路径永不提交，提交超时不盲目重发，结果须以服务端回读确认。任何真实学校账号测试须另行授权；不把真实签到用作验收。
