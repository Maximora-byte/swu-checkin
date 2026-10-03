# 文档中心

## 用户文档

- [快速上手](quickstart.md)：从安装到首次只读验证和正式运行
- [CLI 与状态码参考](cli-reference.md)：命令、环境变量、JSON 和退出码
- [Windows 桌面版与构建指南](windows-desktop.md)：中文 GUI、默认关闭的定时模式、独立安装包构建与验收边界
- [macOS 桌面预览](macos-desktop.md)：手动窗口、可选钥匙串、分架构构建与未公证限制
- [Android 手动客户端](android-client.md)：人工验证码、加密保存、只读查询与确认后的单次签到
- [Android 运行环境验收](android-feasibility.md)：工具链、模拟器、真机、历史与当前证据
- [Windows 免安装版](windows-portable.md)：ZIP 解压运行、DPAPI 数据边界、升级与任务路径
- [Windows 脚本部署](windows.md)：与桌面版区分、DPAPI、计划任务、迁移和卸载
- [Linux systemd 部署](../DEPLOYMENT.md)：专用用户、timer、通知、升级与回滚
- [GitHub Actions](../GITHUB_ACTIONS.md)：Secrets、多账号、邮件和延迟边界
- [故障排查](troubleshooting.md)：状态 3/4、cache、运行锁与安全报告

## 设计与安全

- [安全模型](security.md)：凭据、TokenStore、提交安全与日志边界
- [OAuth 登录发现](oauth-login-discovery.md)：可信主机、redirect 与回调校验
- [维护与项目归属](../MAINTAINERS.md)
- [v2.0.0 发布说明](releases/v2.0.0.md)：已发布资产、升级与该版本限制
- [v2.1.0 预发布说明](releases/v2.1.0.md)：版本变化、交付资产和未完成的用户验收
- [v2.1.1 正式发行说明](releases/v2.1.1.md)：MatchAll、Android 1.0.0、安装与升级
- [历史预发布评估](releases/release-readiness.md)：当前源码变化、平台验证和发布待办
- [开发、CI 与发布](development.md)：代码结构、离线测试、质量门禁与不同产物
- [贡献指南](../CONTRIBUTING.md)

当前发行系列为 [v2.1.1](https://github.com/Maximora-byte/swu-checkin/releases/tag/v2.1.1)，开发者统一为 MatchAll，交付 Python、Windows x64 与 Android 1.0.0；macOS 15 两架构继续作为预览附件。旧版发行和验收记录保留原始来源，不将旧报告当作当前包的证明。

Windows 仍未获得 Authenticode 签名；macOS 为 ad-hoc 签名、未公证预览。Android 正式包使用受保护的持久密钥，CI debug 包只供测试。用户已于 2026-10-03 反馈真实学校账号查询成功，显示“今日状态暂无签到任务”；这是本人只读操作反馈，不包含实际签到或 16 KB 真机验证。每个最终包的来源、签名和测试以发布资产中的报告为准。

所有文档均以所在 commit/tag 的代码为准。部署时不要把不同版本的 README、`uv.lock`、Windows 脚本或 systemd unit 混合使用。
