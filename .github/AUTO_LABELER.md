# PR / Issue 自动标签

本仓库通过 `.github/workflows/auto-label.yml` 自动给 PR 和 Issue 添加标签。

- Issue 创建、修改、重新打开时重新分类。
- PR 创建、修改、重新打开、推送新提交、准备评审时重新分类。
- 根据中英文标题、正文和 PR 修改的文件路径匹配，可添加多个标签。
- 仅补充标签，保留已有标签、颜色和说明；无法分类时添加 `needs-triage`。
- 不会移除标签，因此修改标题后旧标签需要人工清理。

| 标签 | 依据 |
| --- | --- |
| `bug` | 修复、报错、崩溃、fix、bug、复现步骤等 |
| `enhancement` | 新功能、新增、改进、feat、feature 等 |
| `documentation` | 文档相关文本、README、docs、Markdown 文件 |
| `question` | 如何、怎么、求助、question、问号；没有其他匹配时 |
| `dependencies` | 依赖更新文本、Dependabot/Renovate、依赖清单和锁文件 |
| `security` | 安全漏洞、CVE、XSS、权限绕过等 |
| `performance` | 性能、卡顿、内存泄漏、perf 等 |
| `refactor` | 重构、refactor 等 |
| `tests` | 测试相关标题和测试文件 |
| `github-actions` | CI/工作流相关文本和 `.github/workflows/` 文件 |
| `frontend` | 前端目录、JSX/TSX、Vue、CSS、HTML 等文件 |
| `backend` | 后端服务/API 目录、Go/PHP 文件 |
| `mobile` | Android/iOS 目录、Kotlin、Swift 等文件 |
| `needs-triage` | 未匹配到其他类别，等待人工分类 |

这是一套规则分类器，不调用付费 AI 服务。正文中的代码块、HTML 注释、未勾选的复选框和 URL 不参与匹配。机器人不会读取或执行 PR 中的代码。

## 批量处理与预览

在 GitHub 的 **Actions → Auto label PRs and Issues → Run workflow** 中：

- `number` 留空：处理所有尚未关闭的 Issue 和 PR。
- `number` 填写编号：只处理该 Issue 或 PR。
- 勾选 `dry_run`：仅预览，结果显示在运行摘要中。

标签缺失时自动创建，现有同名标签保留原有颜色和说明。
工作流只取得 Issue/PR 写入权限，使用 GitHub 内置的 `GITHUB_TOKEN`，无需配置个人令牌或其他 Secret。Action 固定到完整提交 SHA。

## 调整规则

编辑工作流中 `definitions`、`titleRules`、`bodyRules` 和文件路径匹配规则。
保留 `pull_request_target` 下只运行可信默认分支脚本的设计，不添加 PR 分支 checkout 或执行 PR 代码。
本工作流只覆盖安装它的仓库；新建仓库时需要复制工作流。
