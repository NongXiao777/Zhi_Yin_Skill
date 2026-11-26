# 智赢命令行登录

核验日期：2026-11-26。登录使用桌面客户端的 `common.login` TCP 协议，无需操作登录窗口。已验证本机组件加载、密码编码、合成回环登录响应及 Python→.NET 加密会话互通，并支持当天 16:28 更新后的客户端。真实账户和商品操作需在当前任务验证；具体账户的失败记录属于任务报告。

## 用户在终端输入

只录入并保存，暂不联网：

```powershell
python scripts/zhiying.py credentials-save
python scripts/zhiying.py credentials-status
```

随后使用已保存凭据登录：

```powershell
python scripts/zhiying.py login --saved
```

也可一次完成输入、登录和记住凭据：

```powershell
python scripts/zhiying.py login --remember
```

程序提示手机号和隐藏密码。用户自行在真实终端输入；聊天和助手捕获的命令输出无需包含密码。命令不提供密码参数，也不从环境变量读取密码。终端不能隐藏密码时会停止。仅 `login` 发出登录请求；`credentials-save` 不检验密码是否正确。登录只尝试一次，拒绝后先检查输入和账户状态。

## 本地存储与复用

手机号和密码一起使用当前 Windows 用户的 DPAPI 加密，默认保存到 `%LOCALAPPDATA%\ZhiYingSkill\credentials.dpapi`。可通过 `ZHIYING_CREDENTIAL_FILE` 或 `--credential-file` 指定路径。

成功响应中必须存在有效 `member.token`、`member.userid` 和实际 TCP endpoint，才会保存 `%LOCALAPPDATA%\ZhiYingSkill\session.dpapi`。会话同样 DPAPI 加密，业务命令自动发现它，无需手工填写 token。`ZHIYING_SESSION_FILE` 或 `login --session-file` 可选择其他文件；使用自定义会话文件后，应给业务命令设置同一个 `ZHIYING_SESSION_FILE`。明确指定的历史明文会话 JSON 仍兼容。

```powershell
python scripts/zhiying.py login-status
python scripts/zhiying.py collected-product-live-get --product-id 954521907 --include-copy
```

`credentials-status` 不解密；`login-status` 只报告文件是否存在，不能说明会话仍有效。登录失败或响应缺失时保留旧会话；`login --remember` 在登录成功后才保存凭据。若会话过期，重新 `login --saved`，再执行业务读取。登录验证不需要修改商品。

加密避免明文出现在普通文件、进程参数和日志中。同一 Windows 用户有权限调用 DPAPI 解密，因此它不能隔离同身份运行的助手。脚本只在用户明确请求的登录动作中解密，不提供查看明文命令。

## 原生登录核验

```powershell
python scripts/zhiying.py login-probe
```

该命令使用固定合成数据，返回密码是否已编码、请求长度及 `network_requests_sent: 0`。它不读取保存的凭据、不证明实账户登录成功。

当前版本按 `scripts/native/client-profiles.json` 中 Work/Core/User 的 SHA256 检查反射符号，默认优先选择 `%LOCALAPPDATA%\Programs\ZYing`。`D:\ZYing` 可能是不同版本，先核对实际路径。版本不匹配会停止并返回 `unsupported_client_version`，按 [现场修复](client-update.md) 检查、更新配置并验证。登录服务器沿用客户端默认 TCP pool，可显式使用 `--server-address` 和 `--server-port` 同时覆盖。

字段来自 `ZYing.MLogin` 普通账号分支：`login_acc` 和经 `ZYing.Safe.Encrypt(string)` 编码的 `login_pwd`。TCP 包继续由原生组件生成，包含客户端版本和设备标识；初次登录 token 为空。只读取响应会话字段，不运行会写入其他配置的完整 `Member.Parse`。额外验证、强制改密码或缺失会话会停止，不能当成登录成功。

若真实登录失败，需要优先核对当前安装目录的 `ZYing.User.dll` 中 `MLogin.<登录>d__14.MoveNext` 的普通手机号分支、`ZYing.Work.dll` 中 `common.login` 响应与 TCP pool，以及 `ZYing.Core.dll` 中 `Safe.Encrypt`。提交脱敏字段与调用链即可，无需密码、完整 token 或进程内存转储。

原生窗口呼出、已有桌面会话交接及真实详情响应仍待核验。协作分析时读 [native-login-handoff.md](native-login-handoff.md)；这份交接列出当前版本入口、RVA 和待解问题，不能把它当作已完成的登录功能。
