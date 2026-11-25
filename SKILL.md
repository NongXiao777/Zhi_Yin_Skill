---
name: zhiying-cli
description: Diagnose 智赢跨境, edit local collected-product introductions and variant surcharges, and draft Amazon.com listings and images.
---

Run `scripts/zhiying.py` with Python 3.9+ and use `<command> --help` for flags. Return only the fields and rows needed.

Use authorized APIs, CLI and local files for product operations. Ask the user for the product number, prices, assets or an export after any manual login or collection step.

- Use `status`, `launch`, or `routes` for client diagnostics. On explicit request for a window check or activation, use `window-status` or `window-focus`. See [interfaces.md](references/interfaces.md).
- Use `collected-product-get` and `collected-product-edit` with a supplied JSON snapshot. For English introduction, per-variant `money` and .49/.89/.99 channel quotes, read [erp-products.md](references/erp-products.md). Desktop `spider.detail` and `spider.update` remain static evidence. See [collected-product-api.md](references/collected-product-api.md) for the verified fields and live validation requirements.
- For local ERP product tables, use `erp-product-get` to select by product number and `erp-draft-preview` to review package fields and variant prices. Read [erp-products.md](references/erp-products.md) for columns and rules.
- For Amazon.com copy, including missing ERP descriptions, read [listing-workflow.md](references/listing-workflow.md). Validate the five copy fields with `listing-copy-check`. For product images, read [listing-images.md](references/listing-images.md).
- A downloaded Sales and Traffic JSON uses `traffic-summary --file report.json`. Filter by `--asin` or `--sku`, or use `--by date` for the report's date aggregates.
- Online Amazon operations use `listing-get`, `listing-preview`, `fba-inventory`, `report-create`, `report-status`, or `report-summary`. Read [sp-api.md](references/sp-api.md) for credentials, roles and examples. Preview validates a draft without publishing. Create a report only when asked to request new data.

For traffic interpretation or connector research, read [amazon-organic.md](references/amazon-organic.md). Sales and Traffic covers all page traffic. Profit and stop-loss decisions require costs, fees and the seller's thresholds.
