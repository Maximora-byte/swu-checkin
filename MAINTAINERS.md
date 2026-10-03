# 维护与项目归属

## 维护者

`Maximora-byte/swu-checkin` 由 [MatchAll（@Maximora-byte）](https://github.com/Maximora-byte) 独立维护。

- 权威仓库：<https://github.com/Maximora-byte/swu-checkin>
- Issue：<https://github.com/Maximora-byte/swu-checkin/issues>
- Pull Request：<https://github.com/Maximora-byte/swu-checkin/pulls>

本仓库源自 [Sorynthia/swu-checkin](https://github.com/Sorynthia/swu-checkin)。原项目及其作者继续按 MIT 许可证获得署名。独立维护表示本 fork 有自己的路线、审查、发布、部署说明和支持边界，并不表示 fork 维护者是上游代码的原始作者。

## 支持边界

维护者接受针对当前 `main` 以及本仓库明确发布 commit 的问题报告和贡献。上游更新可能在审阅后按需引入，但不承诺自动或即时同步。

本 fork 特有的问题应在当前仓库报告，不应转交上游作者。报告应包含 commit SHA、运行方式、稳定状态码和已脱敏的结构诊断。不得附上账号、密码、验证码、token、ticket、OAuth state/code、完整回调 URL、宿舍地址、坐标或原始 API 响应。

定位伪造、反检测、凭据收集、认证绕过或削弱可信主机/回调校验的改动不在项目范围内。

## 版本与交付渠道

- 当前发行系列为 **v2.1.1**，Python/Windows 项目版本 2.1.1，Android 1.0.0；软件开发者和发行者统一为 MatchAll。仓库名、包名与原有签名身份保持连续；原始 MIT 版权与第三方署名保留。说明见 [v2.1.1](docs/releases/v2.1.1.md)。
- macOS 附件继续为 ad-hoc 签名、未公证预览。Windows 尚未获得 Authenticode 签名。Android CI debug 包仅供测试；正式分发使用仓库外受保护的持久签名。
- 原生平台 Actions artifacts 保留 14 天；旧 tag 和 Release 资产不随 main 更新。各版本证据以对应来源与实际文件为准。

Release 工作流在 PR/手动运行时只读预检同一源码的 Python 和原生平台包，不读取发行密钥。仅 v* tag push 可创建发行：数字版本必须匹配，commit 必须已在 main，所有构建和暂存门禁成功，拒绝覆盖已有版本。[tool.swu-checkin.release] 明确渠道；prerelease 创建非 latest 预发布，stable 先创建草稿。维护者随后加入同源持久签名 Android APK、证书和验收报告，验证完整资产与哈希后才公开草稿并设为 latest。签名私钥和任何密码不属于发行资产，离机备份采用独立密码保护的 PKCS12，不依赖原电脑 DPAPI。

## 项目性质

这是非官方社区项目，与西南大学、钉钉或原上游作者不存在隶属、背书或运营关系。学校 API 和认证页面可能随时变化，每个部署实例仍由其运行者自行负责。

## 许可证与署名

本仓库继续使用 `LICENSE` 中的 MIT 许可证。必须保留上游项目的版权与署名声明，新贡献也按同一许可证接受。
