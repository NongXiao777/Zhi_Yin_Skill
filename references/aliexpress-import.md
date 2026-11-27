# 速卖通链接或 JSON 导入 New 草稿

使用本流程读取速卖通来源资料，填写可视 New 草稿或创建服务器采集产品。当前已验证标题、图片网址、采集网址的草稿填写与读回；服务器创建 helper 也已使用原始 `preview.snapshot` 从同源详情读回核验测试产品编号 969105417。草稿填写和服务器创建是两个独立步骤。该次服务端未返回 `sale_adult`，结果列为 `serverOmittedFields: ["sale_adult"]`，不声称已核验它为 false。

## 来源读取

1. 默认复用用户日常使用的普通 Chrome 现有已授权调试连接、窗口和匹配标签；尚未连接时按 [浏览器连接流程](interfaces.md) 连接。没有普通 Chrome 时正常启动它。只有用户明确要求时才使用独立浏览器。连接后提醒用户保持窗口打开；界面操作时保持窗口显示、不要最小化。
2. 从用户链接提取 `/item/{id}.html` 中的字符串 ID，使用同一商品标签。遇到登录或验证时由用户在这个窗口处理。
3. 在商品页执行 `scripts/aliexpress_browser_collect.js` 中的 `collectAliExpressProduct`。它与自制采集扩展 0.1.2 使用相同的采集核心，返回 `{ok, product}`。把 `product` 对象作为下面的 `source`。生成器的 `--source-file` 接受原始 `product` 对象，或含 `ok: true` 与 `product` 的完整采集结果。

用 `scripts/browser_call.py collect --url SOURCE_URL --output ABSOLUTE_SCRIPT_PATH` 生成调用文件，再通过已连接浏览器的 `evaluate_script` 以 `sourcePath`、`format: "function"` 和商品标签 `pageId` 执行。只使用核对过的来源 ID 和当前页面字段，不合并其他商品、旧缓存或验证信息。

## New 草稿填写

1. 复用已登录的智赢 ERP 标签；没有匹配标签时在同一普通 Chrome 中打开网页。进入「我的产品 → 产品列表」，点击「添加产品」。既有编号的详情不属于这个流程。
2. 在该标签运行 `scripts/zying_web_new_draft.js` 中的 `zyingWebNewDraft`。先用 `read` 读取 New 草稿，再用 `preview` 核对来源、目标字段和 `snapshot` 快照。英文导入时界面语言应为英语；脚本不自动切换语言。
3. 用户已经授权将此商品填入草稿时，用同一个来源对象及预览的 `expected` 调用 `fill`。脚本调用页面实际文本和图片控件的值更新回调，保留其他语言及表单默认设置；填写采集网址使用该表单接口。
4. 再调用 `verify`，检查表单值、英文语言数据、可见标题和图片控件值。只有验证通过才报告「New 草稿已填写」。草稿编号仍为空时，明确说明尚未保存。

调用形状：

```js
{action: "read"}
{action: "preview", source: product}
{action: "fill", source: product, expected: preview.snapshot}
{action: "verify", source: product}
```

用 `scripts/browser_call.py new-draft --action preview --source-file SOURCE_JSON --output ABSOLUTE_SCRIPT_PATH` 生成调用文件，将完整的成功预览结果保存为 JSON；`fill` 添加 `--preview-file PREVIEW_RESULT_JSON`，生成器从中原样读取 `preview.snapshot`，不是读取只有 snapshot 的文件。`read` 不需要来源文件；`verify` 需要同一个 `--source-file`，不接受 `--preview-file`。这些操作使用同样的生成器，不手工拼接 JSON 或脚本。

结果不明时先 `read` 和 `verify`；需要继续填写时，按读回现状重新核对 `preview`，再用这次完整预览结果调用 `fill`。脚本先设置来源网址，使同一来源的部分填写可以恢复；已经修改为其他内容的目标字段仍会报冲突。

当前字段映射：

| 来源 JSON | New 草稿 |
|---|---|
| `title` | 当前英语标题及 `tLans.en` |
| `images` | `pic` 主图数组 |
| `source_url` | `source` 采集网址 |
| 有内容的 `description` | 当前英语描述及 `iLans.en` |

`visible_price` 是来源页面显示价格，不自动用作采购成本。变体、规格、包装重量、类目和币种不由这个草稿填写器推断；它们需要按实际商品另外核对。空描述保持现有草稿描述。标题和描述按来源原文填入当前英语栏，脚本不自动翻译。

`ok: true` 表示取得可用来源对象，不表示取得完整商品资料。2026 年 11 月 27 日的测试来源返回 9 条图片网址，其中有同一图片的不同尺寸和缩略图；`variants` 为空、`currency` 与 `description` 为 null。该结果不能称为 9 张不同高清图或完整 SKU。表单读回验证的是填入值一致，图片清晰度和实际可售变体仍需另核对。

## 创建服务器采集产品

`scripts/zying_web_product_create.js` 的 `zyingWebProductCreate` 在已登录的网页采集列表 `#/product/1688/collectionlist` 中创建产品，使用 `spider` 来源。来源对象仍是扩展 `product`，另提供真实类目编号、英文简称、毛重、采购成本和币种。当前创建 payload 固定为 `sale_stat: 3411`、`sale_flag: 400`、`sale_level: 10`、`sale_grade: 1`、`sale_adult: false`；3411 是状态值，不是新产品编号。完整 payload 会在 `preview` 返回，核对后使用原快照。测试值只在用户授权实验时使用，并在备注中标明。

以下是 `create-preview-request.json` 的内容；来源另放在 `source.json`，由每次命令的 `--source-file` 提供。

```json
{
  "action": "preview",
  "metadata": {
    "category_id": 123,
    "english_short": "Example product",
    "weight_g": 100,
    "cost": "1.00",
    "currency": "CNY",
    "note": "User supplied product data"
  }
}
```

类目编号必须来自当前可用的分类。需要原生变体时，在 `metadata` 中同时提供核对过的 `native_pair` 和完整 `native_stock`；省略时创建的原生规格和变体为空。它们是另外提供的智赢规格及库存数组，不由来源 `variants` 自动转换，也不把供应商 `stock_shown` 当自己的库存。测试中手工提供的变体不证明已取得来源商品的完整 SKU。

```powershell
python scripts/browser_call.py product-create --request-file create-preview-request.json --source-file source.json --output C:\task\work\create-preview.js
python scripts/browser_call.py product-create --request-file create-apply-request.json --source-file source.json --preview-file create-preview-result.json --output C:\task\work\create-apply.js
python scripts/browser_call.py product-create --request-file create-verify-request.json --source-file source.json --preview-file create-preview-result.json --output C:\task\work\create-verify.js
```

创建请求使用相同 `source`、`metadata` 和 `limit`（若提供），把 `action` 分别改为 `apply`、`verify`。`create-preview-result.json` 必须是完整的成功预览结果；两次调用都从它取原始 `preview.snapshot`。使用当前任务的实际绝对输出路径，再通过现有浏览器连接的 `evaluate_script` 传入 `sourcePath`、`format: "function"` 和采集列表标签的 `pageId`。

当前服务创建后可能返回空值或 null 而不返回编号，不能据此重复提交。脚本使用原预览标记、创建前列表编号和同源详情读回发现新编号并核对字段。只有 `ok && verified` 才报告服务器创建成功。发现 `product_id` 而返回 `product_create_unverified` 表示记录已经被发现但字段尚未全部核验通过，应报告编号和失败检查，继续用原快照 `verify`；不要重建预览再提交。浏览器尝试状态丢失时，旧快照只可用于读回恢复，不能把它当成新的创建尝试。

New 草稿脚本只操作表单；服务器创建脚本经已登录网页加载的产品接口提交预览 payload，不调用 New 草稿表单的保存按钮。`browser_call.py` 只生成调用文件，不建立浏览器连接或直接向服务器创建产品；[操作流程](operation-workflow.md) 中的采集 CLI 状态与本节的浏览器调用分别记录。已有产品的批量加价和五个文案字段使用 [浏览器编辑](browser-product-edit.md)。

当前客户端 UI 或 React 表单结构变化时，脚本应返回明确的接口不可用、语言不匹配或快照冲突，不改用独立浏览器或猜测新增 RPC。
