# 故障排查

先记录版本/tag 或 commit SHA、平台、运行方式、北京时间、业务状态码、进程退出码和安全 `stage`。不要记录账号值、密码、token、验证码、ticket、完整回调 URL、宿舍地址、坐标或原始 API body。

本文以所在源码 commit 为准。当前 Python 版本为 **2.1.0 预发布版**，最新稳定版本仍为 v2.0.0；报错时同时核对 tag/commit、实际包和签名。公开资产以 [v2.1.0 发布页](https://github.com/Maximora-byte/swu-checkin/releases/tag/v2.1.0) 为准，平台交付与待验项见 [发布准备](releases/release-readiness.md)。

## 基础检查顺序

在已经安装命令的环境执行；源码环境可在命令前加 `uv run --locked --no-dev`：

```bash
swu-checkin --help
swu-checkin status
swu-checkin doctor
swu-checkin probe
```

普通本地 run 默认不写状态，第一条状态查询可能没有记录；需要时使用 `status --file PATH`。systemd 部署再检查：

```bash
systemctl status swu-checkin.timer --no-pager -l
systemctl status swu-checkin.service --no-pager -l
sudo journalctl -u swu-checkin.service -n 100 --no-pager
sudo -u swu-checkin /opt/swu-checkin/.venv/bin/swu-checkin status --file /var/lib/swu-checkin/status.json
```

`doctor` 使用 fresh authentication，不读写 token cache；认证通过后分别检查请假、学生、宿舍和任务接口，全部检查通过才退出 `0`。它不表示现在有任务或本人在寝。`probe` 不提交签到或写正式运行状态，但可能更新初始身份校验失效的 cache；业务读取阶段才失效的 cache 不自动恢复。二者不会获取正式运行锁。

## 状态码 3：登录失败

账号凭据被拒绝、验证码识别/校验最终失败会映射为 3。先检查凭据来源和 Secret/环境变量名称，再在学校官方入口确认账号能否正常登录；不要凭一个聚合状态断言账号锁定或密码一定错误。

Windows DPAPI 解密问题属于本地凭据加载问题，不一定产生业务状态 3。任务必须由保存密文的同一 Windows 用户运行；若界面提示无法解密，应在该用户下重新保存，不能复制其他机器的密文。

不要通过命令行参数直接写密码。CLI 的 `setup` 总是交互读取账号密码；其他业务命令优先读环境变量，缺项才询问。凭据拒绝和最终验证码失败不会由外层业务重试反复尝试；验证码内部仍有有限重试。

## 状态码 4：网络错误或数据异常

状态 4 是 fail-closed 聚合状态，不等于“重试一定能解决”。可能来自：

- 网络 timeout、DNS、TLS、连接错误或学校 HTTP 异常
- 非 JSON、缺字段、schema 或 OAuth/CAS 登录链变化
- ticket/token 交换或身份绑定校验失败
- 请假分页完整性、任务、宿舍或提交结果无法安全确认
- cached session 在业务接口失效，且当前模式不允许恢复或恢复后仍失败

先看阶段，再运行一次只读诊断；不要连续手动正式运行：

| 安全阶段 | 对应边界 | 建议 |
| --- | --- | --- |
| `auth` | fresh authentication / OAuth/CAS | 检查官方登录与网络；仅提供脱敏认证结构 |
| `token_validation` | token 的学生身份校验 | 对比 fresh-auth 的 `doctor` 与使用 cache 的 probe；不要贴 token |
| `leave` | 请假读取、分页和策略 | 未确认完整性或状态时不会假定无请假 |
| `transition` | 今日任务读取与待签到校验 | 无任务是 code 0；非法任务结构是 code 4 |
| `student_profile` / `dormitory` | 构造提交前的学生/宿舍校验 | 结构不明时停止，不手改 payload |
| `submit` | 签到表单提交 | 可能已到学校，先看回查结果，勿立即重复提交 |
| `confirm` | 提交后的只读状态确认 | 未确认不代表学校一定没收到；等待并只读核实 |

正式调用默认最多 3 次外层尝试，只对无任务、认证网络分类和提交前可识别的瞬时传输错误重试；schema、JSON、未知业务结构及非瞬时业务错误不会盲目重试。完整规则见 [CLI 参考](cli-reference.md)。

不要把所有数据错误都解释为 token 失效。初始身份校验可以处理明确 token 拒绝/账号绑定不一致；通过初始校验后的 cached session 只有在提交前收到明确 HTTP 401/403 或顶层业务 `code` 401/403 时，正式流程才清 cache 并 fresh-auth 一次。若旧发行版不含当前修复，升级时应一起更新代码、文档和锁文件；不要仅手动清除所有状态。

## 安全诊断如何解读

普通 CLI 的业务诊断通常在 stdout；使用 `--json` 时重定向到 stderr。`stage` 与分类一起解释，不能把 `stage=leave` 的 timeout 当成表单已提交。

| 日志分类 | 含义 | 建议 |
| --- | --- | --- |
| `请求超时` / `连接异常` | 当前阶段的传输失败 | 若在 submit，结果可能不明确；先看回查，不立即连跑 |
| `HTTP 503` 等 HTTP 状态 | 当前阶段收到该 HTTP 状态 | 等待恢复；不附异常正文或完整 URL |
| `业务码已返回` | 可分类响应存在 `code/status`，但最终未确认成功 | 原值有意隐藏；不能据此推断具体学校错误，也不能断言该字段本身一定是失败码 |
| `显式失败标志` | 响应给出可识别的失败标志 | 运行只读诊断，不改 payload |
| `缺少明确业务码或成功标志` | 响应不能提供明确业务成功信号 | 以远端回查为准；未确认时失败 |
| `响应结构异常` / `数据结构异常` / `宿舍数据结构异常` | 当前数据不符合受支持结构 | 只报告字段名/类型等结构信息 |
| `JSON 解析异常` / `数据解析异常` | 当前响应无法按预期解析 | 保留阶段与分类，不粘贴正文 |

同一次正式业务调用最多一次**签到提交 POST**。请求异常和可解析的提交响应会走最多 4 次只读回查；提交解析/结构异常也可能直接失败，不保证回查。无论哪种提交结果，都不通过 outer retry 再提交；认证、查询和回查本身的 HTTP POST 不等于签到提交。后续独立调用仍可能重新提交，所以“同一次最多一次”不是跨调用幂等承诺。

业务码可能承载 token、session 或账号标识。即使它看似短数字或普通英文，也不应记录、哈希或部分遮罩。不要为排查问题打开 HTTP 全量抓包或输出原始响应到 Issue。

## probe、doctor 与正式运行结果不同

- `probe` 复用可用 cache，也可能在初始身份校验失败时删除/替换它；不恢复后续业务失效的 cache
- `doctor` fresh-auth、不读写 cache，检查全部只读接口；没有今日任务或有效请假也可通过接口检查
- 正式运行可对提交前业务阶段失效的 cached session 做一次受限恢复，并按允许类型重试
- 正式 CLI/桌面运行受共享锁保护；probe/doctor 不受该锁影响

probe 返回 `[6] 检测到待签到任务（未提交）` 只是检测结果。`[5] 请假期间无需签到` 或 `[2] 已签到` 会提前结束，不代表本次检查了所有后续宿舍字段。需要完整诊断时使用 `doctor`。

## “已有签到任务正在运行，本次跳过。”

另一个正式 CLI 或桌面调用已占用同一路径的锁。当前 CLI 在读取凭据、访问学校和写状态之前退出 `0`，stderr 输出该固定消息，stdout 为空；`run --json` 也没有 JSON。这个 no-op 不代表本次签到成功。等待原任务完成后读取状态；不要删除正在使用的锁文件。

systemd 使用 `/var/lib/swu-checkin/checkin.lock`；普通 POSIX CLI 使用 `$XDG_RUNTIME_DIR/swu-checkin.lock` 或临时目录中带 uid 的路径；Windows 默认 `%LOCALAPPDATA%\SWUCheckin\checkin.lock`。`SWUDK_LOCK_FILE` 必须为绝对路径。想协调多个入口时应使用同一锁路径，跨机器或不同锁路径不能互斥。

“无法安全获取签到运行锁，本次未执行。”表示锁路径/权限等本地保护无法成立，退出 `1` 且无业务 JSON。检查目录权限、相对路径、符号链接等，不要绕过锁。桌面冲突呈现方式与 CLI 不同，桌面定时入口异常退出 `1`。

## `run --json` 没有输出，或退出 0 却没签到

先区分锁占用 no-op、锁错误和业务结果。显式 `run` 被 `SWUDK_PROBE_ONLY=1` 阻止时退出 `2`；无子命令兼容入口在相同变量下运行 probe。参数错误也退出 `2`，没有结果文档。`--json` 不会禁止交互，缺少凭据仍会等待输入。

JSON 中 `code` 与进程退出码是不同概念；code 2 的英文名称为 `already_checked_in`。不要用 `tail -1` 猜结果。完整字段与例外见 [CLI 参考](cli-reference.md)。

## status 没有状态或与本次结果不同

普通本地 CLI run 默认不记录状态；设置 `SWUDK_STATUS_FILE` 后才记录。`status --file PATH` 优先于环境变量；无两者时查询 `/var/lib/swu-checkin/status.json`。Windows 桌面正式结果在 `%LOCALAPPDATA%\SWUCheckin\status.json`，macOS 桌面则在 `~/Library/Application Support/SWUCheckin/status.json`，均不采用 CLI 的状态路径覆盖。Android 客户端不写这两种桌面状态文件，需在客户端重新查询学校端结果。

`status` 只读文件，不发网络请求。文件按上海日期保存最近最多 10 条正式调用，内部重试不是独立记录；聚合“成功”表示保存的这些记录中曾出现成功终态，不一定是最近一次。缺失文件退出 `0`，损坏/不可读退出 `1`；日期会原样显示，不会自动过滤或刷新旧日期。

本地保存失败不会改变已经返回的远端结果；CLI/桌面会给出安全提示。不要因磁盘、权限或坏状态文件导致的警告盲目重复签到。桌面定时另有 `desktop-last-run.json` 保存最近一次非敏感结果，包括 probe；它不等同于正式状态文件。

## GitHub Actions 延迟

GitHub cron 不保证准点。先查看 workflow 的实际开始时间，不要把排队延迟当成脚本未触发；仓库现有 workflow 的手动触发也会执行正式签到，并没有 probe 模式；具体触发与通知规则见 [GitHub Actions 指南](../GITHUB_ACTIONS.md)。严格时间窗口应选择合适的常在线运行环境，任何部署仍受网络和学校服务影响。

当前 workflow 已修复“成功业务 JSON 配合非零退出码仍显示正常”的判定边界。只有执行 step 成功、CLI 退出 `0` 且结构校验后的正式业务码为 `1`、`2` 或 `5`，才跳过异常通知并让最终检查通过。任何一项不成立，均按异常处理；邮件缺少配置或发送失败不会改写签到的失败结论。旧 v2.0.0 tag 未包含 [PR #42](https://github.com/Maximora-byte/swu-checkin/pull/42)，升级 fork 时应同步完整 workflow 与源码，而不是只拷贝 JSON 解析器。

## Windows 任务：Desktop 与旧版 Daily

图形桌面版任务叫 `SWUCheckin-Desktop`，旧 PowerShell 安装方案叫 `SWUCheckin-Daily`。查看对应任务，而不是只查旧名：

```powershell
Get-ScheduledTask -TaskName "SWUCheckin-Desktop"
Get-ScheduledTaskInfo -TaskName "SWUCheckin-Desktop"
# 仅在排查旧版安装或冲突时查询：
Get-ScheduledTask -TaskName "SWUCheckin-Daily"
```

确认当前用户、运行程序路径、任务模式和下次触发时间。用户需已登录，电脑需开机联网；睡眠/关机不保证执行。开启桌面定时前如检测到旧 Daily 任务，应按提示核对并移除旧任务登记、保留账号配置，避免两套定时同时运行；程序不会擅自迁移或删除旧任务。

### “无法确认计划任务状态” / “计划任务最终状态无法确认”

这表示未知，不能解释为任务已不存在或已关闭。当前实现通过 Task Scheduler COM 查询精确根任务，仅在 `GetTask` 明确返回文件不存在时认定缺失；访问拒绝、调度服务/COM 故障、超时、额外 stderr 或无法识别的结果都保守失败。它不解析本地化错误文本来猜测“未安装”。

创建/删除任务失败后还要核实任务与本地配置；无法确认最终状态时，定时控件停留未知并禁用。请：

1. 在 Windows“任务计划程序”检查精确任务名和实际启用状态；不确定时不要以为自动模式已停用
2. 检查当前用户权限、Task Scheduler 服务、PowerShell/COM 可用性，以及本地配置是否损坏
3. 核实期望状态后重新打开应用，触发只读本地查询；不要连续点创建/删除或通过删配置文件伪装关闭
4. 若仍未知，报告版本、Windows 版本、查询/启停哪个步骤失败和固定错误提示，勿附凭据或完整任务/配置转储

当前离线测试与 Windows CI 覆盖了相应分支，但不能保证所有 Windows 权限、语言、账户或环境都不会误报。部署和验收边界见 [Windows 桌面版](windows-desktop.md) 与 [旧版 Windows CLI](windows.md)。

## 安全提交 Issue

Issue 至少包含版本或 commit SHA、系统与 Python 版本、部署方式、业务状态码、exit code、命令模式、稳定复现步骤，以及固定阶段、字段名/类型、HTTP 状态或异常类型等脱敏信息。

提交入口：[Maximora-byte/swu-checkin/issues](https://github.com/Maximora-byte/swu-checkin/issues)。

## macOS 预览与钥匙串

- 启动不会读取已存账号；须显式点击“读取已存账号”
- 钥匙串取消、锁定、拒绝或不可用是本地存储状态，不代表学校账号错误；不会回退到明文保存。清除时失败不会宣称已删除
- token 仅在窗口进程内存；正式结果位于 `~/Library/Application Support/SWUCheckin/status.json`
- 没有后台任务、开机自启或自动签到；`--scheduled` 不受支持
- 未签名身份/未公证警告不应通过关闭系统保护绕过；具体系统与架构、CI artifact、官方安全链接见 [macOS 桌面指南](macos-desktop.md)

## Android 手动预览

- 仅支持 Android 7.0 / API 24 及以上的 arm64-v8a、x86_64；32 位设备没有当前 APK 对应的原生运行库
- 区分 0.1.1-preview canonical 持久签名候选和 `.feasibility` CI debug 验证；新正式包不是旧 debug 的覆盖升级，原账号须重输。版本/包名可在系统应用信息核对，签名和来源看该包报告；不因安装失败删除已有账号或擅自换证书
- 人工输入验证码；账号/验证码界面禁止截图是设计保护，不应关闭保护排障
- 应用启动不联网、不自动读取保存账号。需要显式输入，或点击“读取已保存账号”后查询；查询与只读诊断不会提交签到
- 验证码超时、取消或切到后台后，请重新发起操作获取新的挑战，不复用旧图或旧输入。软键盘遮住按钮时向下滚动；当前修复会为键盘留出空间
- 保存账号由设备 Android Keystore 保护；卸载、应用数据清除、密钥丢失或密文损坏后不能保证恢复。不要复制密文到另一设备，也不要因读取失败转为明文保存
- 只有待签到状态可进入正式确认；必须确认本人在寝且符合规则。提交后结果未知时先查询学校状态，不连续重发
- 历史 debug 本机 63 项/云端 63 项保留，当前持久签名候选须看自己的 20 项/行报告；学校业务仍使用合成响应。真实学校账号、实际签到和 16 KB 真机未验收，模拟器和对齐检查不代表实体设备通过

安装、验证码与保存/清除操作见 [Android 客户端指南](android-client.md)。反馈时仅提供 Android 版本、设备型号、应用构建来源、操作步骤和固定错误提示；不要公开账号界面、验证码、学校响应或设备完整日志。
