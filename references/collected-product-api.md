# 采集商品接口与原生 TCP 执行器

核验日期：2026-11-25。通过 IDA Pro MCP 和离线 .NET 元数据/IL 分析，检查了 `ZYing.User.dll`、`ZYing.Work.dll`、`ZYing.Core.dll`、`ZYing.UI.dll` 及智赢扩展 5.2.4。用户补充的脱敏分析所列 DLL 与当前安装版哈希不同。按安装版本核对混淆符号和字段映射。

**线上读写仍待验证。** 本机已确认当前智赢进程以普通权限运行，CLI 能识别进程，当时未发现进程监听的本地 TCP 端口。扩展 5.2.4 和已查看的厂商公开文档没有提供这些操作的授权接入方式。下面保留静态证据。本地文件工作流见 [商品预览](erp-products.md)。

## 命令行接入

内置执行器位于 `scripts/native/NativeTransport.cs`。它通过反射复用本机 `ZYing.Work.dll` 的 TCP 请求和响应代码，以及 `ZYing.Core.dll` 的 Record 编码。PowerShell 7 使用自身的 Roslyn 编译器将它编译到临时目录，再由已安装的 .NET 6 Windows Desktop Runtime 运行。`--app` 选择实际安装路径。

```powershell
python scripts/zhiying.py collected-transport-probe
```

该命令创建合成会话，验证原生组件加载和请求编码，返回 `network_requests_sent: 0`。原生回环测试还验证了五字节 TCP 包头和后续请求体，实际捕获了 `spider.detail` 和测试编号。真实记录仍需正常有效的登录会话。

会话由本地 `ZHIYING_SESSION_FILE` 指向的 JSON 提供，文件路径可使用 Git 已忽略的 `*.local.json`。字段为实际 `server_address`（IP）、`server_port`（整数）、`token`（正常登录取得的 GUID），以及可选的实际 `user_id`。凭据由执行器在本地读取。人工登录后的 `ZYing.Member.Token` 位于客户端进程内。另一套 Python 路径已实现 ClrMD 只读会话导出，但使用独立 DPAPI 文件，不能直接当成这个 C# 执行器的会话 JSON。见 [原生商品 CLI](native-cli.md)。

也可通过 `--transport` 指定另一个执行器，或设置 `ZHIYING_COLLECTED_TRANSPORT`。它遵循下方进程间契约。

当前版本的登录状态机发送 `common.login`，使用 `login_acc` 和 `login_pwd` 等表单列。代码中还有密码编码、数字登录号和强制改密码分支，完整登录请求仍待核对。`ZYing.Member.Parse(Record)` 负责写入会话 `Token`，它由 `ZYing.MPush.Deal` 调用。这些是登录流程定位，实账户的登录和会话交接仍待验证。

2026-11-26，Python 执行器对产品列表的 `sale.detail` 发起只读请求，收到客户端 GUID 和会话 GUID 匹配的 `c + metadataCount + Int32LE length` 响应，结果 `-9`，无商品 RecordSet。服务器提示同账户多次登录；用户反馈账号支持同时使用，故真实拒绝原因仍待核对。新导出的会话和当前默认远端均已一致性检查，不应靠猜端口、替换 GUID 或重复提交来隐藏此错误。本次没有保存商品。

```powershell
python scripts/zhiying.py collected-product-live-get --product-id 954521907 --include-copy
python scripts/zhiying.py collected-product-live-edit --product-id 954521907 --set-surcharge EXACT_KEY 1.00
python scripts/zhiying.py collected-product-live-edit --product-id 954521907 --copy-file copy.json
```

先读回记录并核对真实变体键。执行器经标准输入接收一个 UTF-8 JSON 对象，经标准输出返回一个 UTF-8 JSON 对象。凭据由执行器使用正常授权方式管理。

| CLI 发给执行器的请求 | 执行器的响应和责任 |
|---|---|
| `{"command":"spider.detail","id":954521907}` | `{"ok":true,"record":{...}}`。返回同一 `sale_id` 及现有语言和完整变体集合 |
| `{"command":"spider.update","id":954521907,"expected":{...},"fields":{...}}` | 校验 `expected` 中将要更改的字段基线，只保存 `fields` 中的字段。成功返回 `{"ok":true}`，冲突返回 `{"ok":false,"error":"conflict"}` |

上表定义 CLI 到执行器的请求。内置执行器已调用当前客户端编码器，并在保存前重新读取对比基线。服务端对会话和最小更新范围的接受情况仍待实账户核验。服务端原子条件更新能力未知，并发写入时应协调编辑时段。CLI 更新后会再次调用 `spider.detail`，逐个对比提交字段，只有匹配时才返回 `remote_read_back_verified: true`。若保存结果不明或读回失败，先重新读取现状。

当前安装版的五个原生字段已通过独立加载 User 程序集、求值 `GetTitle/GetBrief/GetKeys/GetBullet/GetIntro` 的字符串参数核实。CLI 直接读取并更新原字段，保留其他语言。兼容已有执行器返回的 `listing_copy` 映射。`sale_en` 保留报关英文简称用途。示例见 [修改标题与其他文案](erp-products.md#修改标题与其他文案)。

内置执行器按已核实的 Work 程序集 SHA256 匹配当前混淆符号。版本变化会返回 `unsupported_client_version`，需重新核对符号再更新。当前类型为 `ze53.Fe5b`，命令字段 `tei4`，详情方法 `lenP(string,int)`，记录提交方法 `Ren4(Record[])`。这些符号只适用于已匹配版本。

## 已有采集商品详情

```text
ZYing.User.dll
  ZYing.Channel.采集列表.DSBE(...)
  → new ZYing.Detail.Sale(..., "spider")
  → Sale.Load() / <Load>d__47.MoveNext()
  → ZYing.Channel.CLayer.Create(...)

ZYing.Work.dll
  → Ia3D.La3e.HaF1 = "spider.detail"
  → Ia3D.La3e.Ma3t("id", productId)
  → 参数编码 / TCP 请求与响应
  → Ia3D.La3e.xaFn() 返回 RecordSet

ZYing.User.dll
  → Sale.Read(RecordSet)
  → root 交给商品表单，stock 按 key 匹配并填充库存 num
```

`id` 是 `Int32` 产品编号；客户端从 `Control.Name` 经 `Valid.ToInt` 取得。`PostAsync` 是内部方法名，底层 `TcpClient.ConnectAsync`、`GetStream`、`Stream.WriteAsync` 和 `ReadAsync` 发送二进制数据，不能理解为 HTTP POST。

请求还需要正常登录会话、客户端标识与外层协议编码。命令名和参数名本身不构成可直接调用的公共 API。

## 字段与编码

| 内容 | 字段 | 已确认语义 |
|---|---|---|
| 商品编号 | `sale_id` | 商品记录编号；详情查询参数名为 `id` |
| 商品标题 | `sale_title` | 多语言 JSON 字符串 |
| 短标题 | `sale_brief` | 多语言 JSON 字符串 |
| 要点说明 | `sale_bullet` | 多语言 JSON 字符串，英文按换行组织 |
| 关键词 | `sale_keys` | 多语言 JSON 字符串 |
| 商品描述 | `sale_intro` | 包含多语言 JSON 对象的字符串列；英文语言码为 `en` |
| 包装毛重 | `sale_weight` | `Int32`，克 |
| 包装尺寸 | `sale_size` | 长、宽、高，厘米；UI 保存为逗号分隔字符串 |
| 成本单价 | `sale_cost` | 金额，不是分销价 |
| 分销单价 | `sale_price` | 未证明等同最终平台售价 |
| 商品币种 | `sale_cur` | 表单默认 `CNY`，不代表某条商品的实际币种 |
| 变体集合 | `sale_stock` | 包含完整 JSON 数组的字符串列 |

`sale_en` 是报关英文简称，不是商品英文描述。

`NMulti.ToJson()` 把语言码映射为文本。外层逻辑记录的形状例如：

```json
{"sale_intro":"{\"en\":\"new description\",\"zh\":\"保留的中文描述\"}","sale_size":"20,15,10"}
```

这只是字段编码示例，不是完整请求或真实商品响应。`Record.GetInts` 能解析字符串列，所以逻辑尺寸数组不代表线上保存为 JSON 数组。

`NStockCollection.ToJson()` 输出整个数组。每项实际写出的键为 `key/no/spec/num/weight/money/areas/pic`：

| 变体键 | 含义 |
|---|---|
| `key` | 客户端变体匹配键，映射 `NStock.Key` |
| `no` | 自定义 SKU，选填，映射 `NStock.No` |
| `money` | `Decimal`，界面名称为“加价” |
| `weight` | `Int32`，界面名称为“加重” |
| `spec/num/areas/pic` | 规格、库存、区域和图片相关值 |

当前 `NStock` 没有 `Id/VariantId/Currency` 字段，不能把 `key` 或 `no` 直接当平台数值变体 ID。解析兼容旧键 `add`，写回使用 `money`。空集合编码为空字符串；`money=0` 在完整快照编码中省略该键。这些规则不能证明服务端 PATCH 或清零语义。

一个扩展的 1688 货源核价分支使用 `sale_cost + money` 计算款式采购成本；这不能推广为 ERP 分销或平台最终售价公式。

## 确认提交

```text
Sale.SetIntro(text, "en") → ETabMulti.Set("sale_intro", text, "en")
变体表 money 列 → EStockEdit.GetStocks(...) → 完整 NStockCollection

Sale.<btnSubmit_Click>d__81.MoveNext()
  → EContainer.GetRecord()
  → 附加 id、sale_stock、图片等字段
  → Ia3D.La3e.HaF1 = "spider.update"
  → Ia3D.La3e.za3r(new Record[] { data })
  → RecordSet 编码 / TCP 请求
  → 成功返回后 ISource.Update(...) 更新客户端列表
```

`SetIntro` 只修改内存表单。提交时仍发送保留其他语言的完整 `sale_intro` 字符串。改单个变体应先读取完整集合，唯一定位 `key`，只改目标 `money`，保留其他变体后重新编码整个 `sale_stock`。

UI 文字控件比较 `Origin` 或旧 `NMulti` 的内容；默认 `Always=false`，未变字段会省略。更准确的提交范围是变化/Always 字段加上 User 提交处理器显式添加的字段，不是无条件发送整个商品。

Core 编码层能构造少量列，例如 `id(Int32)` 加 `sale_stock(String)` 或 `sale_intro(String)`；**服务端是否接受这些最小列集合尚未验证**。不能把只序列化一个变体的数组当作单变体远程更新。

`<Load>d__47` 的 `version` 来自界面请求计数，用于避免旧响应覆盖新页面，不是服务器行版本。未发现它作为保存参数传出；其他服务端并发要求仍未知。表单可包含审核状态等字段，且服务端实现不可见，不能保证 `spider.update` 不触发状态、同步或发布副作用。

## 浏览器扩展的接口边界

扩展 5.2.4 已确认以下带签名的 HTTP JSON 创建/入库操作：

| 调用 | 场景 |
|---|---|
| `POST https://seller.zying.net/api/CmdHandler?cmd=spider.insert` | 新采集记录 |
| `POST https://seller.zying.net/api/CmdHandler?cmd=spider.ins`，`{ids: result}` | 插入结果入库 |
| `POST https://meli.zying.net/api/MeliBest/Spider` / `SpiderUP` | 美客多新采集 |
| `POST https://erp.zying.net/api/CmdHandler?cmd=plugin.detail` | 采购订单详情，不是商品详情 |

扩展已注册 action 和动态路由白名单未暴露 `spider.detail/update`。不能把创建接口、`SpiderUP` 或订单详情接口替换为已有商品更新。

签名输入包含 `JSON.stringify(data)`、大写 HTTP 方法、路径及查询、秒时间戳和正常会话 token。请求 headers 包含 `token/appclient/timestamp/signature/version/client_identify/ext_version`；实际传输使用 `appclient=3`、`version=v1.1`。密钥和会话值不应进入模型上下文或仓库。

## 真实接口验收

取得受支持的接入方式后，先读实账户里的采集商品并核对编号、币种、变体键、原加价和英文介绍。按授权范围验证更新范围和可能的状态变化。以一次只改目标字段的保存开始，重新查询确认值和其他语言、变体，再按原值恢复并重新读回。自动化测试覆盖本地快照、执行器契约和当前安装版的原生加载及回环发包。真实验收以授权 TCP 执行器返回的商品和保存后读回为准。
