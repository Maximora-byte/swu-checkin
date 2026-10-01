# 安全模型

## 威胁边界

项目处理校园账号、认证 session 和学校返回的宿舍/任务数据。安全目标不是“任何异常都尽量提交”，而是只有在身份、请假、任务、payload 和结果均可安全确认时才继续。

本工具不测量实际 GPS。现有提交 payload 使用学校宿舍坐标，且包含固定的 GPS/范围字段，这些字段不能证明本人当前在寝。仅应在申报真实且符合学校规则时正式提交；桌面自动模式默认关闭，启用前明确告知并单独确认，不满足条件时应提前停用。项目不扩展定位绕过、反检测、认证绕过或远程凭据托管，也不对未知响应结构做猜测式兼容。

## 凭据

- 本地交互通过 `input()` / `getpass()` 获取，不保存密码；
- GitHub Actions 使用 Repository Secrets；
- Windows 使用当前用户、当前机器绑定的 DPAPI 密文；
- systemd 使用 `/etc/swu-checkin/credentials.env`，要求 `0600 root:root`；
- 凭据、验证码、token、ticket、OAuth state/code 不得进入 Git、Issue、PR、截图或日志。

## OAuth/CAS

登录链从可信 SWU HTTPS 响应逐跳发现 redirect、state、form 和 hidden input，并校验主机、协议、端口、路径和参数唯一性。未知主机、降级请求、异常端口或歧义字段都会失败，不回退到猜测 URL。

精确规则见 [OAuth 登录发现说明](oauth-login-discovery.md)。

业务接口和 token exchange 也禁用自动重定向并拒绝 3xx，避免自定义认证头或签到表单被转发到非预期地址。

## TokenStore

- cache 只保存已验证 session，不保存密码；
- POSIX 文件原子写入并使用 `0600`；Windows 内容使用 DPAPI；
- cached token 每次使用前仍验证身份与请求学号；
- 正式签到只在**提交前只读阶段**收到明确 HTTP/业务码 401/403 时清 cache 并 fresh-auth 一次；
- schema、JSON、超时、网络错误和未知业务响应不会被误判为 session 失效；
- `doctor` 和 `setup` 不读写 TokenStore；`probe` 会复用有效 cache，身份校验明确失效时可 fresh-auth 并替换它，但不会恢复业务读取阶段才失效的 cached session。

## 提交安全

正式流程先完成请假、学生、宿舍和任务读取，再构造 payload。提交后必须回读确认学校状态已经变化。

如果 POST 发生 timeout、连接中断、HTTP 5xx 或其他结果不明确的失败，客户端不会清 token、重新登录并发送第二次 POST。这样保留“可能已经被服务器处理”的事实，避免重复提交。

## 并发

正式 CLI 在读取凭据和访问远端前获取跨进程非阻塞锁：

- POSIX 使用 `fcntl.flock(LOCK_EX | LOCK_NB)`；
- Windows 使用 `msvcrt.locking(..., LK_NBLCK, 1)`；
- 锁文件不保存 PID、账号、token、payload 或业务状态；
- 第二个正式进程立即本地跳过；
- probe/doctor/setup/status 不加锁。

## 状态与日志

`status.json` 只记录日期、状态码、消息和时间等非敏感运行结果。systemd 部署通过专用用户、`UMask=0077` 和受限状态目录保护文件。

日志只允许输出固定异常分类或脱敏结构信息。传输失败可记录 `请求超时`、`连接异常` 或 HTTP 状态；业务响应只记录“业务码已返回”“显式失败标志”等固定分类。未知 `code/status` 即使满足长度、数字或字符集约束，也不会记录原值、哈希、前后缀或部分遮罩，因为它可能是 token、session 或账号标识。

报告问题时不要附原始 API body、response message、完整回调 URL、宿舍地址、房间、坐标或任何认证材料。

## 第三方与责任

这是非官方社区工具，学校接口随时可能变化。运行者负责保管凭据、选择部署环境并遵守学校规则。仅支持当前仓库的 `main` 和明确发布版本；降低上述安全边界的 fork 不在支持范围内。

## Windows 桌面版

- 双击只打开界面；本地恢复配置不连接学校服务。
- 只有显式保存才将账号与密码写入当前 Windows 用户绑定的 DPAPI 密文，不进入任务参数或日志。DPAPI 无法防御同用户恶意程序或管理员在运行时读取秘密。
- GUI 正式签到与 CLI 使用同一跨进程运行锁；只读检测不提交。
- 定时模式默认关闭，可选择只读检测或正式签到；启用时检测已保存账号。已启用时修改凭据须先关闭任务，避免无意替换自动执行的账号。
- 安装器不启用定时任务；卸载器移除本桌面版任务，保留个人配置。发布前须在干净 Windows 实机验证冻结程序、DPAPI、计划任务及升级卸载。
