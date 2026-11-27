# 默认 Chrome 选品与采集流程

默认使用用户的普通 Chrome 配置和已登录的智赢网页。选品或采集资料时用插件取 JSON。需要网页草稿时填 New，明确要求入「产品采集」时创建服务器商品并读回编号。已有链接、JSON 或编号时从相应入口继续。

## 接入与前台

1. 有现成连接时直接执行当前操作，复用该连接中仍有效的标签和 worker ID。缺少目标或 ID 失效时用 `list_pages` 重新定位。连接器的列表可能是结构化记录或文本，按实际格式使用。已有接入请求在等待时，继续等原请求返回。
2. 首次接入使用明确支持 existing-browser / `--autoConnect` 的连接器，或同一 Chrome 实际显示的调试端点。工具配置会启动独立 Chrome 时，用下面的持久客户端。只有普通 Chrome 未运行时，才按常规配置启动。只有调试未启用时，才在同一窗口打开 `chrome://inspect/#remote-debugging` 请用户勾选「Allow remote debugging for this browser instance」。Chrome 显示接入确认时，由用户点击一次「允许」。
3. 从只读验证到后续选品、插件取数、填草稿、保存和读回，保留同一个客户端进程和调试会话。跨工具调用、用户回复和后续步骤继续使用该连接。使用浏览器助手返回的标签 ID 和 worker ID，无需单独接入 worker。一次性命令退出会释放调试连接，后续调用可能再次弹出许可。
4. 待许可时继续等待原请求。遇到超时先确认原请求是否还在等待，再通过已有状态或 Chrome 界面判断实际阻碍。确认原请求已经结束、连接确实不可用且任务仍需接入时，向同一 Chrome 发起一次重连。明确拒绝时暂停接入。
5. 连接后提醒用户保持原 Chrome 打开。选品、采集或界面核验时默认尝试 `select_page` 的 `bringToFront: true`。最小化时先尝试恢复。用户要求纯只读验证时，读取当前任务所需页面。登录、验证及 Chrome 许可由用户处理，已授权的业务步骤由助手直接完成。

### Windows 上的持久客户端

优先复用已连接普通 Chrome 的工具会话。如果内置工具缺失，或它会启动独立 Chrome，可在持久的 Node REPL 导入 [browser_session.mjs](../scripts/browser_session.mjs)，用本机已安装的 Chrome DevTools MCP 连接普通 Chrome。首次使用时提供 Node.js 和 MCP 入口文件的绝对路径。后续在同一 REPL 中复用 `globalThis.zyBrowserConnection`，也可调用 `getChromeSession()` 取得已有对象。若本机也没有可用的 MCP 入口，说明缺的是 Chrome DevTools MCP，并按当前任务继续可用步骤。此脚本只调用现有安装。

```js
const { pathToFileURL } = await import("node:url");
const { getChromeSession } = await import(pathToFileURL(browserSessionPath).href);
const chrome = getChromeSession({ nodePath, mcpEntry });
const snapshot = await chrome.call("take_snapshot", { pageId });
```

`browserSessionPath` 是技能的 `scripts/browser_session.mjs` 绝对路径，`nodePath` 是 Node 可执行文件。`mcpEntry` 取已安装包的 `package.json` 中 `bin.chrome-devtools-mcp` 指向的文件。`chrome.call(name, arguments)` 使用与同名 DevTools 工具相同的参数及返回格式。示例中的 `pageId` 是已定位的目标标签。仅在客户端进程确实退出、需要重新接入时，以 `reconnect: true` 新建持久客户端。

## AI 选品

已有选品授权时，由 AI 在同一 Chrome 搜索、比较并选择，不把搜索和排序默认交回人类。来源未指定时用速卖通；市场、品类和成本约束复用当前任务。已有指定商品或链接就直接处理。

没有具体候选时，先比较少量商品，优先资料完整、规格清楚、图片可用、采购与包装信息能核对的候选；有市场和物流资料时再比较成本与售价。记录实际看到的来源 ID、价格、规格和评价或订单信息，说明选择依据。页面显示价不直接当采购成本，搜索排名不作为盈利证据。真正影响选择的业务缺项集中询问，同时继续读取已有来源资料。

## 插件后台取数

默认使用「速卖通商品采集助手」0.2.0 或兼容版本，复用已安装的同名扩展。缺少采集扩展且当前普通 Chrome 连接支持 `install_extension` 时，可用该工具加载 `assets/aliexpress-collector/` 的绝对路径。安装后核对扩展和 worker。升级文件后提醒用户在 `chrome://extensions` 重新加载并核对版本。

1. 激活选中的商品标签，复用同一连接中已定位的采集 worker。需要定位时，扩展名称和 ID 从 `list_extensions` 取得，该 ID 的 `background.js` worker 从 `list_pages` 取得。手动重新加载后扩展列表可能保留旧版本，最终以 helper 在 worker 内读取的 `chrome.runtime.getManifest().version` 为准。使用实际返回的 `serviceWorkerId`。
2. 用 `browser_call.py extension-read --url SOURCE_URL --output ABSOLUTE_SCRIPT_PATH` 生成调用；执行时传 `sourcePath`、`format: "function"` 和 `serviceWorkerId`，不传商品 `pageId`。
3. 插件后台 `zyingAliExpressCollect` 在匹配商品标签读取数据并直接返回 JSON，不打开弹窗、不点「导出」、不下载文件。多个匹配标签时优先唯一活动标签；仍有歧义才在请求中提供真实 Chrome `tab_id`，它不是工具的 `pageId`。
4. 核对 `ok`、`collector_origin: "extension_service_worker"`、来源 ID 和网址，将完整结果保存到任务工作文件交给 `--source-file`。顶层是 `product` 对象或 `{ok, product}`；图片、规格、变体是对象内数组，不是顶层批量商品数组。

worker 未出现时先核对版本和重载结果，再使用连接器可用的唤醒或恢复能力。仍无法调用时按下方备选方案在普通 Chrome 的商品页取数。弹窗和导出按钮供人类手动使用。

## New、上传和编辑

- `New` 是未保存草稿的显示状态，不是真实编号。网页 New 和 exe 内嵌浏览器 New 都不能作为 `product_id` 传入编辑接口；来源商品 ID 也不是智赢编号。
- 用户要求填草稿时，按 [链接和 JSON 导入](aliexpress-import.md) 填写和读回网页 New。缺类目、采购成本及币种、毛重，或商品需要变体但真实组合未核对时，保留来源 JSON 和已有草稿，等资料齐全再入库。测试值仅用于当次授权实验。
- 已授权入「产品采集」且资料齐全时，用同一来源和原预览快照创建服务器采集产品。结果不明时用原快照 `verify`，报告编号、匹配结果和 `serverOmittedFields` 中的省略项。
- 有数字编号后，优先 [浏览器编辑](browser-product-edit.md) 的五个英文文案字段和批量变体绝对加价。保留其他语言、全部变体和未修改字段，保存后读回；网页可用时不先启动 exe 或 native 登录。

## 备选方案

普通 Chrome 和独立 Chrome 是两种 Chrome 启动方式。默认复用用户正在使用的普通 Chrome，未运行时按普通配置启动。只有用户明确要求独立 Chrome 才使用单独的 Chrome 配置，启动前说明「将启动独立 Chrome，登录状态与普通 Chrome 分开」。exe 内嵌浏览器按下表处理。

默认路线确实不可用且任务需要切换方案时，先用一句话说明原因和实际缺点。

| 方案 | 使用条件 | 需要说明的缺点 |
|---|---|---|
| 同一 Chrome 直接运行采集核心 | 插件未安装、未重载或连接器不能调用 worker，商品页仍可读 | 未经过已安装插件，页面可能缺完整 SKU、币种或描述 |
| exe 内嵌浏览器与缓存 | 用户已在其中采集，或外部商品页无法读取 | 需要另一个窗口，缓存可能旧，依赖客户端缓存布局 |
| native/TCP CLI | 用户指定，或网页不可用且命令支持目标字段 | 登录与网页登录独立，DLL 更新可能需适配，支持字段有限 |
| 页面控件 | 需要操作脚本尚未覆盖的字段 | 可能有无关必填项，保存仍需同源编号读回 |

始终核对同一商品来源。从采集列表导入「我的产品」需要用户明确要求。
