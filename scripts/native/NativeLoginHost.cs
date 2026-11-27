using System;
using System.IO;
using System.Linq;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows.Forms;

internal static class NativeLoginHost
{
    private static string appDirectory;
    private static bool sessionSaved;
    private static bool saveFailed;

    private static string Hash(string path)
    {
        using var stream = File.OpenRead(path);
        using var sha = SHA256.Create();
        return Convert.ToHexString(sha.ComputeHash(stream));
    }

    private static JsonObject Profile(string directory, string file)
    {
        var profiles = JsonNode.Parse(File.ReadAllText(file)) as JsonArray;
        return profiles?.OfType<JsonObject>().SingleOrDefault(p =>
            p["work_sha256"]?.GetValue<string>() == Hash(Path.Combine(directory, "ZYing.Work.dll")) &&
            p["core_sha256"]?.GetValue<string>() == Hash(Path.Combine(directory, "ZYing.Core.dll")) &&
            p["user_sha256"]?.GetValue<string>() == Hash(Path.Combine(directory, "ZYing.User.dll")))
            ?? throw new InvalidOperationException("unsupported_client_version");
    }

    private static Assembly ResolveAssembly(object sender, ResolveEventArgs args)
    {
        var file = Path.Combine(appDirectory, new AssemblyName(args.Name).Name + ".dll");
        return File.Exists(file) ? Assembly.LoadFrom(file) : null;
    }

    private static void SaveSession(Assembly work, JsonObject profile, Guid token, int user, string file)
    {
        string Symbol(string key) => profile[key].GetValue<string>();
        var rpc = work.GetType(Symbol("rpc_type"), true);
        var pool = rpc.GetField(Symbol("login_server_field")).GetValue(null);
        var endpoint = pool?.GetType().GetMethod(Symbol("endpoint_method"))?.Invoke(pool, null) as IPEndPoint;
        if (endpoint == null || endpoint.Port <= 0)
            throw new InvalidOperationException("login_endpoint_unavailable");
        var session = new JsonObject {
            ["token"] = token.ToString(), ["user_id"] = user,
            ["server_address"] = endpoint.Address.ToString(), ["server_port"] = endpoint.Port
        };
        string deviceField = profile["device_id_field"]?.GetValue<string>();
        if (!string.IsNullOrEmpty(deviceField))
            session["device_id"] = ((Guid)rpc.GetField(deviceField).GetValue(null)).ToString();
        string stateField = profile["exchange_state_field"]?.GetValue<string>();
        if (!string.IsNullOrEmpty(stateField))
            session["exchange_state"] = (int)rpc.GetField(stateField).GetValue(null);
        byte[] plaintext = Encoding.UTF8.GetBytes(session.ToJsonString());
        string temporary = null;
        try
        {
            var protectedBytes = ProtectedData.Protect(plaintext, null, DataProtectionScope.CurrentUser);
            var envelope = new { version = 1, protection = "windows-dpapi-current-user",
                purpose = "zhiying-login-session", data = Convert.ToBase64String(protectedBytes),
                client_hashes = new { work_sha256 = Symbol("work_sha256"), user_sha256 = Symbol("user_sha256") } };
            Directory.CreateDirectory(Path.GetDirectoryName(file));
            temporary = file + "." + Guid.NewGuid() + ".tmp";
            File.WriteAllText(temporary, JsonSerializer.Serialize(envelope));
            File.Move(temporary, file, true);
            temporary = null;
        }
        finally
        {
            CryptographicOperations.ZeroMemory(plaintext);
            session.Clear();
            if (temporary != null && File.Exists(temporary)) File.Delete(temporary);
        }
    }

    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            if (args.Length != 4 || !Directory.Exists(args[0]))
                throw new InvalidOperationException("invalid_login_host_arguments");
            appDirectory = args[0];
            var profile = Profile(appDirectory, args[1]);
            var target = Path.GetFullPath(args[2]);
            int timeout = int.Parse(args[3]);
            if (timeout < 10 || timeout > 1800)
                throw new InvalidOperationException("invalid_login_host_arguments");
            AppDomain.CurrentDomain.AssemblyResolve += ResolveAssembly;
            Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            var user = Assembly.LoadFrom(Path.Combine(appDirectory, "ZYing.User.dll"));
            var work = Assembly.LoadFrom(Path.Combine(appDirectory, "ZYing.Work.dll"));
            var global = user.GetType("ZYing.Global", true);
            global.GetField("Name").SetValue(null, "智赢");
            global.GetField("Version").SetValue(null, "");
            // ShowLogin invokes CheckEXE's updater. Create the native form directly.
            var form = (Form)user.GetType("ZYing.MLogin", true).GetProperty("Instance").GetValue(null);
            var context = new ApplicationContext(form);
            global.GetField("Context").SetValue(null, context);
            var member = work.GetType("ZYing.Member", true);
            using var timer = new System.Windows.Forms.Timer { Interval = 100 };
            var started = DateTime.UtcNow;
            timer.Tick += (sender, e) =>
            {
                var token = (Guid)member.GetField("Token").GetValue(null);
                int id = (int)member.GetField("UserID").GetValue(null);
                if (token != Guid.Empty && id > 0)
                {
                    try { SaveSession(work, profile, token, id, target); sessionSaved = true; }
                    catch { saveFailed = true; }
                    timer.Stop();
                    context.ExitThread();
                }
                else if ((DateTime.UtcNow - started).TotalSeconds > timeout)
                {
                    timer.Stop();
                    context.ExitThread();
                }
            };
            timer.Start();
            Application.Run(context);
            foreach (Form owned in Application.OpenForms.Cast<Form>().ToArray()) owned.Close();
            if (sessionSaved)
            {
                Console.WriteLine(JsonSerializer.Serialize(new { ok = true, authenticated = true,
                    session_saved = true, session_file = target, protection = "windows-dpapi-current-user",
                    login_mode = "native_window" }));
                return 0;
            }
            throw new InvalidOperationException(saveFailed ? "native_session_save_failed" : "native_login_cancelled_or_timed_out");
        }
        catch (Exception error)
        {
            while (error.InnerException != null) error = error.InnerException;
            string[] allowed = { "unsupported_client_version", "login_endpoint_unavailable", "invalid_login_host_arguments",
                                 "native_session_save_failed", "native_login_cancelled_or_timed_out" };
            Console.WriteLine(JsonSerializer.Serialize(new { ok = false,
                error = allowed.Contains(error.Message) ? error.Message : "native_login_host_failed" }));
            return 1;
        }
    }
}
