# 智赢跨境 Skill

用于智赢客户端窗口检查、接口排查和亚马逊报表摘要。使用短 `SKILL.md` 和固定的本地脚本，按需读取接口资料，输出少量 JSON；运行命令不依赖 computer use。

当前可用：

| 命令 | 功能 |
|---|---|
| `status` | 检查本地智赢安装、进程、监听端口和扩展版本 |
| `launch` | 尝试启动已安装的客户端；报告初次观察状态 |
| `window-status` | 查找指定安装路径的现有窗口，报告标题及前台状态 |
| `window-focus` | 激活已运行的智赢窗口，核对窗口响应及前台状态 |
| `routes` | 从已安装扩展发现 HTTP 命令定义；不发送业务请求 |
| `traffic-summary` | 摘要已下载的 Amazon Sales and Traffic JSON 报告 |

商品读取、改价、上品、在线报告下载、自动补货/止损和广告预算调整尚未实现。现已静态确认采集商品详情与提交的桌面 TCP 调用链及字段编码，但正常会话调用、服务端最小更新参数和读回验证尚未接通。窗口激活成功只证明可以控制窗口前台状态。

## 使用

需要 Python 3.9+。脚本仅依赖标准库；Windows 状态检查使用系统 PowerShell，窗口命令使用 Windows API，报告摘要可跨平台运行。

```powershell
python scripts/zhiying.py status
python scripts/zhiying.py window-status
python scripts/zhiying.py window-focus
python scripts/zhiying.py routes --match amazon --limit 5
python scripts/zhiying.py traffic-summary --file examples/sales-traffic.json --limit 2
```

示例报告是人工生成的测试数据，不是卖家账号数据。业务报告放在被忽略的 `reports/` 目录，例如：

```powershell
python scripts/zhiying.py traffic-summary --file reports/sales-traffic.json --limit 10
```

默认程序路径为 `D:\ZYing\ZYing.exe`，扩展路径为 `%LOCALAPPDATA%\ZYing\zying-ext.crx`。路径参数放在子命令前：

```powershell
python scripts/zhiying.py --app 'E:\ZYing\ZYing.exe' --extension 'E:\extensions\zying-ext.crx' status
python scripts/zhiying.py --app 'G:\ZYing\ZYing.exe' window-focus
```

`launch` 只启动已有程序，不传入猜测的 `--help` 或调试参数。进程出现不代表登录和完整启动成功。初次实机测试观察到短暂进程，后续已退出，持续启动原因仍未验证。

2026-11-25 已对一个运行中的智赢客户端实测窗口查找和激活：返回 `foreground=true`、`window_responding=true`，没有发送商品请求。`window-focus` 使用现有窗口，不另开一份客户端。窗口标题也不能证明账号权限或登录的是哪一种业务入口。

如果 `window-status` 返回多个窗口，使用返回的整数句柄指定目标；`--window` 放在子命令后：

```powershell
python scripts/zhiying.py --app 'G:\ZYing\ZYing.exe' window-focus --window 123456
```

## 在 Codex 复用

把这个仓库作为一个技能文件夹放到你的 Codex skills 目录，或在对话中指定本仓库的 `SKILL.md`。入口以脚本命令为主，按需读取 `references/amazon-organic.md`、`references/interfaces.md` 或 `references/collected-product-api.md`，避免每轮重复扫描客户端或完整输出页面。

采集商品字段与调用边界见 [采集商品接口核验](references/collected-product-api.md)：`money` 是变体加价，`sale_cost` 是成本单价，`sale_price` 是分销单价。扩展的新采集 HTTP 接口不能直接代替桌面的现有商品更新命令。

Sales and Traffic 报告覆盖整体页面流量，不直接区分自然与广告归因。`unitSessionPercentage` 也不等于订单/session。止损需要成本、平台费用、物流和退款等信息，不能从销售额直接推算净利润。

后续优先验证 SP-API 商品类型校验/刊登草稿、报告下载以及价格库存读取；再加入明确规则的放量、补货和止损建议。真正执行业务写入前，需要已授权账户和具体变更。

## 验证

```powershell
python -m unittest discover -s tests
```

测试覆盖 CRX 2/3 封装解析、路由输出限制、报告字段、缺失 SKU、错误输入、异步窗口激活验证和多窗口歧义处理。窗口查找和激活另有实机验证；报告摘要同时按 Amazon 官方 schema 示例核对。没有执行商品读取、保存或店铺改价。

## 官方参考

详见 `references/sources.json`。Amazon 官方 Selling Partner skill/connector 与官方 SP-API SDK可作为后续接入候选；本仓库不假定 Codex 已具备 Amazon connector，也不包含账号令牌。
