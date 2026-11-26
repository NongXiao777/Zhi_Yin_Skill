---
name: zhiying-cli
description: Use 智赢跨境 through TCP login and product commands, quote prices from supplied costs, and prepare Amazon.com copy and images.
---

Run `scripts/zhiying.py` with Python 3.9+ and use `<command> --help` for flags. Return only the fields and rows needed.

Use authorized CLI transports for live product operations and explicit local files for offline work. Keep screenshots read-only. Desktop diagnostics are independent of product editing.

If a client update causes `unsupported_client_version` or native reflection failures, repair the local version profile in the current task using [client-update.md](references/client-update.md). Inspect installed DLLs, verify with synthetic probes and loopback tests, then resume authorized work.

- For the complete sourcing, packaging, pricing and copy workflow, read [operation-workflow.md](references/operation-workflow.md). Quote supplied costs with `pricing-quote`; read [pricing.md](references/pricing.md). Final channel price and ERP variant surcharge remain separate.
- For the vendor login window, use `login-native`; the user types in that window and the helper protects the session after success. For terminal input, use `credentials-save`, then `login --saved`, or `login --remember`. Read [login.md](references/login.md).
- Use `status`, `launch`, or `routes` for client diagnostics. On explicit request for a window check or activation, use `window-status` or `window-focus`. See [interfaces.md](references/interfaces.md).
- Run `collected-transport-probe` for offline native encoding checks. My Products uses `product-live-get` / `product-live-edit` (`sale.detail/update`); Product Collection uses `collected-product-live-get` / `collected-product-live-edit` (`spider.detail/update`). Keep reads, writes and confirmation on the same source. The built-in TCP transport uses installed DLLs and the protected session from login, or `ZHIYING_SESSION_FILE`. Use `--include-copy` to read English copy and `--copy-file` to change selected fields. Verify writes by reading through that transport. See [collected-product-api.md](references/collected-product-api.md) for the outer `id` versus native `sale_id` distinction.
- 保存后桌面显示可能延迟；以服务器读回结果为准，稍等并刷新页面，勿因界面暂未更新重复加价或追加文字。
- For persistent previews, interrupted operations or later restoration, use `product-plan`, `product-plan-show`, `product-apply`, and `product-restore`; read [product-plans.md](references/product-plans.md). These use the existing verified transport and can batch variant edits.
- Use `collected-product-get` and `collected-product-edit` for supplied local JSON snapshots. Read [erp-products.md](references/erp-products.md) for English introduction, per-variant `money` and .49/.89/.99 channel quotes.
- For local ERP product tables, use `erp-product-get` to select by product number and `erp-draft-preview` to review package fields and variant prices. Read [erp-products.md](references/erp-products.md) for columns and rules.
- For Amazon.com copy, including missing ERP descriptions, read [listing-workflow.md](references/listing-workflow.md). Validate the five copy fields with `listing-copy-check`. For product images, read [listing-images.md](references/listing-images.md).
- A downloaded Sales and Traffic JSON uses `traffic-summary --file report.json`. Filter by `--asin` or `--sku`, or use `--by date` for the report's date aggregates.
- Online Amazon operations use `listing-get`, `listing-preview`, `fba-inventory`, `report-create`, `report-status`, or `report-summary`. Read [sp-api.md](references/sp-api.md) for credentials, roles and examples. Preview validates a draft without publishing. Create a report only when asked to request new data.

For traffic interpretation or connector research, read [amazon-organic.md](references/amazon-organic.md). Sales and Traffic covers all page traffic. Profit and stop-loss decisions require costs, fees and the seller's thresholds.
