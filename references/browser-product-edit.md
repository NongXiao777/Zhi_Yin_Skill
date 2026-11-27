# 浏览器批量加价和商品文案

使用 `scripts/zying_web_product_edit.js` 的 `zyingWebProductEdit` 读取、预览、保存和核验已有产品。当前已在网页采集列表的服务器测试产品上同时验证五个英文文案字段及两个变体加价，其他字段保持不变。

默认复用用户现有普通 Chrome 的已授权调试连接、窗口和匹配标签。连接后提醒用户保持这个窗口打开至浏览器任务完成；需要查看或操作界面时保持窗口显示、不要最小化，普通接口读回不要求浏览器一直在前台。产品采集选择 `source: "spider"`，页面为 `#/product/1688/collectionlist`；我的产品选择 `source: "sale"`，页面为 `#/product/myproduct/productlist`。保存返回空值或 null 不能单独证明成功或失败，必须看同源读回的核验结果。浏览器接口不可用时先读取现状；已有原生 CLI 可以按相同产品来源处理，结果不明时不改用它重复写入。

## 字段

| `changes` 字段 | 内容 |
|---|---|
| `english_title` | 英文产品标题 |
| `english_brief` | 英文文案简述，保存为 `sale_brief`，不同于创建资料的 `english_short` / `sale_en` |
| `english_keys` | 英文关键词 |
| `english_bullet` | 英文要点，按换行组织 |
| `english_description` | 英文描述 |
| `surcharges` | `[{key, value}]`，按实际变体键设置绝对加价 |

只提供需要修改的字段。加价是页面的「加价」，不是基础成本或最终平台售价；增量先由本次读回值算成绝对值。每次最多 500 个不同变体键，保存时保持完整变体数组及其他语言。

## 调用

1. 用 `read` 和真实产品编号读取五个英文字段与变体键。`product_id` 使用正的 Int32 JSON 整数；`read` 不含 `changes` 或 `expected`。`read` 默认展示前 10 个变体，可通过 `limit` 展示最多 50 个；同时返回总数，不能把这个展示列表当作完整变体集合。更多目标键需从同来源的完整详情核对。只操作用户授权的编号与字段。
2. 用 `preview` 读取当前基线及拟修改值，将完整的成功预览结果保存到工作文件，其中的原始 `snapshot` 同时绑定基线与 `changes`。
3. 用完全相同的来源、编号、`changes` 和 `expected: preview.snapshot` 调用 `apply`。脚本保存前重新读取基线，只发送允许的目标列及 `sale_id`，然后从同一接口读回。
4. 用同一个原始预览快照和相同 `changes` 调用 `verify`，即使 `apply` 已返回成功也不重新预览来核验本次修改。浏览器远端读回成功必须同时满足 `ok === true` 和 `verified === true`；TCP CLI 工作流使用 `remote_read_back_verified`。检查其他语言、全部变体及其他字段的保留结果。

```json
{
  "action": "preview",
  "source": "spider",
  "product_id": 123456789,
  "changes": {
    "english_title": "Example product title",
    "english_brief": "Example short title",
    "english_keys": "example, keywords",
    "english_bullet": "First point\nSecond point",
    "english_description": "Example description.",
    "surcharges": [{"key": "EXACT_VARIANT_KEY", "value": "1.25"}]
  }
}
```

编号和变体键必须替换为本次读取的真实值。不要把速卖通 SKU ID 当成智赢变体键。

## 生成浏览器调用脚本

`scripts/browser_call.py` 将 JSON 请求和对应函数组合成可直接执行的浏览器函数文件，避免人工拼接代码。它只生成文件，不启动浏览器。

```powershell
python scripts/browser_call.py product-edit --request-file preview-request.json --output C:\task\work\preview.js
python scripts/browser_call.py product-edit --request-file apply-request.json --preview-file preview-result.json --output C:\task\work\apply.js
python scripts/browser_call.py product-edit --request-file verify-request.json --preview-file preview-result.json --output C:\task\work\verify.js
```

`apply-request.json` 和 `verify-request.json` 分别将 `action` 改为 `apply`、`verify`，保留同一个 `source`、`product_id`、`changes` 和 `limit`（若提供）。`preview-result.json` 必须是完整的成功预览结果，不是单独 snapshot，也不是 apply/verify 的结果；生成器把其中的 `preview.snapshot` 原样放入 `expected`。如果请求已经包含 `expected`，它必须与该快照一致。使用当前任务的实际绝对输出路径，再通过已连接浏览器的 `evaluate_script` 传入 `sourcePath`、`format: "function"`、正确 `pageId`；结果可写到工作文件，回复只引用必要字段。

保存响应为空、缺失或报错时，脚本仍尝试读回一次。未核验成功时用原始预览快照执行 `verify` 并读取现状，不重复写入或增加价格。`apply` 的快照冲突表示当前基线已改变；先核对变化，确定需要新的修改后再建立新预览，不能用新预览证明上一次保存保持了其他字段。服务端 `sale_log` 变化会单独报告，其他字段变化仍使核验失败。
