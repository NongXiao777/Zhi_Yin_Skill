# 原生登录窗口与会话桥：IDA 分析交接

目标一：agent 能呼出厂商原生登录窗口，用户只在窗口内输入密码，成功后生成受保护的 CLI 会话。目标二：已有原生窗口登录成功后，CLI 能接续授权会话。两项都尚未完成端到端验证。

请分析实际安装的 `%LOCALAPPDATA%\Programs\ZYing`，不要混用 `D:\ZYing` 历史版。2026-11-26 16:28 当前版本：

| DLL | SHA256 |
|---|---|
| ZYing.Work.dll | `1259DF6CF6CBDC25823DE8CB443C2F1E268661696A7BD143327099F761824BAC` |
| ZYing.User.dll | `39A236334049F0A92626D7CF49CAE08F9DB0416CD7B27D92DEF4C98292F99858` |
| ZYing.Core.dll | `7AB55921D976D04DDB5163B5034764DB78B37A188276DCE44EC0E0924EC96F34` |

## 1. 如何创建或重新呼出原生登录窗口（优先）

在 `ZYing.User.dll` 看以下入口及调用者，给出最小可行调用顺序、线程要求、初始化依赖和退出条件：

| 类型/方法 | 当前 RVA |
|---|---:|
| `ZYing.Global.ShowLogin()` → `ApplicationContext` | 113276 |
| `ZYing.Global.Start(string, Image)` | 112128 |
| `ZYing.Global.Start(Guid)` | 114212 |
| `ZYing.Global.ShowMainForm(bool)` | 113432 |
| `ZYing.Global.ShowForm(Form)` | 114028 |
| `ZYing.MLogin.get_Instance()` | 132944 |
| `ZYing.MLogin..ctor()` | 132988 |
| `ZYing.MLogin.OnLoad(EventArgs)` | 133496 |
| `ZYing.MLogin.OnVisibleChanged(EventArgs)` | 133892 |
| `ZYing.MLogin.登录()` → `<登录>d__14.MoveNext` | 135384 |
| `ZYing.MLogin.验证()` → `<验证>d__15.MoveNext` | 136148 |
| `ZYing.FlashForm.Start()` | 100408 |

确认能否在独立 .NET 6 Windows Desktop/STA 宿主直接调用 `Application.Run(Global.ShowLogin())`，需要先设置哪些 `AppConfig/Global/UI` 项，成功后如何接收通知而不强制创建整个分销主窗口。也查 `ZYing.Program.Main` 是否存在命令行参数、单实例 IPC、窗口消息、插件回调或其他入口，可以让现有进程显示 `MLogin.Instance`。不要为了呼出登录清空已有账户或修改保存密码配置。

用户平时只输入密码，手机号由原生窗口记住。请核对 `MLogin.OnLoad` 与 `<登录>d__14` 普通账号分支：账号字段是否还有区号/站点/公司选择，`rEI` 的服务器选择怎样影响 `HBQ2`，另一个择远分支何时生效。已观察普通登录发送 `common.login`，有 `login_acc/login_pwd`，密码调用 `Safe.Encrypt(string)`。

## 2. 成功后导出哪些会话状态，才能被 CLI 复用（优先）

在 `ZYing.Work.dll` 看：

- `ZYing.Member.Parse(Record)`，RVA `1588608`；明确 `Token/UserID/LoginID/Auth` 的来源，哪些是 TCP 会话必须项。
- `cBSF.ABSs` 的 `.cctor`、`Create`、`LBgK(byte[])`、`<ConnectAsync>d__77`、`<Init>d__73`；默认服务器 `HBQ2` 和产品操作选择哪个池。
- `sBeW`（静态设备 Guid）、`BBeQ`（交换状态）、`QBer`（当前版本 12980）、`Member.Token` 在帧中怎样使用，跨进程复用是否允许，token 是否与设备/连接/服务器绑定。
- 成功回调能否直接输出 `server_address/server_port/token/user_id` 及必需的设备或交换状态，并立即 DPAPI 加密。只输出字段名与必要调用链，不提供真实值。

当前 CLI 已支持可选 `device_id/exchange_state` 并有原生回环测试；真实桌面 token 经只读字段读取后，用独立 TCP 查询先返回 `session_rejected (-9)`。重新按 Guid 子字段读取后错误变成 `unexpected_detail_shape`，这提示最初 Guid 读取方法可能不正确，但不证明会话已完整可用。请优先提供成功后最小会话初始化链，避免基于这些现象推断。

## 3. 真实商品详情为何不是合成测试里的单行 root（次优先）

检查 User 的 `ZYing.Detail.Sale.Load/Read`，`spider.detail` 的响应 RecordSet 名称与 `root` 形状。当前 `NativeTransport.ResultRecord` 假定 `root.ToJson()` 是只含一个对象的 JSON 数组；真实请求返回 `unexpected_detail_shape`。需要确认合法空值、分页/多行/对象结构、不同商品来源分支、公司/用户过滤与产品服务器选择。

最小提交字段和保存后的审核状态另有任务：商品 `951393413` 的两个变体各加价 `0.01`，英文介绍追加 `*`。本次尚未写入。登录和只读详情确认之前不要用保存测试接口。

## 交付格式

请给：DLL 哈希、类型和方法签名/RVA、脱敏伪代码或调用链、必要初始化字段名、可实现的宿主/IPC方案，以及需更新的 `client-profiles.json` 符号。无需真实手机号、密码、token、完整响应、内存转储或厂商 DLL 本体。动态验证如涉及 token，直接在本机加密保存，普通日志只写布尔状态和错误码。
