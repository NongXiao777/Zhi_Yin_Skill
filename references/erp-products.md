# 智赢商品资料和加价预览

给定本地商品表，`erp-product-get` 精确选择一个智赢产品编号或父 SKU。`erp-draft-preview` 对选中的每条变体应用相同加价规则，保留各自的原价和 SKU，并返回包装字段、拟价和缺项。两个命令直接处理文件。保存的 JSON 供审阅和手工回填。

智赢采集列表是入主库前的暂存区。官方公开文档说明了采集列表查询、主库表格导入和批量替换。对某个采集编号的 CLI 读取和交换格式仍待确认。主库批量导入用于建档，主库批量替换的「成本价格 增减」影响成本价。 [采集列表](https://www.zying.net/helpdet-725.html) · [批量导入](https://www.zying.net/helpdet-714.html) · [批量替换](https://www.zying.net/helpdet-713.html)

## 采集商品快照

人工完成采集和必要的登录后，给 Skill 商品编号、素材和定价表结果。若有获授权的数据导出，取出对应商品或映射为下列单商品 JSON。也可根据人工核实的数据给出最小快照。顶层可直接是记录对象，也可用 `root` 包裹。保留导出中的其他字段和所有变体。

```json
{"sale_id":1001,"sale_cur":"USD","sale_cost":"8.20","sale_price":"11.00","sale_intro":{"en":"Old description","zh":"保留原中文"},"sale_stock":[{"key":"12V-30rpm","money":0.3},{"key":"24V-30rpm","money":0.2}]}
```

`sale_intro` 与 `sale_stock` 也接受包含 JSON 的字符串。保留原文件的这两种表示。可附上 `sale_weight`（克）、`sale_size`（厘米，长宽高）。写介绍时只改语言键 `en`。写变体时用 `key` 唯一定位，保留当前集合的其他数据。

```powershell
python scripts/zhiying.py collected-product-get --file product.json --product-id 1001 --include-intro
python scripts/zhiying.py collected-product-edit --file product.json --product-id 1001 --adjust-surcharge 12V-30rpm 0.10 --set-surcharge 24V-30rpm 0.50 --minimum-channel-price 13.49 --intro-file intro.txt --blocked-brand '示例品牌' --output product-edited.json
```

- `--set-surcharge` 直接设置变体的 `money`，`--adjust-surcharge` 在原 `money` 上增减。两者可重复传不同变体键。例如 0.30 加 0.10 得到 0.40，加 0.20 得到 0.50。若给出 SKU 或规格，先核对对应的唯一 `key`。
- 渠道最低拟价来自人工确认的定价表。采用不低于输入的最小 .49、.89 或 .99 尾数，例如 13.30 → 13.49，13.50 → 13.89，13.49 保持 13.49。渠道拟价单独返回。`money` 是加价，`sale_cost` 是成本，`sale_price` 是分销单价。渠道实际价的换算关系待核实。
- `intro.txt` 使用 UTF-8。把素材里的可见品牌和禁用词以 `--blocked-brand` 传入，可重复。命令也检查常见原厂、官方和授权暗示。图片中的文字、Logo 和商品外观按 [图片流程](listing-images.md) 审核。
- 省略 `--output` 仅查看预览。指定新 JSON 路径可保存并读回验证本地快照，原文件保留作回退依据。由人工把审核后的加价和介绍回填到采集记录。实际读写状态见 [采集商品接口记录](collected-product-api.md)。

### 修改标题与其他文案

`--include-copy` 读取商品描述和已有的英文字段。用 `--copy-file copy.json` 替换文件中指定的字段，可与改价一次执行。支持 `product_title`、`product_highlight`、`bullet_points`、`product_description` 和 `backend_search_terms`。要点用字符串数组，其余用字符串。可附 `blocked_brands` 和 `status`，状态为 `HOLD` 时停止。

```json
{"product_title":"Compact DC Worm Gear Motor","product_description":"A compact gear motor with reversible rotation."}
```

`product_description` 更新 `sale_intro` 的 `en`。其他字段以 `listing_copy` 下的语言映射保存，例如 `"listing_copy":{"product_title":{"en":"Current title","zh":"中文标题"}}`。CLI 保留其他语言和未指定的字段。详情字段映射由 [授权 TCP 执行器](collected-product-api.md) 验证。

## 选择商品

```powershell
python scripts/zhiying.py erp-product-get --file examples/erp-products.csv --product-id DEMO-1001
python scripts/zhiying.py erp-product-get --file products.xlsx --sheet 产品 --parent-sku MY-PARENT
```

每条变体占一行，产品编号或父 SKU 在所属变体行重复填写。Excel 中带前导零的编号请用文本格式保存。XLSX 用第一张表或指定 `--sheet`，读取需要本地 Python 装有 `openpyxl`。CSV、TSV 和 JSON 使用标准库。JSON 可用行对象数组或 `{"rows":[...]}`。

| 数据 | 推荐表头或字段 |
|---|---|
| 智赢编号、父 SKU、变体 SKU | `产品编号` / `product_id`，`父SKU` / `parent_sku`，`SKU` / `sku` |
| 显示名称 | `标题` / `title`，`变体` / `variant` |
| 既有售价和币种 | `原售价` / `base_price`，`币种` / `currency` |
| 包装毛重 | `毛重(克)` / `gross_weight_g` |
| 包装长宽高 | `包装尺寸(cm)` / `package_cm`，例如 `18x12x9` |
| 英文介绍 | `英文描述` / `description`，可提供带单位的独立行 `Gross weight: 0.37 kg`、`Package dimensions: 19 x 13 x 10 cm` |

如果文件的价格列叫其他名字，用 `--price-column` 指定准确表头。分销单价 `sale_price` 需显式选择，并按分销单价解释结果。同名 SKU 或无法区分的变体会标出。包装尺寸按长、宽、高输入，直接从文件取值时请使用标明单位的列。智赢新建产品说明中的包装毛重按克填写。 [智赢包装字段](https://www.zying.net/helpdet-303.html)

## 预览填写和加价

```powershell
python scripts/zhiying.py erp-draft-preview --file examples/erp-products.csv --product-id DEMO-1001 --add-amount 3.25 --currency CNY --gross-weight-g 370 --package-cm 19x13x10 --output preview.json
python scripts/zhiying.py erp-draft-preview --file examples/erp-products.csv --parent-sku DEMO-BOX --markup-percent 15
```

- `--add-amount` 在各变体原价上加相同金额，需配合 `--currency`。`--markup-percent 15` 表示各自原价乘 `1.15`。`--currency` 可补空币种，已有币种与它不符的行会标出。
- `--gross-weight-g` 和 `--package-cm` 给所选变体统一填值。省略时先读包装列，列为空才读英文介绍中明确标注的包装数据，并标明来源。净重、产品本身尺寸或有冲突的数值留给人工确认。变体分别使用自己的原价计算。默认按四舍五入保留两位，可用 `--decimals` 调整。
- `issue_counts` 统计全组缺项和冲突，`ready_for_review` 表示输入检查通过。`--limit` 仅限制终端输出，`--output` 写入全组结果。现有预览文件用新的文件名保留。

## 缺失时估算包装

先按一个实际可售包装核对件数、附件、本体长宽高和重量。优先用匹配变体的规格或供应商包装数据。如果只能找到同系列或相近款，把来源、差异和包材假设写在 `--estimate-basis`，以克和厘米给出保守的单件建议。包装件数不明的外箱数据只作为参考空间。支架单卖、带支架套装和纯电机按实际内容分别估算。

```powershell
python scripts/zhiying.py erp-draft-preview --file products.csv --product-id MY-ID --estimated-gross-weight-g 200 --estimated-package-cm 13x10x8 --estimate-basis '同系列参考；单件，纸盒加泡沫'
```

省略加价参数可以单独预览包装。估算标成 `estimated`，仅补缺项，保留已有值和明确标注的包装数据。冲突值会被提示。估算可用于 ERP 草稿和物流预算，实际出货或 FBA 填报时复核封装后的尺寸和毛重。买家文案和产品尺寸图使用已核实的商品规格。
