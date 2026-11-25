# Amazon SP-API 操作

这些命令直接调用 Amazon SP-API。先注册 SP-API 应用、分配对应角色并取得卖家授权。在本地进程环境中配置 `SP_API_CLIENT_ID`、`SP_API_CLIENT_SECRET` 和 `SP_API_REFRESH_TOKEN`。刊登命令另需 `SP_API_SELLER_ID`。CLI 在运行时兑换 LWA access token，凭证保留在本地进程内。令牌应由本机的凭证管理流程注入。 [Amazon 授权与连接说明](https://developer-docs.amazon.com/sp-api/docs/connecting-to-the-selling-partner-api)

每条在线命令需要指定 `--region na|eu|fe`。按目标 Amazon 站点选择区域和 marketplace ID。下面用北美美国站举例。 [区域与端点](https://developer-docs.amazon.com/sp-api/docs/sp-api-endpoints) · [Marketplace ID](https://developer-docs.amazon.com/sp-api/docs/marketplace-ids)

## 刊登、报价、库存

```powershell
python scripts/zhiying.py listing-get --region na --marketplace ATVPDKIKX0DER --sku 'MY-SKU' --limit 5
python scripts/zhiying.py fba-inventory --region na --marketplace ATVPDKIKX0DER --sku 'MY-SKU'
python scripts/zhiying.py listing-preview --region na --marketplace ATVPDKIKX0DER --sku 'MY-SKU' --file reports/listing-draft.json
```

- `listing-get` 返回刊登状态、指定站点的卖家报价、履约渠道可用数量和刊登问题。FBA 的实际库存用 `fba-inventory` 查。 [getListingsItem](https://developer-docs.amazon.com/sp-api/reference/getlistingsitem)
- `fba-inventory` 返回库存明细。`0` 表示明确为零，`null` 表示响应未提供数量。出现 `next_token` 时，可带 `--next-token` 查询下一页。Amazon 给出的分页令牌有效期为 30 秒。 [getInventorySummaries](https://developer-docs.amazon.com/sp-api/reference/getinventorysummaries)
- `listing-preview` 读取 JSON 草稿，要求有 `productType` 和 `attributes`，可带 `requirements`。用当前站点和卖家的 Product Type Definitions 构造对应属性。Amazon 以 `VALIDATION_PREVIEW` 处理，返回校验状态和问题，供修改草稿。预检完成时进程退出码为 0，是否通过要看 `status` 和问题列表。 [预检说明](https://developer-docs.amazon.com/sp-api/docs/preview-errors-before-creating-a-listing) · [商品类型接口](https://developer-docs.amazon.com/sp-api/reference/getdefinitionsproducttype)

## 销售流量报告

```powershell
python scripts/zhiying.py report-create --region na --marketplace ATVPDKIKX0DER --start 2026-11-01 --end 2026-11-07 --asin-granularity SKU
python scripts/zhiying.py report-status --region na --report-id 'REPORT_ID'
python scripts/zhiying.py report-summary --region na --report-id 'REPORT_ID' --sku 'MY-SKU' --limit 5
python scripts/zhiying.py report-summary --region na --report-id 'REPORT_ID' --by date --limit 7
```

- `report-create` 新建一份 `GET_SALES_AND_TRAFFIC_REPORT`。默认粒度为 `DAY` 和 `CHILD`，需要按 SKU 筛选时申请 `SKU`。起止日期按 UTC 请求，Amazon 会按所选的 `WEEK` 或 `MONTH` 扩展范围。此报告需要 Brand Analytics 角色。 [报告选项和权限](https://developer-docs.amazon.com/sp-api/docs/report-type-values-analytics)
- 记录返回的 `report_id`。`report-status` 与 `report-summary` 都返回 `processing_status`。等待 `DONE` 后可取汇总，遇到 `CANCELLED` 或 `FATAL` 时检查参数和 Amazon 记录。状态查询一次即返回。收到超时或 `429` 时先查已有报告和 Amazon 限流情况，再决定是否重发申请。 [createReport](https://developer-docs.amazon.com/sp-api/reference/createreport) · [getReport](https://developer-docs.amazon.com/sp-api/reference/getreport)
- `report-summary` 在 `DONE` 时通过 Amazon 的预签名地址下载，支持 JSON 和 GZIP，内容在内存解析。它与本地 `traffic-summary` 都支持 `--asin`、`--sku`、`--by date` 和 `--sort sessions|units_ordered|unit_session_percentage`。ASIN 匹配父或子 ASIN，SKU 精确匹配，数字降序且缺失值靠后。日期汇总使用报告原有粒度。 [下载报告](https://developer-docs.amazon.com/sp-api/docs/retrieve-a-report)

HTTP 错误返回状态码和可用的 Amazon request ID。可据此检查凭证、应用角色、站点或限流。原始响应正文和预签名地址保留在脚本处理过程内。
