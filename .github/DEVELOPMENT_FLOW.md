# 开发、审查与密钥流程

```text
需求 → 本地分支 / Copilot Student → PR → 现有 CI + Codecov → 人工审核
                                      └→ matchall-bot 分类
图片优化 → ImgBot PR → 图片门禁 → 人工审核
Doppler → dev: 本地应用 / ci: 专用测试 / prd: 经授权的服务器
```

## 日常使用

1. 明确需求、验收条件和允许修改的组件；读取 AGENTS.md。
2. 在独立分支实现；Copilot Student 使用当前支持的 Auto 模型。给提示词提供源码与合成测试数据，不提供密钥、用户数据或生产日志。
3. 本地执行当前项目的必要检查：uv sync --locked --all-groups --python 3.13; uv run --locked pytest -q; uv run --locked ruff check .; uv run --locked ruff format --check .; uv run --locked mypy src/swu_checkin; uv lock --check. POSIX integration checks need Linux.
4. 创建小范围 PR，说明行为、检查结果、迁移和回滚影响。CI 继续使用现有矩阵、路径选择与取消旧运行机制。
5. 人工代码 PR 准备好时，按需请求一次 Copilot review；普通图片、依赖和文档 bot PR 不默认请求。自动审查、每次 push 审查和付费超额默认关闭。
6. 检查 Codecov 与 CI 结果后人工审核。合并不触发生产部署许可。

## Doppler Local

Existing secret-free checks remain the default. If an affected backend needs credentials, create a separate Doppler project for that service and a dev config with synthetic or sandbox credentials, then use `doppler run --project <service> --config dev -- <application-command>`. Do not use one shared all-service token. Do not wrap an IDE, Copilot CLI or agent in this command. Browser/Android/mini-program builds receive only intentionally public configuration; signing and account credentials are separate release operations.

## Doppler GitHub Actions

普通 PR 单元测试不需要真实密钥。需要联网集成测试时，使用独立 `ci` 环境、只读 service account 和 OIDC 短期身份，仅允许受信任默认分支的手动 workflow_dispatch。绑定准确 repository、ref、event_name、workflow_ref、audience 和 environment subject；禁止通配仓库权限、pull_request_target 执行 PR 代码、fork 或任意分支取密钥。

只把 OIDC identity ID 放到 GitHub variable；不存长期 Doppler token。不导出所有 GitHub secrets，不把 prd 同步到 Actions、Codespaces 或 Copilot Agents。取密钥的 job 不安装或执行 PR 提供的依赖/脚本，不写环境到日志或 artifact。参考 matchall-bot 的 `.github/workflows/doppler-ci.yml` 与 matchallworkflow 的 `docs/copilot-doppler-flow.md`。

## Doppler Server

每个服务各有 prd 配置及只读单配置 token。token 存在该服务专属的受保护凭据文件，不能给容器、Copilot 或其他服务。生产迁移先审批明确的变量清单和目标，再备份、验证、暂存新配置、检查、仅重建该服务并验证健康；保留已知良好的旧配置以便回滚。Doppler 断网或配置无效时终止刷新，正在运行的服务继续使用原配置；不启用 watch/定时重启。

GitHub App 私钥、现有账户 OAuth refresh tokens、数据库、聊天数据和备份不在本次迁移范围。生产密钥变更需要单独审批，不能把整台服务器的 .env 自动上传。

## 额度与分工

matchall-bot 不消耗 Actions 贴标签额度；旧 auto-label workflow 保持禁用。ImgBot 只在已选择的图片仓库工作。Codecov 复用已有测试并保留一次合并上传。Copilot 使用学生包含额度，额外预算保持 $0；Doppler 使用已生效的学生 Team 权益，不开启收费附加项。
