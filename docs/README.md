# 文档中心

## 用户文档

- [快速上手](quickstart.md)：从安装到首次只读验证和正式运行
- [CLI 与状态码参考](cli-reference.md)：命令、环境变量、JSON 和退出码
- [Windows 桌面版与构建指南](windows-desktop.md)：中文 GUI、默认关闭的定时模式、独立安装包构建与验收边界
- [Windows 脚本部署](windows.md)：与桌面版区分、DPAPI、计划任务、迁移和卸载
- [Linux systemd 部署](../DEPLOYMENT.md)：专用用户、timer、通知、升级与回滚
- [GitHub Actions](../GITHUB_ACTIONS.md)：Secrets、多账号、邮件和延迟边界
- [故障排查](troubleshooting.md)：状态 3/4、cache、运行锁与安全报告

## 设计与安全

- [安全模型](security.md)：凭据、TokenStore、提交安全与日志边界
- [OAuth 登录发现](oauth-login-discovery.md)：可信主机、redirect 与回调校验
- [维护与项目归属](../MAINTAINERS.md)
- [开发、CI 与发布](development.md)：代码结构、离线测试、质量门禁与不同产物
- [贡献指南](../CONTRIBUTING.md)

`main` 包含合入的桌面预览功能；已发布 Python tag 与桌面 CI artifact 是不同交付渠道。桌面版目前未签名、尚无正式 Release，支持与验收限制见对应指南。

所有文档均以所在 commit/tag 的代码为准。部署时不要把不同版本的 README、`uv.lock`、Windows 脚本或 systemd unit 混合使用。
