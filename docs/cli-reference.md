# CLI 与状态码参考

本文描述当前源码的 Python CLI、结果与安全边界；项目版本为 **2.1.0 预发布版**，实际资产见 [v2.1.0 发布页](https://github.com/Maximora-byte/swu-checkin/releases/tag/v2.1.0)，CLI 状态码与 JSON schema v1 沿用。图形应用另见 [Windows 桌面](windows-desktop.md)、[macOS 桌面](macos-desktop.md)和 [Android](android-client.md)，它们不提供同一套 CLI 参数。稳定版 v2.0.0 应使用自身 tag 文档；版本差异见 [v2.1.0 说明](releases/v2.1.0.md)与 [发布准备](releases/release-readiness.md)。

## 命令

| 命令 | 是否访问网络 | 是否提交签到 | 是否读写 TokenStore | 用途 |
| --- | :---: | :---: | :---: | --- |
| `swu-checkin setup` | 是 | 否 | 否 | 始终交互输入账号密码，验证只读接口；不保存凭据 |
| `swu-checkin doctor` | 是 | 否 | 否 | 使用环境变量或交互凭据，输出 Runtime、Credentials 和 5 项接口诊断 |
| `swu-checkin probe` | 是 | 否 | 是 | 一次只读业务检查；可更新初始身份校验失效的 cache，不恢复业务阶段失效的 cache |
| `swu-checkin run` | 是 | 可能 | 是 | 正式签到；运行锁、受限重试、最多一次签到提交 POST |
| `swu-checkin status` | 否 | 否 | 否 | 读取已有非敏感状态文件 |
| `swu-checkin` | 是 | 可能 | 是 | 无子命令兼容入口；默认正式运行，受只读开关影响 |

这里“只读”指不调用签到提交接口。认证和部分查询仍会使用 HTTP POST；不能用 HTTP 方法判断是否执行签到。

```bash
swu-checkin --help
swu-checkin run --help
swu-checkin probe --help
swu-checkin status --help
swu-checkin status --file /absolute/path/status.json
```

源码环境可给命令加 `uv run --locked --no-dev` 前缀。`python -m swu_checkin.check_in` 保留兼容入口并接受同一组 CLI 参数。

### 参数与兼容形式

- 顶层 `--json`：正式运行或 probe 的结构化结果模式；可放在子命令前
- `run --json`、`probe --json`：同一 JSON 模式的子命令写法
- 顶层 `--probe`：旧式只读入口，例如 `swu-checkin --probe --json`
- `status --file PATH`：指定状态文件；优先于 `SWUDK_STATUS_FILE`，最后回退 `/var/lib/swu-checkin/status.json`
- `-h` / `--help`：显示顶层或对应子命令的帮助

`setup`、`doctor`、`status` 不支持 `--json` 或旧式 `--probe`。`run` 与顶层 `--probe` 冲突。无子命令时 `SWUDK_PROBE_ONLY=1` 会选择 probe；显式 `run` 遇到该开关会拒绝执行并退出 `2`，不会悄悄改成 probe。

`setup` 总是重新交互输入，不采用已设置的账号密码环境变量。`doctor`、`probe`、`run` 缺失哪项凭据就询问哪项；密码使用无回显输入。无人值守调用必须事先提供凭据，`--json` 不是非交互开关。

## JSON 模式

```bash
swu-checkin --json
swu-checkin --probe --json
swu-checkin run --json
swu-checkin probe --json
```

正常进入业务流程并返回结果时，stdout 只输出一个 schema v1 JSON document；认证、重试与业务诊断重定向到 stderr。普通文本模式的业务诊断通常在 stdout，CLI 锁错误、安全开关拒绝等消息在 stderr。

```json
{"schema_version":1,"mode":"checkin","status":"success","code":1,"message":"签到成功","attempts":1,"duration_ms":1842}
```

| 字段 | 说明 |
| --- | --- |
| `schema_version` | 整数 `1` |
| `mode` | `checkin` 或 `probe` |
| `status` | 与 `code` 对应的稳定英文名称，见下表 |
| `code` | 当前模式允许的整数业务状态码，不是进程退出码 |
| `message` | 与状态码对应的固定中文信息，见下表 |
| `attempts` | 外层业务尝试次数，至少为 1；probe 固定为 1；不等于 HTTP 请求数或验证码尝试数 |
| `duration_ms` | 业务执行耗时，非负整数；含内部重试等待，不含交互输入、获取运行锁和写状态文件 |

### 没有 JSON 的本地退出

| 情况 | 退出码 | 输出与副作用 |
| --- | ---: | --- |
| 正式运行锁已占用 | `0` | stdout 为空，stderr 为“已有签到任务正在运行，本次跳过。”；不读取凭据、不访问学校、不写状态 |
| 锁路径不安全或无法获取锁 | `1` | stdout 为空，stderr 为“无法安全获取签到运行锁，本次未执行。” |
| 显式 `run` 被 `SWUDK_PROBE_ONLY=1` 阻止 | `2` | stdout 为空，stderr 说明安全开关；不进入正式业务流程 |
| 参数不合法或冲突 | `2` | argparse 输出用法/错误；没有业务结果 JSON |

因此，退出 `0` 不一定代表本次完成签到。调用方应区分上述本地 no-op 与业务结果；一旦存在结果，就完整解析并校验精确字段、schema、mode、status、code、message 与类型，不能用 `tail -1` 或正文正则猜测成功。中断或交互输入失败也不能假定存在 JSON。

GitHub Actions 当前实现还同时要求执行 step 的 `outcome=success`、CLI 退出码为 `0`，且经过结构校验的业务码为 `1`、`2` 或 `5`。成功 JSON 配合非零退出码仍是执行失败，会走异常通知与最终失败分支；这个判定修复来自已合并的 [PR #42](https://github.com/Maximora-byte/swu-checkin/pull/42)，不属于旧 v2.0.0 tag。完整触发和通知规则见 [Actions 指南](../GITHUB_ACTIONS.md)。

## 状态码与进程退出码

| code | status | 固定 message | 正式 run 退出码 | probe 退出码 |
| ---: | --- | --- | ---: | ---: |
| 0 | `no_task` | 今日无签到记录 | 1 | 0 |
| 1 | `success` | 签到成功 | 0 | 不产生 |
| 2 | `already_checked_in` | 已签到 | 0 | 0 |
| 3 | `login_failed` | 登录失败 | 1 | 1 |
| 4 | `data_error` | 网络错误或数据异常 | 1 | 1 |
| 5 | `on_leave` | 请假期间无需签到 | 0 | 0 |
| 6 | `probe_pending` | 检测到待签到任务（未提交） | 不产生 | 0 |

正式业务结果只把 1、2、5 视为正常终态；probe 把 0、2、5、6 视为正常只读结果。账号凭据拒绝和验证码最终失败映射为 3；认证网络、登录页面/认证流程变化、ticket/token 校验等失败映射为 4，不能把所有认证问题都解释为密码错误。

`setup` 成功验证退出 `0`，验证失败退出 `1`；`doctor` 的 7 项检查全部通过才退出 `0`。`status` 即使没有文件或读到的业务结果未成功也退出 `0`；文件损坏或不可读退出 `1`。`status` 的进程退出码只反映本地读取，不表示实时签到结果。

## 执行、重试和诊断

正式流程先验证 token 的账号绑定，然后检查请假与今日任务。请假中、无任务、已签到会提前返回；只有任务为待签到时才继续校验学生/宿舍并构造提交。`doctor` / `setup` 的逐项诊断会检查全部只读接口，不能用它们的结果断言当前存在待签到任务。

外层业务重试仅用于无任务、被分类为认证网络错误的失败，以及提交前已识别的瞬时传输错误：timeout、connection error、HTTP 408/425/429/5xx。凭据拒绝、最终验证码失败、schema/JSON 错误、未知业务结构、非瞬时业务 HTTP 错误和不能恢复的会话失效不会盲目重试。默认最多 3 次，等待 8 秒、16 秒；probe 不运行该外层重试。

验证码获取/OCR 与服务端明确拒绝验证码后的有限重试属于认证内部处理，不计为多个外层 `attempts`，也不表示重发签到表单。

同一次正式业务调用最多一次**签到提交 POST**。传输异常或已解析的响应会触发最多 4 次只读回查（立即、再等待 0.3 / 0.6 / 1.0 秒），确认已签到才返回 1；即使提交响应表示业务成功，也不能跳过回查。提交解析/结构异常可能直接返回 4，不保证每类错误都执行回查。所有这些提交结果都不会再触发外层重试提交。

安全诊断使用固定 `stage=auth/token_validation/leave/transition/student_profile/dormitory/submit/confirm` 和固定分类，不记录原始异常文本或未知业务码。具体排查见 [故障排查](troubleshooting.md)。

## 环境变量

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `SWUDK_USERNAME` | 交互输入 | 校园网账号/学号；不适用于强制交互的 `setup` |
| `SWUDK_PASSWORD` | 无回显交互输入 | 校园网密码；不适用于强制交互的 `setup` |
| `SWUDK_MAX_ATTEMPTS` | `3` | 正式 CLI 最大外层业务尝试次数；非法或非正整数回退默认值 |
| `SWUDK_RETRY_DELAY` | `8` | 首次外层重试等待秒数，之后指数退避；只接受正整数，否则回退默认值 |
| `SWUDK_PROBE_ONLY` | 未设置 | 值恰为 `1` 时兼容入口只运行 probe，并阻止显式 CLI/桌面正式签到 |
| `SWUDK_STATUS_FILE` | 普通本地 run 不记录 | 正式 CLI 状态文件；默认 TokenStore 在所有平台上均优先使用该文件同目录的 `auth-token-cache` |
| `SWUDK_LOCK_FILE` | 平台默认 | CLI/桌面正式执行的共享锁文件；必须为绝对路径，相对路径拒绝执行 |
| `XDG_RUNTIME_DIR` | 系统临时目录 fallback | POSIX 默认锁目录；设置时也必须能形成绝对路径 |
| `XDG_CACHE_HOME` | `~/.cache` | POSIX 默认 token cache 根目录；未设置状态文件时使用 |
| `LOCALAPPDATA` | Windows 用户目录 | Windows token cache/桌面数据根目录；仅默认锁在缺失时回退系统临时目录 |
| `SWUDK_DEBUG_CREDENTIALS` | 关闭 | 值恰为 `1` 时输出安全认证阶段诊断，不含凭据值 |

默认 TokenStore 路径依次为：`SWUDK_STATUS_FILE` 同目录的 `auth-token-cache`；Windows 的 `%LOCALAPPDATA%\SWUCheckin\auth-token-cache`；POSIX 的 `$XDG_CACHE_HOME/swu-checkin/auth-token-cache` 或 `~/.cache/swu-checkin/auth-token-cache`。Windows 未设置 `LOCALAPPDATA` 且无状态路径覆盖时，TokenStore 不会改用临时目录。一个 cache 文件保存一个账号对应的记录，不是多账号凭据库。

Windows 桌面后端显式使用 `%LOCALAPPDATA%\SWUCheckin` 下的 DPAPI cache 和状态文件，不采用 CLI 的 `SWUDK_STATUS_FILE`；macOS 桌面 token 仅在进程内存，正式状态位于 `~/Library/Application Support/SWUCheckin/status.json`，也不使用该覆盖。两种桌面业务重试使用服务默认值，不读取 CLI 的最大次数/延时变量；macOS 不支持定时任务。Android 不使用桌面文件 cache、CLI 状态路径或这些环境变量，业务边界见 [Android 指南](android-client.md)。Windows 定时任务与环境细节见 [桌面版指南](windows-desktop.md)。`swu-checkin-notify` 的参数和专用环境变量见 [服务器部署](../DEPLOYMENT.md)。

## 运行锁与本地状态

默认锁路径：

- Windows：`%LOCALAPPDATA%\SWUCheckin\checkin.lock`，缺失 `LOCALAPPDATA` 时用系统临时目录下的 `SWUCheckin/checkin.lock`
- POSIX 且设置 `XDG_RUNTIME_DIR`：`$XDG_RUNTIME_DIR/swu-checkin.lock`
- 其他 POSIX：系统临时目录下 `swu-checkin-<uid>.lock`
- systemd：unit 显式设置 `/var/lib/swu-checkin/checkin.lock`

正式 CLI 和桌面后端共同使用 `formal_execution` 的锁边界。CLI 在读取凭据前获取锁，保持到业务执行和状态记录结束；桌面锁保护正式业务执行与状态记录。不同锁路径或不同机器不互斥。`setup`、`doctor`、`status`、`probe` 不获取该正式锁，也不能把锁文件存在当成正在运行。

普通 CLI 只在设置 `SWUDK_STATUS_FILE` 后记录正式结果。状态文件与 schema v1 CLI 结果不是同一种 JSON：它保存上海日期、最近最多 10 条正式调用的时间/状态/固定消息，以及这些记录中是否出现成功终态；不逐条记录内部业务重试，也不存账号或 token。写状态失败不会改变已得到的远端结果，CLI 会输出安全警告。读取状态不访问学校，也不判断所存日期是不是今天。

## Python API

历史状态枚举接口：

```python
import os

from swu_checkin.check_in import check_in, check_in_with_retry, probe_check_in

status = probe_check_in(
    os.environ["SWUDK_USERNAME"],
    os.environ["SWUDK_PASSWORD"],
)
```

`check_in` 执行一次业务尝试，`check_in_with_retry` 使用外层重试策略，`probe_check_in` 只读；三者返回 `CheckinStatus`。`probe_check_in` 不在包根导出。

结构化接口从包根导入：

```python
import os

from swu_checkin import run_probe

result = run_probe(os.environ["SWUDK_USERNAME"], os.environ["SWUDK_PASSWORD"])
print(result.to_json())
```

包根 `run_checkin`、`run_probe` 返回 `CheckinResult`，包含 attempts、duration 和 mode。直接调用这些 Python 业务 API 不自动获取 CLI/桌面运行锁、不写运行状态，也不读取 CLI 的只读环境开关。需要这些执行保护的用户应使用 CLI/桌面入口；嵌入方必须自行管理互斥、授权与结果存储。
