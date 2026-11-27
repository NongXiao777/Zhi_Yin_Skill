using System;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.IO;
using System.Linq;
using System.Net;
using System.Reflection;
using System.Reflection.Emit;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;

internal sealed class NativeTransport
{
    private readonly JsonObject profile;
    private string Symbol(string key) => profile[key].GetValue<string>();
    private static JsonObject SelectProfile(string directory, string profileFile)
    {
        string Hash(string filename)
        {
            using var stream = File.OpenRead(Path.Combine(directory, filename));
            using var sha = SHA256.Create();
            return Convert.ToHexString(sha.ComputeHash(stream));
        }
        string work = Hash("ZYing.Work.dll"), core = Hash("ZYing.Core.dll"), user = Hash("ZYing.User.dll");
        var profiles = JsonNode.Parse(File.ReadAllText(profileFile)) as JsonArray;
        var match = profiles?.OfType<JsonObject>().SingleOrDefault(p =>
            p["work_sha256"]?.GetValue<string>() == work && p["core_sha256"]?.GetValue<string>() == core &&
            p["user_sha256"]?.GetValue<string>() == user);
        return match ?? throw new InvalidOperationException("unsupported_client_version");
    }
    private sealed class LoginRejected : Exception
    {
        internal readonly string Reason;
        internal readonly long Result;
        internal LoginRejected(string message, long result) : base("login_rejected")
        {
            Result = result;
            Reason = message switch {
                _ when message.Contains("密码错误") || message.Contains("密码不正确") || message.Contains("账号或密码") => "credentials_rejected",
                _ when message.Contains("账号不存在") || message.Contains("用户不存在") => "account_not_found",
                _ when message.Contains("版本过低") || message.Contains("升级客户端") => "client_update_required",
                _ when message.Contains("验证码") || message.Contains("二次验证") => "additional_verification_required",
                _ when message.Contains("账号被禁用") || message.Contains("账号已禁用") || message.Contains("账号被冻结") => "account_unavailable",
                _ => "unclassified"
            };
        }
    }
    private sealed class ServerRejected : Exception
    {
        internal readonly string Reason;
        internal readonly long Result;
        internal ServerRejected(string message, long result) : base("server_rejected_request")
        {
            Result = result;
            Reason = message switch {
                _ when message.Contains("登录") || message.Contains("登陆") => "session_rejected",
                _ when message.Contains("权限") || message.Contains("授权") => "permission_denied",
                _ when message.Contains("命令") || message.Contains("指令") => "command_rejected",
                _ when message.Contains("不存在") || message.Contains("找不到") => "record_not_found",
                _ when message.Contains("参数") => "invalid_parameters",
                _ => "unclassified"
            };
        }
    }
    private static readonly string[] Editable = {
        "sale_title", "sale_brief", "sale_bullet", "sale_keys", "sale_intro", "sale_stock"
    };
    private readonly Type rpcType;
    private readonly Type recordType;
    private readonly Type resultType;
    private readonly Type memberType;
    private readonly Assembly coreAssembly;
    private readonly object server;
    private IPEndPoint lastEndpoint;
    private static string appDirectory;

    private NativeTransport(string directory, string profileFile, JsonObject session, bool login, JsonObject sessionHashes)
    {
        appDirectory = directory;
        string assemblyPath = Path.Combine(directory, "ZYing.Work.dll");
        profile = SelectProfile(directory, profileFile);
        if (sessionHashes != null &&
            (sessionHashes["work_sha256"]?.GetValue<string>() != Symbol("work_sha256") ||
             sessionHashes["user_sha256"]?.GetValue<string>() != Symbol("user_sha256")))
            throw new InvalidOperationException("client_relogin_required");
        AppDomain.CurrentDomain.AssemblyResolve += ResolveAssembly;
        var work = Assembly.LoadFrom(assemblyPath);
        coreAssembly = Assembly.LoadFrom(Path.Combine(directory, "ZYing.Core.dll"));
        rpcType = work.GetType(Symbol("rpc_type"), true);
        recordType = coreAssembly.GetType("ZYing.Data.Record", true);
        resultType = work.GetType("ZYing.ZResult", true);
        memberType = work.GetType("ZYing.Member", true);

        // A login has no existing member token. The native frame still supplies the
        // client's version and generated device identifier, as the desktop does.
        if (login)
        {
            memberType.GetField("Token").SetValue(null, Guid.Empty);
            string state = profile["exchange_state_field"]?.GetValue<string>();
            if (!string.IsNullOrEmpty(state)) rpcType.GetField(state).SetValue(null, 0);
        }
        else
        {
            Guid token = Guid.Parse(session["token"].GetValue<string>());
            if (token == Guid.Empty)
                throw new InvalidOperationException("invalid_session_configuration");
            memberType.GetField("Token").SetValue(null, token);
            if (session["exchange_state"] != null)
            {
                string state = profile["exchange_state_field"]?.GetValue<string>();
                if (string.IsNullOrEmpty(state)) throw new InvalidOperationException("unsupported_client_version");
                rpcType.GetField(state).SetValue(null, session["exchange_state"].GetValue<int>());
            }
            if (session["device_id"] != null)
            {
                // Preserve the desktop identity in this helper process only.
                // Reflection.SetValue disallows InitOnly fields after initialization.
                string deviceField = profile["device_id_field"]?.GetValue<string>();
                if (string.IsNullOrEmpty(deviceField)) throw new InvalidOperationException("unsupported_client_version");
                var field = rpcType.GetField(deviceField);
                var setter = new DynamicMethod("SetSessionDevice", typeof(void), new[] { typeof(Guid) }, rpcType, true);
                var il = setter.GetILGenerator();
                il.Emit(OpCodes.Ldarg_0); il.Emit(OpCodes.Stsfld, field); il.Emit(OpCodes.Ret);
                ((Action<Guid>)setter.CreateDelegate(typeof(Action<Guid>)))(Guid.Parse(session["device_id"].GetValue<string>()));
            }
            if (session["user_id"] != null)
                memberType.GetField("UserID").SetValue(null, session["user_id"].GetValue<int>());
        }

        if (login && session == null)
            server = rpcType.GetField(Symbol("login_server_field")).GetValue(null);
        else
        {
            var address = IPAddress.Parse(session["server_address"].GetValue<string>());
            int port = session["server_port"].GetValue<int>();
            if (port < 1 || port > 65535)
                throw new InvalidOperationException("invalid_session_configuration");
            var poolType = work.GetType(Symbol("server_type"), true);
            server = Activator.CreateInstance(poolType, new object[] { new IPEndPoint(address, port) });
        }
        if (server == null)
            throw new InvalidOperationException("login_endpoint_unavailable");
    }

    private static Assembly ResolveAssembly(object sender, ResolveEventArgs args)
    {
        string file = Path.Combine(appDirectory, new AssemblyName(args.Name).Name + ".dll");
        return File.Exists(file) ? Assembly.LoadFrom(file) : null;
    }

    private object NewRequest(string command)
    {
        var rpc = Activator.CreateInstance(rpcType, BindingFlags.Instance | BindingFlags.NonPublic,
                                          null, new[] { server }, null);
        rpcType.GetField(Symbol("command_field")).SetValue(rpc, command);
        // This branch suppresses the client's error-dialog/retry path. Failures propagate to the CLI.
        rpcType.GetField(Symbol("interactive_field")).SetValue(rpc, false);
        return rpc;
    }

    private async Task<object> Send(string command, object data)
    {
        var rpc = NewRequest(command);
        try
        {
            MethodInfo method;
            object[] parameters;
            if (data is int id)
            {
                method = rpcType.GetMethod(Symbol("send_id_method"), new[] { typeof(string), typeof(int) });
                parameters = new object[] { "id", id };
            }
            else
            {
                method = rpcType.GetMethod(Symbol("send_records_method"), new[] { recordType.MakeArrayType() });
                parameters = new[] { data };
            }
            var task = (Task)method.Invoke(rpc, parameters);
            if (await Task.WhenAny(task, Task.Delay(20000)) != task)
                throw new InvalidOperationException("tcp_timeout");
            await task;
            var result = task.GetType().GetProperty("Result").GetValue(task);
            lastEndpoint = rpcType.GetField(Symbol("endpoint_field"), BindingFlags.NonPublic | BindingFlags.Instance)
                                  .GetValue(rpc) as IPEndPoint;
            if ((bool)resultType.GetField("IsErr").GetValue(result))
            {
                if (command == "common.login")
                    throw new LoginRejected((string)resultType.GetField("Message").GetValue(result) ?? "",
                                            (long)resultType.GetField("Result").GetValue(result));
                throw new ServerRejected((string)resultType.GetField("Message").GetValue(result) ?? "",
                                         (long)resultType.GetField("Result").GetValue(result));
            }
            return result;
        }
        finally
        {
            rpcType.GetMethod(Symbol("close_method"), Type.EmptyTypes).Invoke(rpc, null);
        }
    }

    private object LoginRecord(string phone, string password)
    {
        string digits = phone?.Trim().TrimStart('+');
        if (string.IsNullOrWhiteSpace(phone) || digits.Length < 6 || digits.Length > 20 ||
            digits.Any(c => c < '0' || c > '9') || phone.Trim().Count(c => c == '+') > 1 ||
            string.IsNullOrEmpty(password) || password.Length > 4096 || password.Contains('\0'))
            throw new InvalidOperationException("invalid_login_input");
        phone = phone.Trim();
        string encoded = (string)coreAssembly.GetType("ZYing.Safe", true)
            .GetMethod("Encrypt", new[] { typeof(string) }).Invoke(null, new object[] { password });
        // Safe.Encrypt returns its original input on a cryptographic failure.
        // Stop here instead of ever sending an unencoded password.
        if (string.IsNullOrEmpty(encoded) || encoded == password)
            throw new InvalidOperationException("password_encoding_failed");
        byte[] bytes = Convert.FromBase64String(encoded);
        if (bytes.Length == 0 || bytes.Length % 8 != 0)
            throw new InvalidOperationException("password_encoding_failed");
        var input = new JsonObject { ["login_acc"] = phone, ["login_pwd"] = encoded };
        return recordType.GetMethod("FromJson", new[] { typeof(string) })
                         .Invoke(null, new object[] { input.ToJsonString() });
    }

    private JsonObject LoginSession(object result)
    {
        var records = resultType.GetField("RS").GetValue(result);
        if (records == null)
            throw new InvalidOperationException("login_response_incomplete");
        var item = records.GetType().GetProperty("Item", new[] { typeof(string) });
        var force = item.GetValue(records, new object[] { "force_pwd" });
        if (force != null && (int)recordType.GetMethod("GetInt", new[] { typeof(string) })
                                          .Invoke(force, new object[] { "force" }) == 1)
            throw new InvalidOperationException("password_change_required");
        var member = item.GetValue(records, new object[] { "member" });
        if (member == null)
            throw new InvalidOperationException("login_response_incomplete");
        Guid token = (Guid)recordType.GetMethod("GetGuid", new[] { typeof(string) })
                                    .Invoke(member, new object[] { "token" });
        int user = (int)recordType.GetMethod("GetInt", new[] { typeof(string) })
                                 .Invoke(member, new object[] { "userid" });
        if (token == Guid.Empty || user <= 0 || lastEndpoint == null)
            throw new InvalidOperationException("login_response_incomplete");
        // Read only these session columns: Member.Parse also consumes unrelated
        // service credentials and runs client configuration side effects.
        var session = new JsonObject {
            ["server_address"] = lastEndpoint.Address.ToString(), ["server_port"] = lastEndpoint.Port,
            ["token"] = token.ToString(), ["user_id"] = user
        };
        string deviceField = profile["device_id_field"]?.GetValue<string>();
        if (!string.IsNullOrEmpty(deviceField))
            session["device_id"] = ((Guid)rpcType.GetField(deviceField).GetValue(null)).ToString();
        string stateField = profile["exchange_state_field"]?.GetValue<string>();
        if (!string.IsNullOrEmpty(stateField))
            session["exchange_state"] = (int)rpcType.GetField(stateField).GetValue(null);
        return session;
    }

    private async Task<JsonObject> Login(JsonObject input)
    {
        var rows = Array.CreateInstance(recordType, 1);
        rows.SetValue(LoginRecord(input["phone"].GetValue<string>(), input["password"].GetValue<string>()), 0);
        var result = await Send("common.login", rows);
        return new JsonObject {
            ["ok"] = true, ["authenticated"] = true, ["session"] = LoginSession(result),
            ["client_hashes"] = new JsonObject {
                ["work_sha256"] = Symbol("work_sha256"), ["user_sha256"] = Symbol("user_sha256")
            }
        };
    }

    private JsonObject LoginProbe()
    {
        const string phone = "13800000000";
        const string password = "synthetic-login-秘密";
        var record = LoginRecord(phone, password);
        string encoded = (string)recordType.GetMethod("Get", new[] { typeof(string) })
                                           .Invoke(record, new object[] { "login_pwd" });
        var records = Activator.CreateInstance(coreAssembly.GetType("ZYing.Data.RecordSet", true));
        records.GetType().GetMethod("Add", new[] { recordType }).Invoke(records, new object[] { record });
        var payload = (byte[])records.GetType().GetMethod("ToBytes", Type.EmptyTypes).Invoke(records, null);
        var rpc = NewRequest("common.login");
        try
        {
            var loginServer = rpcType.GetField(Symbol("login_server_field")).GetValue(null);
            var endpoint = loginServer?.GetType().GetMethod(Symbol("endpoint_method"), Type.EmptyTypes)
                                      .Invoke(loginServer, null) as IPEndPoint;
            var frame = (byte[])rpcType.GetMethod(Symbol("frame_method"), BindingFlags.NonPublic | BindingFlags.Instance)
                                      .Invoke(rpc, new object[] { payload });
            return new JsonObject {
                ["ok"] = true, ["native_components_loaded"] = true,
                ["login_command"] = "common.login", ["password_was_encoded"] = encoded != password,
                ["login_endpoint_resolved"] = endpoint != null && endpoint.Port > 0 && endpoint.Port <= 65535,
                ["parameter_bytes"] = payload.Length, ["request_bytes"] = frame.Length,
                ["network_requests_sent"] = 0, ["authenticated"] = false
            };
        }
        finally { rpcType.GetMethod(Symbol("close_method"), Type.EmptyTypes).Invoke(rpc, null); }
    }

    private static JsonObject LoadSession(out JsonObject clientHashes)
    {
        clientHashes = null;
        string file = Environment.GetEnvironmentVariable("ZHIYING_SESSION_FILE");
        bool explicitFile = !string.IsNullOrEmpty(file);
        if (!explicitFile)
            file = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                "ZhiYingSkill", "session.dpapi");
        if (!File.Exists(file))
            throw new InvalidOperationException("missing_session_file");
        if (new FileInfo(file).Length > 1000000)
            throw new InvalidOperationException("invalid_session_configuration");
        var envelope = JsonNode.Parse(File.ReadAllText(file)) as JsonObject;
        if (envelope?["protection"] == null && explicitFile)
            return envelope;
        if (envelope?["version"]?.GetValue<int>() != 1 ||
            envelope?["protection"]?.GetValue<string>() != "windows-dpapi-current-user" ||
            envelope?["purpose"]?.GetValue<string>() != "zhiying-login-session")
            throw new InvalidOperationException("invalid_session_configuration");
        if (envelope.TryGetPropertyValue("client_hashes", out var binding))
            clientHashes = binding as JsonObject ?? throw new InvalidOperationException("invalid_session_configuration");
        byte[] plaintext = null;
        try
        {
            var ciphertext = Convert.FromBase64String(envelope["data"].GetValue<string>());
            plaintext = ProtectedData.Unprotect(ciphertext, null, DataProtectionScope.CurrentUser);
            return JsonNode.Parse(System.Text.Encoding.UTF8.GetString(plaintext)) as JsonObject;
        }
        catch { throw new InvalidOperationException("invalid_protected_session"); }
        finally { if (plaintext != null) CryptographicOperations.ZeroMemory(plaintext); }
    }

    private JsonObject ResultRecord(object result)
    {
        var records = resultType.GetField("RS").GetValue(result);
        if (records == null)
            throw new InvalidOperationException("missing_detail_record");
        var root = records.GetType().GetProperty("Item", new[] { typeof(string) })
                          .GetValue(records, new object[] { "root" });
        if (root == null)
            throw new InvalidOperationException("missing_detail_record");
        string json = (string)recordType.GetMethod("ToJson", new[] { typeof(string[]) })
                                       .Invoke(root, new object[] { null });
        var parsed = JsonNode.Parse(json);
        var rows = parsed as JsonArray ?? (parsed as JsonObject)?["data"] as JsonArray;
        if (rows != null && rows.Count == 0)
            throw new InvalidOperationException("product_not_found");
        if (rows == null || rows.Count != 1 || rows[0] is not JsonObject row)
            throw new InvalidOperationException("unexpected_detail_shape");
        rows.RemoveAt(0);
        return row;
    }

    private async Task<JsonObject> Read(int id, string command = "spider.detail")
    {
        var record = ResultRecord(await Send(command, id));
        if (record["sale_id"] == null || record["sale_id"].ToString() != id.ToString())
            throw new InvalidOperationException("wrong_product");
        return record;
    }

    private async Task<JsonObject> Update(int id, JsonObject input, string command = "spider.update")
    {
        var fields = input["fields"] as JsonObject;
        var expected = input["expected"] as JsonObject;
        if (fields == null || expected == null || fields.Count == 0 ||
            fields.Count != expected.Count || fields.Any(p => !Editable.Contains(p.Key) || !expected.ContainsKey(p.Key)))
            throw new InvalidOperationException("invalid_update_fields");
        var current = await Read(id, command == "sale.update" ? "sale.detail" : "spider.detail");
        foreach (var pair in fields)
        {
            if (current[pair.Key]?.ToJsonString() != expected[pair.Key]?.ToJsonString())
                return new JsonObject { ["ok"] = false, ["error"] = "conflict" };
            if (pair.Value is not JsonValue value || !value.TryGetValue<string>(out var _))
                throw new InvalidOperationException("native_fields_require_json_strings");
        }
        var update = new JsonObject { ["sale_id"] = id };
        foreach (var pair in fields)
            update[pair.Key] = JsonNode.Parse(pair.Value.ToJsonString());
        var record = recordType.GetMethod("FromJson", new[] { typeof(string) })
                               .Invoke(null, new object[] { update.ToJsonString() });
        var rows = Array.CreateInstance(recordType, 1);
        rows.SetValue(record, 0);
        await Send(command, rows);
        return new JsonObject { ["ok"] = true };
    }

    private JsonObject Probe()
    {
        var rpc = NewRequest("spider.detail");
        var values = new NameValueCollection { { "id", "1001" } };
        var payload = (byte[])rpcType.GetMethod(Symbol("values_method"), BindingFlags.NonPublic | BindingFlags.Static)
                                    .Invoke(null, new object[] { values });
        var frame = (byte[])rpcType.GetMethod(Symbol("frame_method"), BindingFlags.NonPublic | BindingFlags.Instance)
                                  .Invoke(rpc, new object[] { payload });
        return new JsonObject {
            ["ok"] = true, ["native_components_loaded"] = true,
            ["parameter_bytes"] = payload.Length, ["request_bytes"] = frame.Length,
            ["network_requests_sent"] = 0
        };
    }

    private static string ErrorCode(Exception exception)
    {
        while (exception.InnerException != null)
            exception = exception.InnerException;
        string[] publicErrors = {
            "unsupported_client_version", "client_relogin_required", "invalid_session_configuration", "tcp_timeout",
            "server_rejected_request", "missing_detail_record", "unexpected_detail_shape", "product_not_found",
            "wrong_product", "invalid_update_fields", "native_fields_require_json_strings",
            "unsupported_command", "missing_session_file", "request_too_large"
            , "invalid_login_input", "password_encoding_failed", "login_endpoint_unavailable",
            "login_rejected", "login_response_incomplete",
            "password_change_required", "private_login_pipe_required", "invalid_protected_session"
        };
        return publicErrors.Contains(exception.Message) ? exception.Message : "native_transport_failed";
    }

    private static async Task<int> Main(string[] args)
    {
        try
        {
            if (args.Length != 2 || !Directory.Exists(args[0]) || !File.Exists(args[1]))
                throw new InvalidOperationException("invalid_session_configuration");
            Console.InputEncoding = System.Text.Encoding.UTF8;
            Console.OutputEncoding = new System.Text.UTF8Encoding(false);
            string text = Console.In.ReadToEnd();
            if (text.Length > 10000000)
                throw new InvalidOperationException("request_too_large");
            var input = JsonNode.Parse(text) as JsonObject;
            string command = input?["command"]?.GetValue<string>();
            bool probe = command == "native.probe";
            bool loginProbe = command == "login.probe";
            bool login = command == "common.login";
            if (login && (!Console.IsInputRedirected || !Console.IsOutputRedirected))
                throw new InvalidOperationException("private_login_pipe_required");
            JsonObject session;
            JsonObject sessionHashes = null;
            if (probe || loginProbe)
            {
                session = new JsonObject {
                    ["server_address"] = "127.0.0.1", ["server_port"] = 43210,
                    ["token"] = Guid.NewGuid().ToString()
                };
            }
            else if (login)
            {
                bool hasAddress = input["server_address"] != null;
                bool hasPort = input["server_port"] != null;
                if (hasAddress != hasPort)
                    throw new InvalidOperationException("invalid_session_configuration");
                session = hasAddress ? input : null;
            }
            else
                session = LoadSession(out sessionHashes);
            var transport = new NativeTransport(args[0], args[1], session, login || loginProbe, sessionHashes);
            JsonObject response;
            if (probe)
                response = transport.Probe();
            else if (loginProbe)
                response = transport.LoginProbe();
            else if (login)
                response = await transport.Login(input);
            else
            {
                int id = input["id"].GetValue<int>();
                if (id <= 0)
                    throw new InvalidOperationException("wrong_product");
                if (command == "spider.detail" || command == "sale.detail")
                    response = new JsonObject { ["ok"] = true, ["record"] = await transport.Read(id, command) };
                else if (command == "spider.update" || command == "sale.update")
                    response = await transport.Update(id, input, command);
                else
                    throw new InvalidOperationException("unsupported_command");
            }
            Console.WriteLine(response.ToJsonString());
            return 0;
        }
        catch (Exception exception)
        {
            while (exception.InnerException != null) exception = exception.InnerException;
            if (exception is LoginRejected rejected)
                Console.WriteLine(JsonSerializer.Serialize(new { ok = false, error = "login_rejected",
                    reason = rejected.Reason, server_result = rejected.Result }));
            else if (exception is ServerRejected failure)
                Console.WriteLine(JsonSerializer.Serialize(new { ok = false, error = "server_rejected_request",
                    reason = failure.Reason, server_result = failure.Result }));
            else
                Console.WriteLine(JsonSerializer.Serialize(new { ok = false, error = ErrorCode(exception) }));
            return 1;
        }
    }
}
