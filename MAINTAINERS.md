# 维护与项目归属

## 维护者

`Maximora-byte/swu-checkin` 由 [@Maximora-byte](https://github.com/Maximora-byte) 独立维护。

- 权威仓库：<https://github.com/Maximora-byte/swu-checkin>
- Issue：<https://github.com/Maximora-byte/swu-checkin/issues>
- Pull Request：<https://github.com/Maximora-byte/swu-checkin/pulls>

本仓库源自 [Sorynthia/swu-checkin](https://github.com/Sorynthia/swu-checkin)。原项目及其作者继续按 MIT 许可证获得署名。独立维护表示本 fork 有自己的路线、审查、发布、部署说明和支持边界，并不表示 fork 维护者是上游代码的原始作者。

## 支持边界

维护者接受针对当前 `main` 以及本仓库明确发布 commit 的问题报告和贡献。上游更新可能在审阅后按需引入，但不承诺自动或即时同步。

本 fork 特有的问题应在当前仓库报告，不应转交上游作者。报告应包含 commit SHA、运行方式、稳定状态码和已脱敏的结构诊断。不得附上账号、密码、验证码、token、ticket、OAuth state/code、完整回调 URL、宿舍地址、坐标或原始 API 响应。

定位伪造、反检测、凭据收集、认证绕过或削弱可信主机/回调校验的改动不在项目范围内。

## 版本与交付渠道

- 截至 2026-10-02，最新已发布 [v2.0.0](https://github.com/Maximora-byte/swu-checkin/releases/tag/v2.0.0) 包含 Python wheel/sdist、Windows x64 安装包和完整 onedir ZIP，源码 commit 为 `ccedc7b642f6391d86ba7ddfc7e42e69467c2e64`；该版本说明见 [发布说明](docs/releases/v2.0.0.md)
- 当前 `main` 仍使用 Python 版本号 `2.0.0`，新增 macOS 手动预览、Android 手动客户端、Windows Portable ZIP、验证码提供器和 Actions 结果修复；这些变化尚未随新 Release 交付。下一版范围和条件见 [发布评估](docs/releases/release-readiness.md)，版本号不代替源码来源
- 原生平台 Actions artifacts 保留 14 天；Windows 未签名，macOS 未公证，Android 使用临时调试签名。构建机 smoke 不替代真实用户环境验收，Android 合成业务测试不代替真实学校账号测试；支持边界见各平台指南
- 普通 CI 的 `quality` 汇总 Linux、Windows 脚本/运行时与 Python 打包检查；桌面安装包构建单独运行。具体命令、触发条件和发布权限边界见 [开发与发布](docs/development.md)

现有 Python Release 工作流只在推送 `v*` tag 时触发，要求 tag 精确匹配项目版本、commit 已包含在 `main`，并拒绝覆盖已有 Release。它创建 wheel/sdist 的普通 Release，不自动标记 Pre-release，也不附加 Windows、macOS 或 Android 资产。预发布标记与原生资产审核须在新版发布流程中明确实现；不可复用已有 `v2.0.0` tag 或仅凭合并通过就宣称跨平台发布完成。Android 对外 APK 还须补齐项目 MIT 与核对第三方许可材料；详见发布评估。

## 项目性质

这是非官方社区项目，与西南大学、钉钉或原上游作者不存在隶属、背书或运营关系。学校 API 和认证页面可能随时变化，每个部署实例仍由其运行者自行负责。

## 许可证与署名

本仓库继续使用 `LICENSE` 中的 MIT 许可证。必须保留上游项目的版权与署名声明，新贡献也按同一许可证接受。
