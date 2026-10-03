# 贡献指南

感谢你考虑为 `Maximora-byte/swu-checkin` 做出贡献。

本项目是由 [MatchAll](https://github.com/Maximora-byte) 独立维护的 [Sorynthia/swu-checkin](https://github.com/Sorynthia/swu-checkin) fork。本 fork 的 Issue、Pull Request、发布和支持均在[当前仓库](https://github.com/Maximora-byte/swu-checkin)处理；除非问题可以在未经修改的上游版本中独立复现，否则请不要将本 fork 的问题转交上游作者。

## 如何贡献

### 报告问题

- 使用[当前仓库 Issues](https://github.com/Maximora-byte/swu-checkin/issues) 报告 bug 或提出功能请求
- 提供清晰的标题和详细的描述
- 包含复现步骤、环境信息和预期行为
- 认证或接口问题只附结构信息；不要提交账号、密码、验证码、token、ticket、OAuth state/code、完整回调 URL、地址或坐标

### 提交代码

1. Fork [Maximora-byte/swu-checkin](https://github.com/Maximora-byte/swu-checkin)
2. 从最新 `main` 创建单一用途分支 (`git checkout -b fix/short-description`)
3. 提交范围清晰的修改 (`git commit -m 'fix: short description'`)
4. 推送到分支 (`git push origin fix/short-description`)
5. 向 `Maximora-byte/swu-checkin:main` 创建 Pull Request

### 代码规范

- Python 代码通过 Ruff lint、格式检查及 `mypy src/swu_checkin`
- 使用 Python 3.13 和仓库中的 `uv.lock`，不要无故更新依赖锁
- 提交信息使用清晰的中文或英文描述
- 添加必要的注释和文档
- 不得加入定位伪造、反检测、凭据收集或降低 OAuth/CAS 安全校验的改动
- 凭据不得进入仓库、日志或未受保护的文件；既有 GitHub Secrets、root-only 环境文件、Windows DPAPI、macOS Keychain、Android Keystore 与受限 token cache 必须保持各自安全边界，详见 [安全说明](docs/security.md)

### Pull Request 要求

- 保持修改范围单一，不混入无关格式化或重构
- 确保代码通过现有测试与 CI
- 对于新功能，添加相应的测试用例
- 更新相关文档
- 新增或修改用户行为时，同步检查 [文档中心](docs/README.md)、README、部署指南和故障排查；示例命令必须与当前 CLI 一致
- 桌面功能、凭据存储、计划任务或正式执行入口变更，还需覆盖默认关闭、重复点击、关闭/取消、跨进程锁、只读与正式模式隔离，并更新 [桌面版指南](docs/windows-desktop.md)
- macOS 或 Android 前端变更，还需检查对应平台生命周期、手工操作与安全存储；更新 [macOS 指南](docs/macos-desktop.md)或 [Android 指南](docs/android-client.md)。模拟接口、模拟器、原生 CI 与真实学校账号验证必须分别记录
- 文档中的相对链接必须指向仓库内存在的文件；不得在教程中加入真实账号、token、地址、坐标或原始 API 响应
- 新增分发格式须检查项目 MIT LICENSE、依赖许可/notice 和构建来源是否随实际产物交付；源码仓库有 LICENSE 不等于安装包已经携带许可，功能测试也不能替代这项检查
- 保持提交历史清晰

## 开发环境

### Python 项目

代码结构、平台边界和完整验证步骤见 [开发与发布](docs/development.md)。推荐使用与 CI 相同的 uv 0.12.15 和 Python 3.13，按锁文件安装全部开发依赖：

```bash
uv sync --locked --all-groups --python 3.13
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src/swu_checkin
uv lock --check
```

这些测试使用合成数据或模拟接口，不需要真实学校账号。`probe` / `doctor` / `setup` 会访问学校服务，`run` 或无参数 CLI 会正式签到，不能拿它们代替离线测试。

普通 CI 包括 `linux-quality`、`windows-quality`、`package-quality`，由 `quality` 汇总三个结果；另有 actionlint、systemd 单元校验、Unix DAC 权限测试、Windows PowerShell/DPAPI、跨进程锁、wheel/sdist 安装 smoke 和生产依赖漏洞审计。原生工作流独立支持路径过滤 PR/手动运行与 `workflow_call`；Release 预检按精确同一 SHA 调用 Windows、macOS 和 Android，审核实际安装包及许可来源。它们仍不属于普通 `quality` 的依赖；是否触发以各 workflow 的实际路径规则为准。PR 预检不发布且不接触发行签名秘密。请勿删除或跳过安全测试，也不要把未执行的平台检查记作通过。

当前候选源码为 **2.1.0**，最新公开版本仍为 v2.0.0；[候选说明](docs/releases/v2.1.0.md)和 [发布准备](docs/releases/release-readiness.md)记录具体范围与证据。三段数字版本配合 GitHub Pre-release 属性使用，不能直接改为 `2.1.0rc1` 后假设 Windows 安装器仍接受。版本、锁文件、内嵌许可证或签名变化均须审核变化后的实际包。已发布 tag 和资产不可用不同代码重新打包覆盖。

## 行为准则

- 尊重所有贡献者
- 保持友好和专业的交流
- 接受建设性的批评
- 关注项目目标和用户需求

## 许可证

提交代码即表示你同意你的贡献使用项目的 MIT 许可证。独立维护关系不会移除原上游作者的署名或许可证声明；贡献者也不应改写他人的作者身份。
