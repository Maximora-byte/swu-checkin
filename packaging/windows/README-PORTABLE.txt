SWU Checkin · Windows x64 免安装预览版
====================================

这是完整应用目录的 ZIP，不是单文件 EXE，也不是 GitHub 的 Source code ZIP。
无需安装 Python、uv、OCR 模型或安装程序，无需以管理员身份运行。
目标平台为 Windows 10/11 x64；当前自动验收是 Windows Server 2022 x64，
不代表已完成干净 Windows 10/11 实机验收。ARM64、32 位系统未验收。

开始使用
--------
1. 只从 https://github.com/Maximora-byte/swu-checkin 下载，核对可信渠道的 SHA256。
2. 右键 ZIP →“全部解压缩”，放到当前用户可访问的本地目录。
3. 打开解压后的 SWUCheckin 文件夹，双击 SWUCheckin.exe。
   必须保留整个文件夹（包括 _internal）。不要只复制 EXE，不要在 ZIP 预览中运行。
4. 默认打开中文窗口，只读取本地状态，不登录、不联网、不提交签到、不新建计划任务。
   不需要执行任何 .ps1、pip、uv 或安装命令。

当前构建未签名。校验值和 BUILD-INFO.json 提供完整性/来源信息，不是数字签名。
若 Windows、SmartScreen 或单位安全策略阻止运行，请停止并核实来源、向维护者报告；
不要关闭安全防护、修改执行策略或绕过安全警告。构建/下载来源见上面的官方仓库。
本说明随当前源码构建的 Portable.zip 分发；已发布 v2.0.0 的原始 win-x64.zip
不包含所有后续改动。当前候选源码已提升到 2.1.0，仍须核对 commit 和 SHA256。
各平台与下一版发布条件：https://github.com/Maximora-byte/swu-checkin/blob/main/docs/releases/release-readiness.md

账号、数据与“便携”的边界
----------------------
免安装指应用文件可解压运行，不代表账号数据跟随文件夹跨电脑使用。
配置、状态与加密凭据仍保存在 %LOCALAPPDATA%\SWUCheckin，通常不会写入应用目录。
只有显式“保存账号”才持久保存账号和密码；Windows DPAPI 绑定当前 Windows 用户。
复制应用文件夹到另一台电脑/另一 Windows 用户后，应重新输入并按需保存账号。
不要复制、分享或上传 desktop-credentials.dpapi、auth-token-cache 或整个数据目录。
同一 Windows 用户下的安装版和免安装版共用这些数据与正式执行锁；请一次只用一份应用。
删除 ZIP/应用文件夹不会删除用户数据，也不会自动删除此前明确启用过的计划任务。

计划任务、移动与升级
------------------
计划任务默认关闭；打开免安装版不会自动启用或注册任务。
如已有经你授权的 SWUCheckin-Desktop 任务，它仍可能运行；关闭窗口不等于关闭任务。
若使用定时功能，请选固定的本地目录。任务引用启用时的 EXE 绝对路径，不会跟随移动。
移动、重命名、升级、删除应用目录，或在安装版/免安装版间切换前：
  - 先在旧程序中关闭每日计划任务，并在 Windows 任务计划程序确认已删除
  - 如任务状态未知或无法关闭，先停止操作并核实；不要把未知状态当作已关闭
  - 关闭全部程序，完整解压新包到新目录，不要边运行边覆盖或混用不同版本的 _internal
  - 新目录运行正常后再删除旧目录；需要定时功能时重新明确启用，并核对任务动作路径
新程序不会替你迁移或重注册任务。旧路径失效时任务会失败，旧副本仍在时可能继续运行。
没有计划任务时，可关闭应用后移动整个文件夹，再从新路径打开。

使用约束
--------
建议先只读检测；正式签到每次手动确认，自动签到需单独授权。
本工具使用学校记录的寝室坐标，不测量真实 GPS，不证明本人在寝。
仅在本人确实在寝且符合学校规则时执行正式签到。
请勿在问题报告、截图或日志中提供账号、密码、验证码、token、地址或坐标。

校验与来源
----------
包内 SHA256SUMS.txt 覆盖全部应用文件、本文及来源/许可材料（不包含清单自身）。
BUILD-INFO.json 记录源码 commit、是否有未提交修改、源码摘要、锁文件和依赖版本。
TOOLCHAIN.txt 记录构建工具链；LICENSE-INVENTORY.json 列出原文来源与逐文件 SHA256。
项目、实际 CPython/Tcl/Tk 和依赖（含内置第三方组件）的许可保留在包内。
构建和发布预检会拒绝缺失或被修改的许可文件。再分发请保留整个包。

完整说明：https://github.com/Maximora-byte/swu-checkin/blob/main/docs/windows-portable.md
故障反馈：https://github.com/Maximora-byte/swu-checkin/issues
