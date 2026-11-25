# 智赢跨境 Skill

用简短的技能入口和 Python CLI 处理智赢本地诊断、产品资料和加价预览，以及亚马逊刊登预检、库存和销售流量。需要 Python 3.9+。Excel 工作簿读取使用可选依赖 `openpyxl`，智赢进程检查使用 Windows PowerShell。

| 命令 | 操作 |
|---|---|
| `status` / `launch` / `routes` | 检查或启动智赢，查看扩展中的命令定义 |
| `window-status` / `window-focus` | 按明确请求检查现有窗口或切到前台 |
| `collected-transport-probe` | 无窗口加载原生 TCP 组件并验证请求编码 |
| `collected-product-live-get` / `collected-product-live-edit` | 通过原生或自定义 TCP 执行器读取价格和文案、修改加价或选定文案并读回 |
| `collected-product-get` / `collected-product-edit` | 读本地采集商品快照，预览并保存英文文案和指定变体的加价 |
| `erp-product-get` | 从本地商品表按产品编号或父 SKU 选取商品和变体 |
| `erp-draft-preview` | 预填包装毛重和尺寸，批量试算变体加价并保存审阅稿 |
| `listing-copy-check` | 检查美国站五个英文字段、排除指定品牌和原厂暗示，可返回智赢英文栏位 |
| `traffic-summary` | 读取本地销售流量报告，按 ASIN/SKU 筛选、按指标排序或查看日期汇总 |
| `listing-get` | 按 SKU 读取刊登状态、卖家报价、可售量和刊登问题 |
| `listing-preview` | 将草稿交给 Amazon 预检，返回刊登问题 |
| `fba-inventory` | 按 SKU 查看 FBA 可配送、在途和预留数量 |
| `report-create` / `report-status` / `report-summary` | 申请报告、查询生成状态、在内存下载并汇总 |

## 本地使用

```powershell
python scripts/zhiying.py status
python scripts/zhiying.py routes --match amazon --limit 5
python scripts/zhiying.py erp-product-get --file examples/erp-products.csv --product-id DEMO-1001
python scripts/zhiying.py erp-draft-preview --file examples/erp-products.csv --product-id DEMO-1001 --add-amount 3.25 --currency CNY
python scripts/zhiying.py traffic-summary --file examples/sales-traffic.json --sku DEMO-002 --limit 1
python scripts/zhiying.py traffic-summary --file examples/sales-traffic.json --by date --limit 2
```

示例使用合成数据。实际报告可放在 Git 忽略的 `reports/` 目录。以关键词 `--help` 查看每条命令的参数。默认优先使用 `%LOCALAPPDATA%\Programs\ZYing\ZYing.exe`，不存在时检查 `D:\ZYing\ZYing.exe`，扩展路径为 `%LOCALAPPDATA%\ZYing\zying-ext.crx`。可在子命令前使用 `--app` 和 `--extension` 指定其他路径。`launch` 返回的是初次观察到的进程状态。

商品表支持 CSV、TSV、JSON 和 XLSX。采集商品 JSON 可按变体键更新加价、更新英文介绍并保存到新文件。列名、单位和定价规则见 [ERP 商品预览](references/erp-products.md)。内置 TCP 执行器已通过当前安装版的组件和回环发包核验，需要 PowerShell 7、.NET 6 Desktop Runtime 和正常登录会话。实账户读写仍待验证。见 [采集商品接口记录](references/collected-product-api.md)。

商品介绍缺失时，按 [Amazon.com 文案流程](references/listing-workflow.md) 先核验并生成缺失内容，再用 `listing-copy-check` 检查。主图、场景图、细节图和尺寸图的制作边界见 [商品图片](references/listing-images.md)。

## Amazon 联机使用

在线命令需要已获授权的 SP-API 应用和对应权限。`listing-preview` 固定使用 `VALIDATION_PREVIEW`；`report-create` 会向 Amazon 新建报告请求。配置、示例和结果解释见 [SP-API 操作说明](references/sp-api.md)。

Sales and Traffic 覆盖整体页面流量。净利润和止损需要另有成本、费用、物流、退款和阈值。更多背景见 [亚马逊运营参考](references/amazon-organic.md)。

## 在 Codex 复用

将 `zhiying-cli` 文件夹放在 Codex 的技能搜索目录，或在对话里指定 [SKILL.md](SKILL.md)。入口只列常用命令。接口和业务资料按需读取。

## 验证

```powershell
python -m unittest discover -s tests
```

测试覆盖本地扩展解析、商品选择、包装和价格预览、报告处理，以及模拟 HTTP 响应下的刊登、库存和报告流程。XLSX 测试在已安装 `openpyxl` 的环境运行。真实卖家账户联机验证需要已授权的 SP-API 应用。
