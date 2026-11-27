# 读取「单个采集」的速卖通缓存

人在智赢内嵌浏览器打开商品详情后，可在提交前按标题或速卖通商品 ID 查找缓存。使用与打开商品时相同的安装目录。有多个版本时，在命令名前传入 `--app`。

```powershell
python scripts/zhiying.py collected-cache-list --limit 8
python scripts/zhiying.py collected-cache-list --match crayon --match 'wax pastel'
python scripts/zhiying.py collected-cache-get --source-id 1005013209445272
```

列表按详情缓存时间倒序，同一来源 ID 只显示一次。`--match` 对标题做不区分大小写的子串匹配，多次传入时匹配任意词。详情输出标题、店铺、主图链接、规格、变体，以及缓存中可用的商品描述。按速卖通 URL 的 `/item/{id}.html` 取 ID，支持智赢界面上仍显示 `New` 的阶段。

命令只读当前安装目录下 `cache/temp/Cache` 的 Chromium blockfile HTTP 缓存，适用于已核验的智赢内嵌浏览器布局。只解析速卖通商品详情响应和对应的商品描述，输出产品字段。图片只返回源链接。

输出反映当时页面的地区、价格和库存。智赢草稿内后续修改的字段仍以草稿为准。若列表返回零条，或详情返回 `source_product_not_cached`，可在内嵌浏览器打开对应商品，等标题、图片和 SKU 加载完成后重新读取。
