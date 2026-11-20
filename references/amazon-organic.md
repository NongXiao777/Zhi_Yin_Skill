# Amazon natural-traffic scope, 2026-11-20

The user currently operates Amazon with natural traffic. Treat advertising budgets as a future optional workflow, not an active account control.

## What is available in the installed client

Static inspection of `D:\ZYing\ZYing.Work.dll`, type `AmzService.Amz`, found:

| Need | Existing method names | Remaining verification |
|---|---|---|
| Listing details | `GetListingsItem_20210801`, `SearchListingsItems` | Account authorization and exact includedData/payload |
| Publish/update products | `PutListingsItem(sku, productType, requirements, attributes)` | Product type schema, validations and user-approved change |
| Feed processing | `CreateFeed`, `GetFeed`, `GetFeedDocument` | Feed schema and processing result |
| Price/offer visibility | `GetPrice`, `GetItemOffersByAsin` | Marketplace and offer/account scope |
| Sales/traffic reports | `CreateReport`, `GetReport`, `GetReportDocId`, `GetReportDocument`, `DownloadReport` | Permissions, report options and account retrieval |

The installation contains the report identifier `GET_SALES_AND_TRAFFIC_REPORT`. This is evidence that the application contains a compatible report capability, not a callable shell command. Native methods cannot simply be run as external CLI subcommands without authentication and initialization.

The official report JSON model includes `salesAndTrafficByAsin`, with `salesByAsin` and `trafficByAsin`, plus date aggregates. The supplied `traffic-summary` command parses an already downloaded JSON report and returns ASIN/SKU, sessions, page views, units ordered, sales/currency, and unit-session percentage. It performs no account/network operations. SKU can be absent when reports use CHILD/PARENT aggregation.

This report covers page traffic and sales; it does not explicitly separate natural traffic from paid traffic. Do not equate unit-session percentage with orders/session or claim a change will guarantee conversion. Stop-loss calculations require product cost, Amazon fees, shipping, refunds and the user's thresholds; gross sales alone cannot supply net profit.

## Reusable integration candidates

The official `amzn/selling-partner-api-sdk` supplies Python/JavaScript/C# clients. This is the stable code-based route for a small deterministic CLI after legitimate SP-API developer registration and Seller Central authorization. Credentials remain local to the client; the model should only receive bounded business summaries.

The official `amzn/selling-partner-agentic-toolkit` contains `seller-analytics`, `listing-searchability` and `stockout-prevention` skills, backed by the Selling Partner Connector MCP. The official product homepage lists AWS Quick and Claude as current hosts. Codex compatibility and this account's authorization were not verified, and this session exposes no Amazon connector tools. The analytics skill retains a private-beta note about domain naming; do not interpret that note alone as proof the whole product is unreleased. Its analytics skill also requires a separate request reference, so its apparent entrypoint length understates loaded context.

For repeated use, prefer a short router and fixed commands such as listing validation, report retrieval and traffic summaries. Only claim a business command is implemented after a real authorized request and response have been validated. For current offline work, use the supplied local JSON summary command. If connector access becomes available, discover metric IDs once and reuse the verified IDs.
