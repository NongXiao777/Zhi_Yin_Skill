# 客户端更新后的现场修复

遇到 `unsupported_client_version`，或更新后出现反射相关的 `native_transport_failed`，在当前任务中检查实际安装 DLL，修复本地 Skill 副本后继续已授权工作。用户不必每次重新授权这种本地修复。未知写入结果仍须先读取现状，不能重跑增量改价或追加文字。

## 记录更新前基线和对比更新后 DLL

```powershell
python scripts/zhiying.py --app "$env:LOCALAPPDATA\Programs\ZYing\ZYing.exe" client-diagnose --symbols
```

`client-diagnose` 只读取当前安装目录的 Core、Work、User DLL 和仓库里的 `scripts/native/client-profiles.json`。`dlls` 逐项显示 `matched`、`changed`、`missing` 或 `unreadable`，`sha256` 和 `baseline_sha256` 提供实测及基线哈希。可以把 JSON 输出保存在任务工作目录作为更新前记录。已记录的 TCP 类型依次为 `ze53.Fe5b`、`cBSF.ABSs`、`JgP5.ggPZ`，每个配置都保存了三份 DLL 的哈希。

默认显示完整匹配的旧版或新版配置。没有完整匹配时，与匹配 DLL 最多的配置比较，同分选清单中较新的条目。用 `--baseline 2026-11-27-1255` 固定对照版本。`ok` 表示诊断完成，`supported` 表示三个 DLL 完整命中同一个配置。DLL 哈希变化只说明文件内容变化。Work 已匹配时，可直接沿用该 Work 哈希对应的类型名称作为核验线索。User 已变化时，优先检查桌面登录调用链。

## 定位新的混淆类型

`--symbols` 用 PowerShell 7 扫描 Work DLL 的 PE 元数据。它用 TCP 客户端字段以及返回 `Task<ZYing.ZResult>` 的两个发送签名 `(string, int)`、`(ZYing.Data.Record[])` 定位 `rpc_type`，并列出发送方法、嵌套服务器类型和端点方法。以 `rpc_inspection.candidates` 缩小范围。若有多个候选或没有候选，回到下面的调用链核对。若报告扫描期间 Work DLL 改变，等更新完成后重新诊断。

`scripts/native/Inspect.ps1` 只读取 DLL 的元数据和 IL，不读取配置、进程内存、凭据，也不联网。用 PowerShell 7 运行，输出存入任务的临时目录：

```powershell
$appDir = "$env:LOCALAPPDATA\Programs\ZYing"
pwsh -NoProfile -File scripts/native/Inspect.ps1 -AppDirectory $appDir -TypeMatch 'MLogin.*登录' -MethodMatch '^MoveNext$' -IncludeIL
pwsh -NoProfile -File scripts/native/Inspect.ps1 -AppDirectory $appDir -TypeMatch '^JgP5\.ggPZ(?:\+DcoB)?$'
```

把第二条命令中的类型替换成诊断输出的候选全名，使用正则时转义句点和加号。加上 `-MethodMatch '方法正则' -IncludeIL` 可继续核对指定方法。沿登录状态机中对候选类的字段访问和调用处确认默认服务器、命令字段等符号。11 月 27 日版在 `ZYing.MLogin+<登录>d__14.MoveNext` 中写入 `JgP5.ggPZ::mgdo`，在 `QgYn` 构建请求帧时读取命令字段 `ggIi`。

## 维护版本配置

`scripts/native/client-profiles.json` 保存 Work/Core/User 的 SHA256 和对应符号；执行器只接受三者完全匹配的配置。保留已有配置并新增当前版本，不能只换哈希或取消版本检查。

从元数据和调用链核对：TCP 类型、服务器类型、默认登录服务器字段、命令字段、抑制弹窗/重试字段、整数发送方法、Record 数组发送方法、实际端点字段、关闭方法、键值参数编码方法、帧构建方法及交换状态字段。签名和调用用途应共同支持判断，混淆名称没有固定含义。

常见稳定线索：`ZYing.ZResult` 的 `IsErr/Message/Result/RS`，`ZYing.Member.Token/UserID`，`ZYing.Data.Record` 和 `RecordSet`。普通登录通常是 `common.login`、`login_acc`、`login_pwd` 和 `ZYing.Safe.Encrypt(string)`；“我的产品”是 `sale.detail/update`，“产品采集”是 `spider.detail/update`。这些是定位线索，仍应对当前 DLL 核验。`MLogin` 的登录异步状态机可确认真实参数、默认服务器和初始化；商品提交状态机可确认实际发出的 Record。应追踪 Record 对象来源，不能把本地列表回调的 `id` 与线上 Record 的 `sale_id` 混淆。

参数或响应结构变化时，调整执行器和相关 Python 解析，而不只更换配置。编译使用 `Build.ps1`，缓存由 C# 源码哈希决定；配置文件每次读取，无需手工删除缓存。

## 验证后继续任务

```powershell
python scripts/zhiying.py login-probe
python scripts/zhiying.py collected-transport-probe
$env:ZHIYING_NATIVE_TEST_APP="$env:LOCALAPPDATA\Programs\ZYing\ZYing.exe"
python -m unittest discover -s tests -p test_native_transport.py
```

探针必须返回 `network_requests_sent: 0`。原生测试使用合成凭据和回环服务器，应覆盖真实编码、响应等待、登录会话提取、拒绝/额外验证、DPAPI 互通和商品读取。调整相关业务代码后运行对应测试。当前版本通过验证后，若它的 Work 或 User 哈希与上次登录不同，用 `login-native --if-needed` 重新登录，先读取商品，再执行已授权修改并读回。

保存前保留完整语言和变体集合，检查要改字段的 `expected` 基线。读回匹配提交字段后才能报告成功；审核状态、同步等其他服务端变化需额外读取检查。若保存结果不明，先读商品，不自动重试。若登录被拒绝，区分已保存输入、桌面分支、额外验证和服务器要求；不要把版本更新自动当作所有失败的原因。

若当前 DLL 无法从静态证据映射，保留已完成的本地改动，说明具体缺失类型/调用链及所需脱敏二进制分析。无需请求用户提供密码、完整 token 或内存转储。
