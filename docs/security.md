# 安全模型

## 威胁边界

项目处理校园账号、认证 session 和学校返回的宿舍/任务数据。安全目标不是“任何异常都尽量提交”，而是只有在身份、请假、任务、payload 和结果均可安全确认时才继续。

项目不提供 GPS/位置伪造、反检测或风控绕过、认证绕过、凭据收集或远程托管，也不对未知响应结构做猜测式兼容。

## 凭据

- 本地交互通过 `input()` / `getpass()` 获取，不保存密码；
- GitHub Actions 使用 Repository Secrets；
- Windows 使用当前用户、当前机器绑定的 DPAPI 密文；
- systemd 使用 `/etc/swu-checkin/credentials.env`，要求 `0600 root:root`；
- 凭据、验证码、token、ticket、OAuth state/code 不得进入 Git、Issue、PR、截图或日志。

## OAuth/CAS

登录链从可信 SWU HTTPS 响应逐跳发现 redirect、state、form 和 hidden input，并校验主机、协议、端口、路径和参数唯一性。未知主机、降级请求、异常端口或歧义字段都会失败，不回退到猜测 URL。

精确规则见 [OAuth 登录发现说明](oauth-login-discovery.md)。

## TokenStore

- cache 只保存已验证 session，不保存密码；
- POSIX 文件原子写入并使用 `0600`；Windows 内容使用 DPAPI；
- cached token 每次使用前仍验证身份与请求学号；
- 正式签到只在**提交前只读阶段**收到明确 HTTP/业务码 401/403 时清 cache 并 fresh-auth 一次；
- schema、JSON、超时、网络错误和未知业务响应不会被误判为 session 失效；
- `probe`、`doctor` 和 `setup` 不刷新认证状态。

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
