# Android 分发许可材料

`android/app/src/main/assets/licenses/` 会作为普通 Android assets 打进 debug 和 release APK。项目 MIT、Chaquopy、CPython、原生库以及 bootstrap 中被上游 `.py` 打包规则遗漏的第三方许可都保留原文。没有把第三方项目改标成项目 MIT。

`inventory.json` 是审核过的分发输入清单，记录原始来源、版本、文件 SHA-256 和转换方式。清单同时包括：

- 许可资产和 `requirements-common.imy` / `bootstrap.imy` 中原有的 LICENSE、NOTICE、AUTHORS。
- 实际 Python distribution METADATA，包括九个 Android requirements、setuptools 和 pyelftools。
- Chaquopy 官方 bootstrap 与 CPython 公共标准库归档的完整哈希，以及两个 ABI 的所有原生文件哈希。
- 实际 `releaseRuntimeClasspath` 的 Maven 坐标、POM 及归档哈希。此列表包含不产生代码的平台和元数据组件，不能把其数量当作 APK 中的库数量。

CPython 版本依据 Chaquopy 17.0.0 的实际 `target:3.13.9-0` 输入，原生依赖依据该版本的官方 Android 构建脚本。附带的 `.sh` 和 `.py.txt` 是原文字节的来源证据，并不是本项目要执行的构建脚本。CPython 文档与源通知还包含被 Android 构建裁掉的上游代码材料，保留这些通知不代表重新引入桌面模块。

构建后验证实际 APK，校验器以仓库清单为信任来源，不接受 APK 自己重新填写的哈希：

```sh
python scripts/android/verify_apk.py android/app/build/outputs/apk/release/app-release.apk
```

在 `android/` 内导出 Gradle 的实际发行依赖并检查：

```sh
./gradlew :app:dependencies --configuration releaseRuntimeClasspath > runtime-dependencies.txt
python ../packaging/android/verify_maven_inventory.py runtime-dependencies.txt
```

更新依赖时，先检查实际 AAR、JAR、wheel 和 Chaquopy runtime 中的许可与 vendored 代码，取得精确版本的官方原文，再更新来源、哈希和清单。对于 Maven 子 POM 没有 license 的情况要检查父 POM；对于 setuptools 或 pyelftools 这样的 vendored 分发，要检查子库原始许可，不能只保留顶层 LICENSE。最后重新构建并运行两个门禁。

Python 包的上游源代码链接保留在清单中；certifi 原始源码可通过对应的精确 PyPI 版本获取，其 MPL-2.0 许可保留在嵌套归档内。
