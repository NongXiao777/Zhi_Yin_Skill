// Evaluate in the installed collector extension's background service worker.
// Its verified API collects from the requested existing Chrome tab. This
// helper does not open a popup, export a file, or inject a copied collector.
async function zyingAliExpressExtensionRead(request) {
  const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
  const plain = value => value !== null && typeof value === "object" && !Array.isArray(value) &&
    [Object.prototype, null].includes(Object.getPrototypeOf(value));
  const stop = error => { throw Object.assign(new Error(error), {extensionReadError: error}); };
  let nodes = 0, stringLength = 0;
  const clone = (value, depth = 0, seen = new Set()) => {
    if (++nodes > 50000 || depth > 25 || seen.has(value)) stop("invalid_extension_json");
    if (typeof value === "string") {
      stringLength += value.length;
      if (stringLength > 1500000) stop("extension_json_too_large");
      return value;
    }
    if (value === null || typeof value === "boolean") return value;
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (!plain(value) && !Array.isArray(value)) stop("invalid_extension_json");
    const keys = Reflect.ownKeys(value);
    if (keys.length > 5001 || keys.some(key => typeof key !== "string")) stop("invalid_extension_json");
    for (const key of keys) {
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      if (!descriptor || !own(descriptor, "value")) stop("invalid_extension_json");
    }
    seen.add(value);
    let result;
    if (Array.isArray(value)) {
      if (value.length > 5000 || keys.length !== value.length + 1 ||
        keys.some(key => key !== "length" && !/^(0|[1-9]\d*)$/.test(key))) stop("invalid_extension_json");
      result = Array.from({length: value.length}, (_, index) => {
        const descriptor = Object.getOwnPropertyDescriptor(value, String(index));
        if (!descriptor) stop("invalid_extension_json");
        return clone(descriptor.value, depth + 1, seen);
      });
    } else {
      result = Object.fromEntries(keys.map(key => {
        const descriptor = Object.getOwnPropertyDescriptor(value, key);
        if (!descriptor.enumerable) stop("invalid_extension_json");
        return [key, clone(descriptor.value, depth + 1, seen)];
      }));
    }
    seen.delete(value);
    return result;
  };
  const copy = value => {
    nodes = 0; stringLength = 0;
    const result = clone(value);
    if (JSON.stringify(result).length > 2000000) stop("extension_json_too_large");
    return result;
  };
  try {
    if (!plain(request)) stop("invalid_extension_request");
    request = copy(request);
    if (Object.keys(request).some(key => !["source_product_id", "target_url", "tab_id"].includes(key)) ||
      typeof request.source_product_id !== "string" || !/^\d{10,24}$/.test(request.source_product_id)) {
      stop("invalid_source_product_id");
    }
    if (own(request, "tab_id") && (!Number.isInteger(request.tab_id) || request.tab_id < 1 || request.tab_id > 2147483647)) {
      stop("invalid_extension_tab_id");
    }
    const expectedUrl = "https://www.aliexpress.com/item/" + request.source_product_id + ".html";
    if (own(request, "target_url") && request.target_url !== expectedUrl) stop("source_item_mismatch");
    let worker;
    try { worker = new URL(location.href); } catch { stop("extension_service_worker_required"); }
    if (worker.protocol !== "chrome-extension:" || worker.pathname !== "/background.js" ||
      worker.username || worker.password || worker.port || worker.search || worker.hash) stop("extension_service_worker_required");
    if (typeof chrome !== "object" || typeof chrome.runtime?.getManifest !== "function") stop("extension_api_unavailable");
    const extensionId = chrome.runtime.id;
    if (typeof extensionId !== "string" || !/^[a-p]{32}$/.test(extensionId) || worker.hostname !== extensionId) {
      stop("extension_identity_mismatch");
    }
    const manifest = chrome.runtime.getManifest();
    if (manifest?.name !== "速卖通商品采集助手" || manifest.manifest_version !== 3) stop("extension_identity_mismatch");
    if (typeof manifest.version !== "string" || !/^0\.(?:[2-9]|[1-9]\d+)\.\d+$/.test(manifest.version)) stop("extension_version_unsupported");
    if (typeof globalThis.zyingAliExpressCollect !== "function") stop("extension_api_unavailable");
    let response;
    try { response = await globalThis.zyingAliExpressCollect(request); }
    catch { stop("extension_collection_failed"); }
    response = copy(response);
    if (!plain(response) || typeof response.ok !== "boolean") stop("invalid_extension_result");
    if (!response.ok) {
      if (typeof response.error !== "string" || !/^[a-z][a-z0-9_]{0,79}$/.test(response.error)) stop("invalid_extension_result");
      if (own(response, "diagnostics") && response.diagnostics !== null && !plain(response.diagnostics)) stop("invalid_extension_result");
      return {ok: false, error: response.error, ...(own(response, "diagnostics") ? {diagnostics: response.diagnostics} : {})};
    }
    if (response.collector_origin !== "extension_service_worker" || !plain(response.extension) ||
      response.extension.id !== extensionId || response.extension.name !== manifest.name ||
      response.extension.version !== manifest.version) stop("extension_identity_mismatch");
    const product = response.product;
    if (!plain(product) || product.source !== "aliexpress" || product.source_product_id !== request.source_product_id ||
      product.source_url !== expectedUrl) stop("source_item_mismatch");
    if (typeof product.title !== "string" || !product.title.trim() || product.title.length > 1000 ||
      !["images", "specifications", "variants"].every(key => Array.isArray(product[key]))) stop("invalid_extension_product");
    return {ok: true, product, collector_origin: "extension_service_worker",
      extension: {id: extensionId, name: manifest.name, version: manifest.version}};
  } catch (error) {
    return {ok: false, error: error?.extensionReadError || "extension_service_worker_read_failed"};
  }
}

if (typeof module === "object") module.exports = zyingAliExpressExtensionRead;
