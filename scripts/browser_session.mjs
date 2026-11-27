import { spawn } from "node:child_process";
import { isAbsolute } from "node:path";
import { createInterface } from "node:readline";

export function getChromeSession({ nodePath, mcpEntry, reconnect = false } = {}) {
  const previous = globalThis.zyBrowserConnection;
  if (previous && !previous.client.killed && previous.client.exitCode === null &&
      previous.client.signalCode === null) {
    return previous;
  }
  if (previous && !reconnect) {
    throw new Error("The Chrome connector has exited. Confirm that reconnection is needed before replacing it.");
  }
  if (typeof nodePath !== "string" || !isAbsolute(nodePath) ||
      typeof mcpEntry !== "string" || !isAbsolute(mcpEntry)) {
    throw new Error("Supply absolute paths to Node.js and the installed Chrome DevTools MCP entry point.");
  }

  const client = spawn(nodePath, [
    mcpEntry, "--autoConnect", "--no-usage-statistics", "--no-performance-crux",
    "--redact-network-headers", "--categoryExtensions", "--experimentalIncludeAllPages",
  ], { windowsHide: true, stdio: ["pipe", "pipe", "ignore"] });
  const pending = new Map();
  let nextId = 0;
  let transportError;

  function fail(error) {
    transportError ??= error;
    for (const { reject } of pending.values()) reject(transportError);
    pending.clear();
  }

  client.on("error", fail);
  client.stdin.on("error", fail);
  client.on("close", () => fail(new Error("The Chrome DevTools MCP connection closed.")));
  createInterface({ input: client.stdout }).on("line", (line) => {
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      fail(new Error("The Chrome DevTools MCP server returned invalid JSON."));
      return;
    }
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    if (message.error) request.reject(new Error(message.error.message));
    else request.resolve(message.result);
  });

  function send(message) {
    client.stdin.write(JSON.stringify({ jsonrpc: "2.0", ...message }) + "\n");
  }

  function request(method, params) {
    return new Promise((resolve, reject) => {
      if (transportError) {
        reject(transportError);
        return;
      }
      const id = ++nextId;
      pending.set(id, { resolve, reject });
      send({ id, method, params });
    });
  }

  async function invoke(name, args = {}) {
    const response = await request("tools/call", { name, arguments: args });
    if (response.isError) {
      const reason = (response.content ?? []).filter((item) => item.type === "text")
        .map((item) => item.text).join("\n");
      throw new Error(reason || "Chrome DevTools MCP tool failed.");
    }
    return response;
  }

  let ready;

  const session = {
    client,
    async call(name, args = {}) {
      ready ??= request("initialize", {
        protocolVersion: "2025-06-18",
        capabilities: {},
        clientInfo: { name: "zhiying-cli", version: "1.0" },
      }).then(() => send({ method: "notifications/initialized" }));
      await ready;
      return invoke(name, args);
    },
  };
  globalThis.zyBrowserConnection = session;
  return session;
}
