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
- 当前源码已同步 Python 版本 **2.1.0**，准备明确标记的 GitHub Pre-release；尚无新 tag 或 Release。新增 macOS 手动预览、Android 客户端、Windows Portable、验证码提供器与 Actions 结果修复；范围见 [候选说明](docs/releases/v2.1.0.md)，证据与门槛见 [发布准备](docs/releases/release-readiness.md)
- 原生平台 Actions artifacts 保留 14 天；Windows 未签名，macOS ad-hoc 签名且未公证。Android 区分 CI 临时 debug 验证包和本机受保护持久签名候选，签名私钥与密码不进仓库/PR。构建机 smoke 不替代真实用户环境验收，合成业务测试不替代真实学校账号测试
- 普通 CI 的 `quality` 汇总 Linux、Windows 脚本/运行时与 Python 打包检查；桌面安装包构建单独运行。具体命令、触发条件和发布权限边界见 [开发与发布](docs/development.md)

Release 工作流在 PR/手动运行时以只读权限完成 Python 与各原生平台预检，以同一源码 SHA 审核实际用户包、来源、哈希和内嵌许可；不发布、不读取签名秘密。只有 `v*` tag push 会进入写权限的发布 job：要求 tag 精确匹配数字项目版本、commit 已包含在 `main`、全部构建与暂存门禁成功，并拒绝覆盖已有 Release。使用固定说明创建 Pre-release（不会设为 latest），自动资产范围为 Python wheel/sdist、Windows installer/Portable、macOS 两架构 ZIP；Android CI debug APK 不公开，持久签名候选另行审核。必须保留历史 tag/资产，最终候选合入后仍须核对选定 commit 的实际产物。Android 密钥保管与受保护备份由发布维护者负责；本机 DPAPI 保存不等于异机恢复已验收。

## 项目性质

这是非官方社区项目，与西南大学、钉钉或原上游作者不存在隶属、背书或运营关系。学校 API 和认证页面可能随时变化，每个部署实例仍由其运行者自行负责。

## 许可证与署名

本仓库继续使用 `LICENSE` 中的 MIT 许可证。必须保留上游项目的版权与署名声明，新贡献也按同一许可证接受。
