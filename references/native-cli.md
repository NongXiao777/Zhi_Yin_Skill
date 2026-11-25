# 原生商品 CLI

代码已实现；成功读取、保存和还原尚未通过实机验证。2026-11-26 的只读请求已收到身份标识匹配的服务器响应，结果 `-9`，没有返回商品记录。先解决正常客户端会话接入，再验证具体商品操作；不要把单元测试或错误响应当作改价成功。

## 会话依赖

需要 Windows、Python 3.9+、PowerShell 7，以及已运行并正常登录的智赢客户端。当前导出器只支持代码中 SHA256 对应的 `ZYing.Work.dll` 布局；新版本不猜字段。Microsoft 依赖需事先解压到指定目录：

```text
diagnostics/
  clrmd/lib/net6.0/Microsoft.Diagnostics.Runtime.dll
  diag/lib/net6.0/Microsoft.Diagnostics.NETCore.Client.dll
```

已验证版本为 `Microsoft.Diagnostics.Runtime 3.1.512801` 和 `Microsoft.Diagnostics.NETCore.Client 0.2.410101`。依赖、厂商 DLL、账号数据均不随仓库提交。GZip 使用 Python 标准库；收到 Brotli 响应时需要可选的 `brotli` 包。

导出器使用 ClrMD 只读附加，读取指定的客户端 GUID、Token、协议版本、修订版本和端点，没有暂停进程或执行厂商业务方法。会话写入 DPAPI CurrentUser 保护文件，不打印秘密值。重新登录或客户端重新启动后重新导出。

```powershell
python scripts/zhiying.py --app 'G:\ZYing\ZYing.exe' session-export --output work/session.local.json --diagnostics-dir 'E:\diagnostics'
python scripts/zhiying.py product-detail --session work/session.local.json --namespace sale --id 123456789 --limit 5 --output work/product.local.json
```

上述编号为示例。`sale` 对应产品列表，`spider` 对应采集列表；读取结果包含 `sale_title` 的多语言标题、价格字段摘要和有限变体。完整响应只在指定输出文件中保存。

## 改动计划

AI 传递一个短 JSON，完整商品读取、合并和编码由固定程序完成。例子的产品、变体和金额都是人工示例；`new_money` 是目标加价的绝对值，不是增量或平台售价。

```json
{
  "operation": "update_product",
  "namespace": "sale",
  "product_id": 123456789,
  "variant_key": "example-variant",
  "new_money": "7.01",
  "description_language": "en",
  "append_character": "＊"
}
```

金额使用十进制字符串，最多四位有效小数；程序不经二进制浮点改写 `money`。变体键必须唯一存在。改介绍时只追加一个可见字符，并保留其他语言；只改价可以省略两个介绍参数，只改介绍可以省略变体和金额参数。

将指令保存为 `work/instruction.local.json`：

```powershell
python scripts/zhiying.py product-plan --session work/session.local.json --instruction work/instruction.local.json --output work/plan.local.json
python scripts/zhiying.py product-apply --session work/session.local.json --plan work/plan.local.json
python scripts/zhiying.py product-restore --session work/session.local.json --plan work/plan.local.json
```

`product-plan` 会读取商品并保存预览、原值、预期内容和指纹，不提交。`product-apply` 先重读检查竞争改动，再记录写入意图、提交一次并读回；响应丢失后保留 `write_attempted`，不能自动重放。`product-restore` 只在目标字段仍属于该计划时还原，避免覆盖别人的后续修改。计划包含完整变体集合和商品原值，应留在 `work/` 或 `*.local.json` 中。

当前提交候选为 `id` 加改动列：`sale_stock` 或 `sale_intro`。保留其他变体和语言的合并已通过本地测试，但服务器接受的最小字段集合、并发版本要求及发布/同步副作用未验证。`sale_stock` 整列包含完整变体数组，不是单变体 PATCH。

## 已知限制

- 只支持已核对的普通 `M` 模式 TCP 与 `c` 响应；`w` 进度帧未实现。
- 不执行未实现的对象类型反序列化；未知记录类型会失败。
- 会话导出不等于服务端认证成功；`-9` 的具体原因仍待确认。
- 本次没有执行用户提出的“变体加价增加 0.01、介绍加字符、展示后还原”实机测试。
