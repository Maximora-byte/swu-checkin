# CLI 与状态码参考

## 命令

| 命令 | 是否访问网络 | 是否提交 | 是否读写 TokenStore | 用途 |
| --- | :---: | :---: | :---: | --- |
| `swu-checkin setup` | 是 | 否 | 否 | 交互验证账号和全部只读接口，不保存密码 |
| `swu-checkin doctor` | 是 | 否 | 否 | 输出 Runtime、Credentials 和 5 项接口诊断 |
| `swu-checkin probe` | 是 | 否 | 只读 | 查询请假、学生、宿舍和任务；stale cache 不会被刷新 |
| `swu-checkin run` | 是 | 是 | 是 | 正式签到；运行锁、有限重试、提交后回读 |
| `swu-checkin status` | 否 | 否 | 否 | 读取已有非敏感状态文件 |
| `swu-checkin` | 是 | 是 | 是 | 兼容入口，等价于正式签到 |

旧式 `swu-checkin --probe` 与 `SWUDK_PROBE_ONLY=1 swu-checkin` 仍兼容。显式 `swu-checkin run` 遇到 `SWUDK_PROBE_ONLY=1` 会 fail closed，拒绝正式执行。

## JSON 模式

以下形式受支持：

```bash
swu-checkin --json
swu-checkin --probe --json
swu-checkin run --json
swu-checkin probe --json
```

`setup`、`doctor` 和 `status` 没有 JSON 输出。JSON 模式保证 stdout 只有一个 document，诊断文本进入 stderr。

```json
{"schema_version":1,"mode":"checkin","status":"success","code":1,"message":"签到成功","attempts":1,"duration_ms":1842}
```

| 字段 | 说明 |
| --- | --- |
| `schema_version` | 固定为 `1` |
| `mode` | `checkin` 或 `probe` |
| `status` | 与 `code` 一一对应的稳定英文名称 |
| `code` | 0–6 的业务状态码 |
| `message` | 与状态码对应的中文信息 |
| `attempts` | 本次业务尝试次数，至少为 1 |
| `duration_ms` | 总耗时，非负整数 |

调用方必须完整解析 JSON 并校验 schema、mode、status 与 code，不能用 `tail -1` 或正文正则猜测成功。

## 状态码与进程退出码

| code | status | 含义 | 正式 run 退出码 | probe 退出码 |
| ---: | --- | --- | ---: | ---: |
| 0 | `no_task` | 今日无签到记录 | 1 | 0 |
| 1 | `success` | 签到成功 | 0 | 不产生 |
| 2 | `already_checked` | 今日已签到 | 0 | 0 |
| 3 | `login_failed` | 登录失败 | 1 | 1 |
| 4 | `data_error` | 网络错误或数据异常 | 1 | 1 |
| 5 | `on_leave` | 请假中，跳过打卡 | 0 | 0 |
| 6 | `probe_pending` | probe 发现待签到任务，未提交 | 不产生 | 0 |

正式运行只把 1、2、5 视为正常终态；probe 把 0、2、5、6 视为正常只读结果。

## 环境变量

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `SWUDK_USERNAME` | 交互输入 | 校园网账号/学号 |
| `SWUDK_PASSWORD` | 无回显交互输入 | 校园网密码 |
| `SWUDK_MAX_ATTEMPTS` | `3` | 正式签到最大业务尝试次数；非法或非正整数回退默认值 |
| `SWUDK_RETRY_DELAY` | `8` | 第一次重试等待秒数，之后指数退避 |
| `SWUDK_PROBE_ONLY` | 未设置 | `1` 时兼容入口只运行 probe，并阻止显式 `run` |
| `SWUDK_STATUS_FILE` | 本地 run 不记录 | 正式运行的非敏感状态文件；也影响 POSIX token cache 所在状态域 |
| `SWUDK_LOCK_FILE` | 平台默认 | 正式 CLI 的绝对锁文件路径；相对路径会拒绝执行 |
| `XDG_RUNTIME_DIR` | 系统临时目录 fallback | POSIX 普通 CLI 默认锁目录 |
| `XDG_CACHE_HOME` | 平台用户 cache | POSIX token cache 根目录（未设置状态文件时） |
| `LOCALAPPDATA` | Windows 临时目录 fallback | Windows 安装、token cache 和锁目录 |
| `SWUDK_DEBUG_CREDENTIALS` | 关闭 | `1` 时输出不含凭据值的结构化诊断信息 |

systemd 还使用 notifier 专用变量，见 [服务器部署](../DEPLOYMENT.md)。

## 默认锁路径

- Windows：`%LOCALAPPDATA%\SWUCheckin\checkin.lock`；
- POSIX 且设置 `XDG_RUNTIME_DIR`：`$XDG_RUNTIME_DIR/swu-checkin.lock`；
- 其他 POSIX：系统临时目录下 `swu-checkin-<uid>.lock`；
- systemd：unit 显式设置 `/var/lib/swu-checkin/checkin.lock`。

锁只保护正式 CLI。`setup`、`doctor`、`status`、`probe` 和 `SWUDK_PROBE_ONLY=1` 不加锁。

## Python API

已有公共函数签名保持兼容：

```python
import os

from swu_checkin import check_in, probe_check_in

status = probe_check_in(
    os.environ["SWUDK_USERNAME"],
    os.environ["SWUDK_PASSWORD"],
)
```

公共 API 返回 `CheckinStatus`。自动化 shell 或 workflow 更推荐使用 CLI schema v1，以便同时获得 attempts 和 duration。
