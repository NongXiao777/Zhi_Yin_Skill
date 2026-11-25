using System;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.IO;
using System.Linq;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;

internal sealed class NativeTransport
{
    private const string RpcTypeName = "ze53.Fe5b";
    private const string WorkHash = "034C95CC20C59037D6177FCB409B7D87AE975AF46C5A1805B10175DF9774C934";
    private static readonly string[] Editable = {
        "sale_title", "sale_brief", "sale_bullet", "sale_keys", "sale_intro", "sale_stock"
    };
    private readonly Type rpcType;
    private readonly Type recordType;
    private readonly Type resultType;
    private readonly object server;
    private static string appDirectory;

    private NativeTransport(string directory, JsonObject session)
    {
        appDirectory = directory;
        string assemblyPath = Path.Combine(directory, "ZYing.Work.dll");
        using (var stream = File.OpenRead(assemblyPath))
        using (var sha = SHA256.Create())
        {
            if (Convert.ToHexString(sha.ComputeHash(stream)) != WorkHash)
                throw new InvalidOperationException("unsupported_client_version");
        }
        AppDomain.CurrentDomain.AssemblyResolve += ResolveAssembly;
        var work = Assembly.LoadFrom(assemblyPath);
        var core = Assembly.LoadFrom(Path.Combine(directory, "ZYing.Core.dll"));
        rpcType = work.GetType(RpcTypeName, true);
        recordType = core.GetType("ZYing.Data.Record", true);
        resultType = work.GetType("ZYing.ZResult", true);
        var member = work.GetType("ZYing.Member", true);

        var address = IPAddress.Parse(session["server_address"].GetValue<string>());
        int port = session["server_port"].GetValue<int>();
        if (port < 1 || port > 65535)
            throw new InvalidOperationException("invalid_session_configuration");
        Guid token = Guid.Parse(session["token"].GetValue<string>());
        if (token == Guid.Empty)
            throw new InvalidOperationException("invalid_session_configuration");
        member.GetField("Token").SetValue(null, token);
        if (session["user_id"] != null)
            member.GetField("UserID").SetValue(null, session["user_id"].GetValue<int>());

        var poolType = rpcType.GetNestedType("IK7o", BindingFlags.NonPublic | BindingFlags.Public);
        server = Activator.CreateInstance(poolType, new object[] { new IPEndPoint(address, port) });
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
        rpcType.GetField("tei4").SetValue(rpc, command);
        // This branch suppresses the client's error-dialog/retry path. Failures propagate to the CLI.
        rpcType.GetField("AeiX").SetValue(rpc, false);
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
                method = rpcType.GetMethod("lenP", new[] { typeof(string), typeof(int) });
                parameters = new object[] { "id", id };
            }
            else
            {
                method = rpcType.GetMethod("Ren4", new[] { recordType.MakeArrayType() });
                parameters = new[] { data };
            }
            var task = (Task)method.Invoke(rpc, parameters);
            if (await Task.WhenAny(task, Task.Delay(20000)) != task)
                throw new InvalidOperationException("tcp_timeout");
            await task;
            var result = task.GetType().GetProperty("Result").GetValue(task);
            if ((bool)resultType.GetField("IsErr").GetValue(result))
                throw new InvalidOperationException("server_rejected_request");
            return result;
        }
        finally
        {
            rpcType.GetMethod("Kenv", Type.EmptyTypes).Invoke(rpc, null);
        }
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
        var rows = JsonNode.Parse(json) as JsonArray;
        if (rows == null || rows.Count != 1 || rows[0] is not JsonObject row)
            throw new InvalidOperationException("unexpected_detail_shape");
        return row;
    }

    private async Task<JsonObject> Read(int id)
    {
        var record = ResultRecord(await Send("spider.detail", id));
        if (record["sale_id"] == null || record["sale_id"].ToString() != id.ToString())
            throw new InvalidOperationException("wrong_product");
        return record;
    }

    private async Task<JsonObject> Update(int id, JsonObject input)
    {
        var fields = input["fields"] as JsonObject;
        var expected = input["expected"] as JsonObject;
        if (fields == null || expected == null || fields.Count == 0 ||
            fields.Count != expected.Count || fields.Any(p => !Editable.Contains(p.Key) || !expected.ContainsKey(p.Key)))
            throw new InvalidOperationException("invalid_update_fields");
        var current = await Read(id);
        foreach (var pair in fields)
        {
            if (current[pair.Key]?.ToJsonString() != expected[pair.Key]?.ToJsonString())
                return new JsonObject { ["ok"] = false, ["error"] = "conflict" };
            if (pair.Value is not JsonValue value || !value.TryGetValue<string>(out var _))
                throw new InvalidOperationException("native_fields_require_json_strings");
        }
        var update = new JsonObject { ["id"] = id };
        foreach (var pair in fields)
            update[pair.Key] = JsonNode.Parse(pair.Value.ToJsonString());
        var record = recordType.GetMethod("FromJson", new[] { typeof(string) })
                               .Invoke(null, new object[] { update.ToJsonString() });
        var rows = Array.CreateInstance(recordType, 1);
        rows.SetValue(record, 0);
        await Send("spider.update", rows);
        return new JsonObject { ["ok"] = true };
    }

    private JsonObject Probe()
    {
        var rpc = NewRequest("spider.detail");
        var values = new NameValueCollection { { "id", "1001" } };
        var payload = (byte[])rpcType.GetMethod("yenK", BindingFlags.NonPublic | BindingFlags.Static)
                                    .Invoke(null, new object[] { values });
        var frame = (byte[])rpcType.GetMethod("tenu", BindingFlags.NonPublic | BindingFlags.Instance)
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
            "unsupported_client_version", "invalid_session_configuration", "tcp_timeout",
            "server_rejected_request", "missing_detail_record", "unexpected_detail_shape",
            "wrong_product", "invalid_update_fields", "native_fields_require_json_strings",
            "unsupported_command", "missing_session_file", "request_too_large"
        };
        return publicErrors.Contains(exception.Message) ? exception.Message : "native_transport_failed";
    }

    private static async Task<int> Main(string[] args)
    {
        try
        {
            if (args.Length != 1 || !Directory.Exists(args[0]))
                throw new InvalidOperationException("invalid_session_configuration");
            Console.InputEncoding = System.Text.Encoding.UTF8;
            Console.OutputEncoding = new System.Text.UTF8Encoding(false);
            string text = Console.In.ReadToEnd();
            if (text.Length > 10000000)
                throw new InvalidOperationException("request_too_large");
            var input = JsonNode.Parse(text) as JsonObject;
            string command = input?["command"]?.GetValue<string>();
            bool probe = command == "native.probe";
            string file = Environment.GetEnvironmentVariable("ZHIYING_SESSION_FILE");
            JsonObject session;
            if (probe)
            {
                session = new JsonObject {
                    ["server_address"] = "127.0.0.1", ["server_port"] = 43210,
                    ["token"] = Guid.NewGuid().ToString()
                };
            }
            else
            {
                if (string.IsNullOrEmpty(file) || !File.Exists(file))
                    throw new InvalidOperationException("missing_session_file");
                session = JsonNode.Parse(File.ReadAllText(file)) as JsonObject;
            }
            var transport = new NativeTransport(args[0], session);
            JsonObject response;
            if (probe)
                response = transport.Probe();
            else
            {
                int id = input["id"].GetValue<int>();
                if (id <= 0)
                    throw new InvalidOperationException("wrong_product");
                if (command == "spider.detail")
                    response = new JsonObject { ["ok"] = true, ["record"] = await transport.Read(id) };
                else if (command == "spider.update")
                    response = await transport.Update(id, input);
                else
                    throw new InvalidOperationException("unsupported_command");
            }
            Console.WriteLine(response.ToJsonString());
            return 0;
        }
        catch (Exception exception)
        {
            Console.WriteLine(JsonSerializer.Serialize(new { ok = false, error = ErrorCode(exception) }));
            return 1;
        }
    }
}
