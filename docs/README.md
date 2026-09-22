# 文档中心

## 用户文档

- [快速上手](quickstart.md)：从安装到首次只读验证和正式运行
- [CLI 与状态码参考](cli-reference.md)：命令、环境变量、JSON 和退出码
- [Windows 使用指南](windows.md)：DPAPI、计划任务、更新和卸载
- [Linux systemd 部署](../DEPLOYMENT.md)：专用用户、timer、通知、升级与回滚
- [GitHub Actions](../GITHUB_ACTIONS.md)：Secrets、多账号、邮件和延迟边界
- [故障排查](troubleshooting.md)：状态 3/4、cache、运行锁与安全报告

## 设计与安全

- [安全模型](security.md)：凭据、TokenStore、提交安全与日志边界
- [OAuth 登录发现](oauth-login-discovery.md)：可信主机、redirect 与回调校验
- [维护与项目归属](../MAINTAINERS.md)
- [贡献指南](../CONTRIBUTING.md)

所有文档均以所在 commit/tag 的代码为准。部署时不要把不同版本的 README、`uv.lock`、Windows 脚本或 systemd unit 混合使用。
