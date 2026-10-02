# GitHub Actions 自动签到

GitHub Actions 适合没有长期在线主机的用户，但 scheduled workflow **不保证准点**。公共 runner 可能延迟几分钟、几十分钟甚至更久；时间窗口严格时请使用 [systemd](DEPLOYMENT.md) 或 [Windows 计划任务](docs/windows.md)。

本指南只适用于 [Maximora-byte/swu-checkin](https://github.com/Maximora-byte/swu-checkin) 的 [`.github/workflows/checkin.yml`](.github/workflows/checkin.yml)。它会执行正式签到，与普通 `CI`、Python `Release`、Windows/macOS 桌面构建及 Android 验证工作流不同；触发与发布边界见 [开发与发布](docs/development.md)。不要复制其他 fork 的 workflow 片段，也不要把真实凭据写进 YAML。

## 工作方式

- 每天北京时间 21:15、21:45 各触发一次；
- 支持 `workflow_dispatch` 手动触发；
- 单个 workflow 可通过 matrix 并行处理多个账号；
- 使用 Python 3.13 和仓库 `uv.lock`；
- CLI 输出 schema v1 JSON，仓库解析器严格校验后才判断成功；
- 仅执行 step 成功、CLI 退出码为 0、有效 JSON 状态为 1/2/5 三者同时成立，才视为正常终态；其余组合进入失败/通知路径；
- 邮件配置完整时，异常结果可发送邮件。

每个账号 job 使用独立 runner，最长运行 15 分钟，瞬时可重试错误最多尝试 3 次、按 8/16 秒等待。不是所有错误都会重试，也不会等待到时间窗口开放。此工作流不配置 systemd 的长期状态文件或 Telegram 日汇总；本机运行锁不能协调不同 runner、独立 workflow run 或另一台设备，请避免重复调度同一账号。

## 1. Fork 并启用 workflow

1. Fork [Maximora-byte/swu-checkin](https://github.com/Maximora-byte/swu-checkin) 到自己的账号；
2. 打开 fork 的 **Actions** 页面；
3. 如果 GitHub 显示 workflow 被禁用，点击 **I understand my workflows, go ahead and enable them**；
4. 在 **自动签到** workflow 页面确认存在 **Run workflow**。

定时任务只从 fork 的默认分支运行。更新 fork 后要确认 `.github/workflows/checkin.yml` 与 `uv.lock` 来自同一已审阅版本。

## 2. 配置单账号 Secrets

进入 fork：**Settings → Secrets and variables → Actions → New repository secret**。

| Secret | 内容 |
| --- | --- |
| `SWU_USERNAME` | 校园网账号/学号 |
| `SWU_PASSWORD` | 校园网密码 |

GitHub 页面不会回显 Secret 明文；workflow 只会把明确引用的 Secret 在 job 运行时注入环境变量。不要运行未经审阅的 fork 代码，也不要把值写到 Variables、workflow、Issue 或日志。

这里的 Secret 名是 `SWU_USERNAME` / `SWU_PASSWORD`；workflow 将它们映射到 CLI 使用的 `SWUDK_USERNAME` / `SWUDK_PASSWORD`，不要把两组名称混用。

## 3. 首次手动验证

在 **Actions → 自动签到 → Run workflow** 手动运行一次。打开对应账号 job，确认：

- locked 依赖安装成功；
- 最终输出是有效 schema v1 JSON；
- 状态码和 CLI exit code 一致；
- 日志没有账号值、密码、token 或完整认证回调。

手动运行会执行正式签到，不是 probe。若只想做只读验证，请先按 [快速上手](docs/quickstart.md) 在本地执行 `swu-checkin probe`。云端提交不测量本人 GPS、不能验证本人在寝；请仅在本人符合学校签到条件时使用，不要把技术提交成功当作实际位置证明。

## 4. 多账号

编辑 fork 的 `.github/workflows/checkin.yml` 中 `matrix.account`：

```yaml
matrix:
  account:
    - name: "账号1"
      username_secret: SWU_USERNAME
      password_secret: SWU_PASSWORD
    - name: "账号2"
      username_secret: SWU_USERNAME_2
      password_secret: SWU_PASSWORD_2
```

再添加 `SWU_USERNAME_2`、`SWU_PASSWORD_2`。更多账号依次使用新的 Secret 名称。`name` 只是日志标签，不要写学号、手机号或真实姓名等敏感信息。

matrix 使用 `fail-fast: false`：一个账号失败不会取消其他账号；每个账号有独立 job 和结果。

## 5. 可选邮件通知

继续添加：

| Secret | 说明 |
| --- | --- |
| `MAIL_SERVER` | SMTP 主机，例如 `smtp.qq.com` |
| `MAIL_PORT` | SMTP 端口，例如 `587` 或 `465` |
| `MAIL_USERNAME` | 发件邮箱账号 |
| `MAIL_PASSWORD` | SMTP 授权码或应用密码，不是优先使用普通登录密码 |
| `NOTIFY_EMAIL` | 接收地址 |

邮件配置缺失时 workflow 会明确 warning 并跳过发送，不会把“通知失败”伪装成“签到成功”。

常见配置：

```text
QQ:      smtp.qq.com:587
Gmail:   smtp.gmail.com:587
163:     smtp.163.com:465
Outlook: smtp-mail.outlook.com:587
```

具体认证方式以邮箱服务商当前说明为准。

## 6. 时间与延迟

workflow 使用 UTC cron，对应北京时间：

```yaml
schedule:
  - cron: '15 13 * * *'  # 21:15 Asia/Shanghai
  - cron: '45 13 * * *'  # 21:45 Asia/Shanghai
```

cron 表示最早可调度时间，不是 SLA。排查“没有准时运行”时先对比 run 的 `created_at` / `started_at`，区分 GitHub 排队和脚本执行时间。

修改时间要同时考虑学校实际窗口和 UTC+8 换算。不要启用高频循环或在失败后无限 dispatch。

## 7. 结果与 JSON

“执行签到” step 先保存 CLI 退出码，再解析 stdout 文件。以下展示同样的两阶段检查，必须在已配置凭据的 Actions Bash 环境中运行；它会正式提交签到，不是离线测试：

```bash
set +e
uv run --locked --no-dev swu-checkin --json > checkin_result.json
exit_code=$?
set -e
uv run --locked --no-dev python -m swu_checkin.actions_result \
  checkin_result.json "$GITHUB_OUTPUT"
status_code=$(uv run --locked --no-dev python -c \
  'import json; print(json.load(open("checkin_result.json", encoding="utf-8"))["code"])')
if [[ "$status_code" != "1" && "$status_code" != "2" && "$status_code" != "5" ]] || \
  [[ "$exit_code" != "0" ]]; then
  exit 1
fi
```

解析器只接受两个位置参数：`RESULT_JSON GITHUB_OUTPUT`，成功返回 0，参数或解析/写入失败返回 2；它不接收或检查 CLI exit code。它检查：

- JSON 可完整解码；
- `schema_version == 1`；
- `mode == "checkin"`；
- 字段集合必须与 schema 完全一致，不能缺少或增加字段；
- 固定状态名称、固定公开 message 与 code 一致，且 code 适用于 checkin；
- `attempts` 是至少为 1 的整数，`duration_ms` 是非负整数，不能用布尔值代替整数。

畸形输出、未知状态码或 schema 不匹配会进入 `OUTPUT_ERROR`；缺失账号或密码直接进入 `CONFIG_ERROR`。解析成功仅表示结构有效，不代表签到成功。状态与退出码的对应关系见 [CLI 参考](docs/cli-reference.md)。

当前 `main` 的“执行签到” step 使用 `continue-on-error: true`，以便继续走通知与最终检查。“汇总签到执行结果”统一计算 `execution_result.outputs.ok`：只有执行 step 的 `outcome == success`、CLI exit code 为 `0`、严格校验后的状态为 `1/2/5` 才为 `true`。邮件条件与最终 job 检查都读取这个汇总结果；成功状态 JSON 搭配非零退出码、解析失败或 step 失败均不会被绿色结果掩盖。通知成功也不会把原本失败的签到 job 改为成功。

这项一致性修复属于 `v2.0.0` tag 之后的 `main`，旧 tag/fork 可能仍采用只检查状态码的后续步骤。同步时需核对完整 workflow，版本号 `2.0.0` 相同不足以证明已包含修复；当前分发差异见 [发布准备评估](docs/releases/release-readiness.md)。

## 8. 更新 fork

更新前阅读当前仓库 Release Notes。同步代码时必须同时更新 workflow、源码、`pyproject.toml` 和 `uv.lock`；不要只复制 `checkin.yml`。

同步后先手动运行一次并检查日志。如果自己修改了 workflow，建议在 PR 中保留变更和 GitHub Checks，便于回滚。

## 9. 停用

推荐：**Actions → 自动签到 → Disable workflow**。

这会停止定时与手动触发，不需要在 YAML 中添加自定义开关。永久不用时也可从 fork 删除 `.github/workflows/checkin.yml`。

## 故障排查

- **Secret 未配置**：核对名称和 matrix 中的 `username_secret` / `password_secret`；
- **状态 3**：验证账号密码与账号状态；
- **状态 4**：检查学校服务、网络和脱敏异常类型，见 [故障排查](docs/troubleshooting.md)；
- **一个账号失败**：打开该账号独立 job，不要从其他账号成功推断它也成功；
- **邮件没发**：检查五个邮件 Secret 和 `检查邮件通知配置` step；
- **cron 延迟**：这是 GitHub 调度限制；时间敏感时迁移到 systemd 或 Windows。

报告本 fork 的问题请使用 [当前仓库 Issues](https://github.com/Maximora-byte/swu-checkin/issues)，附版本、状态码和脱敏结构信息，不要要求原上游作者支持本 fork 的 workflow。
