# 智赢商品资料和加价预览

给定本地商品表，`erp-product-get` 精确选择一个智赢产品编号或父 SKU。`erp-draft-preview` 对选中的每条变体应用相同加价规则，保留各自的原价和 SKU，并返回包装字段、拟价和缺项。两个命令直接处理文件。保存的 JSON 供审阅和手工回填。

智赢采集列表是入主库前的暂存区。官方公开文档说明了采集列表查询、主库表格导入和批量替换。对某个采集编号的 CLI 读取和交换格式仍待确认。主库批量导入用于建档，主库批量替换的「成本价格 增减」影响成本价。 [采集列表](https://www.zying.net/helpdet-725.html) · [批量导入](https://www.zying.net/helpdet-714.html) · [批量替换](https://www.zying.net/helpdet-713.html)

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

如果文件的价格列叫其他名字，用 `--price-column` 指定准确表头。同名 SKU 或无法区分的变体会标出。包装尺寸按长、宽、高输入，直接从文件取值时请使用标明单位的列。智赢新建产品说明中的包装毛重按克填写。 [智赢包装字段](https://www.zying.net/helpdet-303.html)

## 预览填写和加价

```powershell
python scripts/zhiying.py erp-draft-preview --file examples/erp-products.csv --product-id DEMO-1001 --add-amount 3.25 --currency CNY --gross-weight-g 370 --package-cm 19x13x10 --output preview.json
python scripts/zhiying.py erp-draft-preview --file examples/erp-products.csv --parent-sku DEMO-BOX --markup-percent 15
```

- `--add-amount` 在各变体原价上加相同金额，需配合 `--currency`。`--markup-percent 15` 表示各自原价乘 `1.15`。`--currency` 可补空币种，已有币种与它不符的行会标出。
- `--gross-weight-g` 和 `--package-cm` 给所选变体统一填值。省略时先读包装列，列为空才读英文介绍中明确标注的包装数据，并标明来源。净重、产品本身尺寸或有冲突的数值留给人工确认。变体分别使用自己的原价计算。默认按四舍五入保留两位，可用 `--decimals` 调整。
- `issue_counts` 统计全组缺项和冲突，`ready_for_review` 表示输入检查通过。`--limit` 仅限制终端输出，`--output` 写入全组结果。现有预览文件用新的文件名保留。
