# 持久商品计划与还原

使用 CLI 商品传输器时，可用持久计划保存预览、继续任务或按要求还原。使用内置 TCP 时沿用当前版本配置和 DPAPI 会话。普通 Chrome 编辑继续走 [网页预览和核验](browser-product-edit.md)，保留原预览结果以便恢复核验。

```powershell
python scripts/zhiying.py product-plan --namespace sale --product-id 951393413 --adjust-surcharge KEY1 0.01 --adjust-surcharge KEY2 0.01 --append-intro "*" --output work/plan.local.json
python scripts/zhiying.py product-plan-show --plan work/plan.local.json
python scripts/zhiying.py product-apply --plan work/plan.local.json
python scripts/zhiying.py product-restore --plan work/plan.local.json
```

`sale` 对应“我的产品”，`spider` 对应“产品采集”。示例中的键必须替换为真实且唯一的变体键；`product-plan` 只读取并生成计划，没有商品写入。也支持现有 `--set-surcharge`、`--intro-file`、`--copy-file` 参数。计划保存完整原快照、目标快照和实际差异，应放在任务 `work/` 或 `*.local.json`；不包含登录密码或 token。

`product-apply` 重新校验实际差异与计划展示一致，只允许既有变体的加价及英文文案字段。保存前重读将修改的完整列并比较基线，写入前将状态持久化为 `write_attempted`。同一计划文件持有操作系统文件锁，禁止并发和重复执行；保存结果未知时不能重新 apply。不同计划文件之间以及人工编辑仍需协调。

`product-plan-show` 只校验并显示本地计划和保存状态。CLI 写入结果未知时，用对应来源的 `product-live-get` 或 `collected-product-live-get` 查询服务器。用户要求撤销时才使用 `product-restore`，该命令可能写回原值。已还原计划再次 restore 是空操作，仅报告此前的核验结果。

读回分开报告目标内容、改动列是否匹配和 `other_changed_fields`。服务端正常更新 `sale_log` 会列入额外变化，不会把已经正确保存的目标内容判成失败。桌面界面可能稍后才刷新，以服务器读回为准。

`product-restore` 只撤销计划改过的加价或英文语言值，保留其他变体、库存、图片和其他语言的后续编辑。每个目标当前必须等于计划原值或计划目标值；若目标被别人改过，停止还原。已经是原值时不发送写入。未知还原结果再次调用时先读当前值，不盲目重放。服务端原子条件写入尚未核验，执行器会在发包前再检查完整列基线。

本功能吸收 PR #3 的持久意图、文件锁及恢复设计，修正了全量日志比较和计划展示与实际目标可能不一致的问题。其旧 TCP、旧 Guid 导出和另一套 DPAPI 格式未纳入。
