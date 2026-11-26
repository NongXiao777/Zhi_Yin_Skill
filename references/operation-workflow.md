# 采集、资料整理与定价流程

按用户的实际工作顺序推进，自动化使用正常授权的 CLI、API 和本地文件。VPN、Chin GPT、速卖通登录和搜索页面属于人工流程背景；本流程不使用 Computer Use、浏览器 UI 自动化或模拟鼠标键盘。

## 各步骤的当前入口

| 工作步骤 | 已有能力 | 下一步所需数据或核验 |
|---|---|---|
| 打开定价表 | 接收本地 JSON、CSV、TSV、XLSX 商品表；`erp-product-get` 按编号或父 SKU 选择记录 | 现有定价表的路径、表头、公式和币种尚未提供。先用用户的表或明确输入，不能推断原表的计算规则 |
| 打开 VPN、Chin GPT | 无需为这些背景步骤添加自动化 | 用户自行完成；商品任务直接在本对话继续 |
| 登录智赢、读取采集商品 | `credentials-save` 隐藏输入并本地加密保存；`login` 取得 CLI 会话；`collected-product-live-get` 读取指定商品 | 实账户登录和 TCP 商品读写仍需验证。按 [命令行登录](login.md) 与 [TCP 接口](collected-product-api.md) 执行 |
| 速卖通登录、按单量搜索、采集到智赢 | 尚无已验证的搜索、排序、采集 CLI | 由用户完成采集，提供智赢商品编号、来源链接和可售变体。需要自动化时先核验正常授权的 API、字段及采集结果，不能由扩展路由名猜调用 |
| 补重量、包装尺寸和英文资料 | `erp-draft-preview` 读取包装数据、仅补缺失的估算；文案按 [Listing 流程](listing-workflow.md) 生成并用 `listing-copy-check` 检查 | 提供型号、原始描述、清晰照片、实际可售组合与件数；记录包装估算依据。当前 TCP 编辑命令未接入 `sale_weight`、`sale_size` 保存，审核值由人工回填 |
| 查运费、阿里巴巴进货价、算渠道售价 | `pricing-quote --file pricing-input.json` 从明确单件成本、单件运费、费用和利润目标计算，并取 `.49/.89/.99` 尾数 | 用户提供匹配商品和采购数量的进货报价、按实际目的地/渠道得到的单件运费、费用、币种/汇率及利润目标。定价表和报价 API 未核验时使用明确输入；见 [本地定价](pricing.md) |
| 完善各变体加价、文案和图片 | `collected-product-edit` 改本地快照；`collected-product-live-edit` 按唯一 `key` 改加价、指定英文文案并读回；图片按 [图片流程](listing-images.md) 制作 | 实际变体 `key`、现有 `money`、审核目标和商品素材。图片上传、绑定子体及渠道最终售价换算尚无已验证 API |
| 检查品牌和侵权词 | `listing-copy-check` 检查五字段、已列品牌及常见原厂/官方/授权暗示；图片逐张核对文字、Logo 和商品一致性 | 将来源与素材中实际发现的品牌传入 `blocked_brands` 或 `--blocked-brand`。文字检查通过只证明已覆盖的规则，不证明商品身份、图片或类目全部合格 |

`login` 仅登录智赢桌面 ERP。它不建立速卖通会话，也不取得 Amazon 卖家授权。Amazon 的 `listing-get`、`listing-preview`、`fba-inventory` 与报告命令另需 [SP-API 配置](sp-api.md)；`listing-preview` 只做刊登预检，现有命令未发布商品。

## 一次商品任务的最小资料

- 智赢商品编号、来源链接、现有标题和介绍、清晰商品图。
- 实际可售变体：唯一 `key` / SKU、规格组合、每款件数、图片对应关系、当前加价与币种。
- 包装毛重与长宽高；缺失时提供可追溯的商品规格或允许估算的依据。
- 进货价与采购数量、目的地和物流渠道、明确运费规则、平台等费用、利润目标；存在多币种时提供明确汇率。

已有资料直接复用。会改变商品身份、变体、包装或关键结论的缺项集中询问，普通未知商品事实省略；影响定价的缺失金额、币种和费率仍需明确输入。缺少商品照片时标 `IMAGE PENDING`，先推进资料与定价，不凭空生成产品图。

## 从读取到回填

1. 用户完成采集后，先通过正常 CLI 会话读指定商品；尚未连通时处理用户提供的导出或最小快照。`status`、`launch`、`routes` 是诊断命令，不能代替已读取商品的证据。
2. 按同一组事实整理包装、五个英文字段和图片。包装估算用克、厘米并标明 `estimated`；商品尺寸图使用产品本体的已核实尺寸。生成或编辑图片使用可用的 `imagegen`，按图片参考逐张验收。
3. 用明确报价计算渠道售价，再整理每个变体的加价目标。`money` 是 ERP 变体加价，`sale_cost` 是成本，`sale_price` 是分销单价；它们与最终渠道价的换算仍待核验。不能把渠道目标价直接写入 `money`。尾数规则作用于渠道拟价，例如 `13.50 → 13.89`。
4. 用 `listing-copy-check` 核对文案；本地预览保存为新文件。TCP 已登录且真实读取通过后，按用户指定的变体键和英文字段提交修改，保留其他语言及完整变体集合。
5. 保存后重新读取同一商品，只有 `remote_read_back_verified: true` 才报告远端字段已验证。结果不明时先读现状，再决定下一步；图片绑定、包装回填和发布由人工完成，直至各自 API 被验证。

定价 JSON 使用 `currency`、`unit_cost`、`shipping_cost`、`packaging_cost`、`other_cost`、`platform_fee_rate`，利润目标选 `target_profit` 金额或 `target_margin` 比例之一。所有成本先统一币种；运费规则需要先换算成明确单件运费。可选 `channel_base_price`、`current_surcharge` 仅用于比较报价差值，不自动产生 ERP `money`。`examples/pricing-input.json` 是合成示例，不是用户原定价表。

常用参数和数据格式分别查 [本地定价](pricing.md)、[ERP 商品预览](erp-products.md)、[TCP 接口](collected-product-api.md)、[Listing 文案](listing-workflow.md) 与 [图片流程](listing-images.md)。
