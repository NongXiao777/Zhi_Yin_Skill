# 原生登录窗口与会话桥：IDA 分析交接

验证更新（2026-11-26）：目标一已由 `login-native` 完成动态验证，原生窗口登录成功后保存 DPAPI 会话，独立 CLI 使用 `sale.detail` 读到“我的产品”记录。`Global.ShowLogin()` 会运行更新检查，实际宿主直接创建 `MLogin.Instance` 并设置 Context。目标二也已验证：现有桌面进程定向读取 token、用户、设备、交换状态和实际默认服务器池，立即加密后成功读取同一商品；尚未封装为稳定命令。以下保留分析入口，用于后续版本和现有窗口接管。

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
| `ZYing.MLogin.验证()` → `<验证>d__16.MoveNext` | 136148 |
| `ZYing.FlashForm.Start()` | 100408 |

确认能否在独立 .NET 6 Windows Desktop/STA 宿主直接调用 `Application.Run(Global.ShowLogin())`，需要先设置哪些 `AppConfig/Global/UI` 项，成功后如何接收通知而不强制创建整个分销主窗口。也查 `ZYing.Program.Main` 是否存在命令行参数、单实例 IPC、窗口消息、插件回调或其他入口，可以让现有进程显示 `MLogin.Instance`。不要为了呼出登录清空已有账户或修改保存密码配置。

用户平时只输入密码，手机号由原生窗口记住。请核对 `MLogin.OnLoad` 与 `<登录>d__14` 普通账号分支：账号字段是否还有区号/站点/公司选择，`rEI` 的服务器选择怎样影响 `HBQ2`，另一个择远分支何时生效。已观察普通登录发送 `common.login`，有 `login_acc/login_pwd`，密码调用 `Safe.Encrypt(string)`。

## 2. 成功后导出哪些会话状态，才能被 CLI 复用（优先）

在 `ZYing.Work.dll` 看：

- `ZYing.Member.Parse(Record)`，RVA `1588608`；明确 `Token/UserID/LoginID/Auth` 的来源，哪些是 TCP 会话必须项。
- `cBSF.ABSs` 的 `.cctor`、`Create`、`LBgK(byte[])`、`<ConnectAsync>d__77`、`<Init>d__73`；默认服务器 `HBQ2` 和产品操作选择哪个池。
- `sBeW`（静态设备 Guid）、`BBeQ`（交换状态）、`QBer`（当前版本 12980）、`Member.Token` 在帧中怎样使用，跨进程复用是否允许，token 是否与设备/连接/服务器绑定。
- 成功回调能否直接输出 `server_address/server_port/token/user_id` 及必需的设备或交换状态，并立即 DPAPI 加密。只输出字段名与必要调用链，不提供真实值。

当前 CLI 支持可选 `device_id/exchange_state` 并有原生回环测试。独立合成进程确认 ClrMD 的 `ClrStaticField.Read<Guid>` 会读错静态 Guid；需 `ReadStruct` 再读取 `_a..._k`。真实进程使用此方式、读取 `HBQ2` 的实际 endpoint 后，CLI `sale.detail` 查询已成功。仍建议直接在原生窗口宿主的同一进程读取会话，避免额外诊断依赖。

## 3. 详情响应已确认的来源与形状

“我的产品”构造 Sale 时前缀是 `sale`，所以使用 `sale.detail`；“产品采集”前缀是 `spider`。此前对“我的产品”编号调用 `spider.detail` 的已认证响应 root 为零行。当前解析支持普通数组和分页对象的 `data` 数组，对空记录明确返回 `product_not_found`，仍核对单行与 sale_id。`Record.ToJson` 不需手工重置游标。

保存路径已补正：CLI 外层和详情查询参数仍为 `id`，实际传给 `bBge` 的 outgoing Record 使用 `sale_id(Int32)`。状态机的另一份 callback Record 使用 `id`，只用于保存后的本地 `ISource.Update/Insert`；`thumb/cost/title` 也属于回调，不应猜测补入线上字段。执行器保持同源流程：`sale.detail → sale.update → sale.detail`，或 `spider.detail → spider.update → spider.detail`。

“我的产品”用 `product-live-edit`，产品采集用 `collected-product-live-edit`。完整 `sale_stock` 只修改已选变体，完整 `sale_intro` 只修改指定语言；最小载荷的服务器接受情况和其他状态变化以当前任务的授权保存、读回核验为准。不要重复执行结果未确认的加价或追加文字。

## 交付格式

请给：DLL 哈希、类型和方法签名/RVA、脱敏伪代码或调用链、必要初始化字段名、可实现的宿主/IPC方案，以及需更新的 `client-profiles.json` 符号。无需真实手机号、密码、token、完整响应、内存转储或厂商 DLL 本体。动态验证如涉及 token，直接在本机加密保存，普通日志只写布尔状态和错误码。
