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

- 当前源码版本为 `2.0.0`，相对 `v1.1.5` 的变化与交付目标见 [发布说明](docs/releases/v2.0.0.md)；实际发布状态、tag 与资产以本仓库的 [GitHub Releases](https://github.com/Maximora-byte/swu-checkin/releases) 为准
- Windows desktop preview 来自 [PR #33](https://github.com/Maximora-byte/swu-checkin/pull/33)。旧 `v1.1.5` Release 只有 Python wheel/sdist，不含桌面功能；`v2.0.0` 的交付目标包含 Python 分发包与单独验证的 Windows 预览资产
- Windows desktop Actions artifacts 保留 14 天；选定构建另行发布到 Release 后才有长期下载入口。桌面安装包仍未签名，构建机 smoke 不替代尚未完成的干净 Windows 10/11 x64 标准用户验收
- 普通 CI 的 `quality` 汇总 Linux、Windows 脚本/运行时与 Python 打包检查；桌面安装包构建单独运行。具体命令、触发条件和发布权限边界见 [开发与发布](docs/development.md)

发布与合并是不同动作。现有 Python Release 工作流只在推送 `v*` tag 时触发，要求版本匹配且 tag commit 已包含在 `main`，并拒绝覆盖已有 Release。它不会自动附加 Windows 安装包；Windows 资产需在确认与 tag 的来源一致、检查通过后另行发布，也不会把合并 `main` 当作桌面发布授权。

## 项目性质

这是非官方社区项目，与西南大学、钉钉或原上游作者不存在隶属、背书或运营关系。学校 API 和认证页面可能随时变化，每个部署实例仍由其运行者自行负责。

## 许可证与署名

本仓库继续使用 `LICENSE` 中的 MIT 许可证。必须保留上游项目的版权与署名声明，新贡献也按同一许可证接受。
