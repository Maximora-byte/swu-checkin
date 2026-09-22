# 贡献指南

感谢你考虑为 `Maximora-byte/swu-checkin` 做出贡献。

本项目是由 [Maximora-byte](https://github.com/Maximora-byte) 独立维护的 [Sorynthia/swu-checkin](https://github.com/Sorynthia/swu-checkin) fork。本 fork 的 Issue、Pull Request、发布和支持均在[当前仓库](https://github.com/Maximora-byte/swu-checkin)处理；除非问题可以在未经修改的上游版本中独立复现，否则请不要将本 fork 的问题转交上游作者。

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

- Python 代码通过 Ruff lint 与格式检查
- 使用 Python 3.13 和仓库中的 `uv.lock`，不要无故更新依赖锁
- 提交信息使用清晰的中文或英文描述
- 添加必要的注释和文档
- 不得加入定位伪造、反检测、凭据持久化或降低 OAuth/CAS 安全校验的改动

### Pull Request 要求

- 保持修改范围单一，不混入无关格式化或重构
- 确保代码通过现有测试与 CI
- 对于新功能，添加相应的测试用例
- 更新相关文档
- 新增或修改用户行为时，同步检查 [文档中心](docs/README.md)、README、部署指南和故障排查；示例命令必须与当前 CLI 一致
- 文档中的相对链接必须指向仓库内存在的文件；不得在教程中加入真实账号、token、地址、坐标或原始 API 响应
- 保持提交历史清晰

## 开发环境

### Python 项目

推荐使用 uv 按锁文件安装全部开发依赖：

```bash
uv sync --locked --all-groups --python 3.13
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv lock --check
```

CI 还会运行 actionlint、systemd 单元校验、Unix DAC 权限测试和锁定生产依赖漏洞审计。请不要通过删除或跳过安全测试来使 PR 通过。

## 行为准则

- 尊重所有贡献者
- 保持友好和专业的交流
- 接受建设性的批评
- 关注项目目标和用户需求

## 许可证

提交代码即表示你同意你的贡献使用项目的 MIT 许可证。独立维护关系不会移除原上游作者的署名或许可证声明；贡献者也不应改写他人的作者身份。
