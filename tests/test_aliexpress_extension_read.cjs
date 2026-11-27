const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const helper = fs.readFileSync(path.join(__dirname, "../scripts/aliexpress_extension_read.js"), "utf8");
const extensionId = "a".repeat(32);
const id = "1005013209445272";
const productUrl = "https://www.aliexpress.com/item/" + id + ".html";
const product = () => ({source: "aliexpress", source_product_id: id, source_url: productUrl,
  captured_at: "2026-11-27T12:00:00Z", title: "Black O-ring kit", store: null,
  images: ["https://ae-pic-a1.aliexpress-media.com/kf/fixture.jpg"],
  specifications: [{name: "Material", value: "Rubber"}],
  variants: [{source_sku_id: "120000000000000001", options: [{name: "Color", value: "Black", image: null}],
    visible_price: "$1.00", currency: "USD", stock_shown: 100}],
  visible_price: "$1.00", currency: null, description: null});
const manifest = () => ({name: "速卖通商品采集助手", manifest_version: 3, version: "0.2.0", background: {service_worker: "background.js"}});
const normal = value => JSON.parse(JSON.stringify(value));

function worker(options = {}) {
  const calls = [];
  const info = options.manifest || manifest();
  const result = options.result || {ok: true, product: product(), collector_origin: "extension_service_worker",
    extension: {id: extensionId, name: info.name, version: info.version}};
  const context = vm.createContext({URL,
    location: {href: options.url || "chrome-extension://" + extensionId + "/background.js"},
    chrome: {runtime: {id: options.extensionId || extensionId, getManifest: () => info}},
    inspectPage() { assert.fail("Service worker helper opened or refreshed a popup"); },
  });
  vm.runInContext("let apiResult = JSON.parse(" + JSON.stringify(JSON.stringify(result)) + "); let getterCalls = 0;", context);
  if (!options.missingApi) context.zyingAliExpressCollect = async request => {
    calls.push(normal(request));
    if (options.apiHook) await options.apiHook(context);
    if (options.apiFailure) throw new Error("Private details should not be exposed");
    return vm.runInContext("apiResult", context);
  };
  vm.runInContext(helper, context);
  return {
    context, mutate: code => vm.runInContext(code, context), calls,
    read: async (request = {source_product_id: id}) => normal(await vm.runInContext(
      "zyingAliExpressExtensionRead(JSON.parse(" + JSON.stringify(JSON.stringify(request)) + "))", context)),
  };
}

test("calls the installed background API and preserves its complete arrays and missing fields", async () => {
  const fixture = worker();
  const request = {source_product_id: id, target_url: productUrl};
  const result = await fixture.read(request);
  assert.deepEqual(result, {ok: true, product: product(), collector_origin: "extension_service_worker",
    extension: {id: extensionId, name: "速卖通商品采集助手", version: "0.2.0"}});
  assert.deepEqual(fixture.calls, [request]);
  assert.equal(result.product.currency, null);
  assert.equal(result.product.description, null);
  assert.deepEqual(normal(fixture.mutate("apiResult.product")), product());
});

test("wrong context, mismatched identity, old manifest and missing background API stop before collection", async () => {
  const cases = [
    [{url: productUrl}, "extension_service_worker_required"],
    [{url: "chrome-extension://" + extensionId + "/popup.html"}, "extension_service_worker_required"],
    [{url: "chrome-extension://" + extensionId + "/background.js?tab=7"}, "extension_service_worker_required"],
    [{extensionId: "b".repeat(32)}, "extension_identity_mismatch"],
    [{manifest: {...manifest(), name: "Other collector"}}, "extension_identity_mismatch"],
    [{manifest: {...manifest(), manifest_version: 2}}, "extension_identity_mismatch"],
    [{manifest: {...manifest(), version: "0.1.2"}}, "extension_version_unsupported"],
    [{manifest: {...manifest(), version: "0.2.0-beta"}}, "extension_version_unsupported"],
    [{missingApi: true}, "extension_api_unavailable"],
  ];
  for (const [options, error] of cases) {
    const fixture = worker(options);
    assert.deepEqual(await fixture.read(), {ok: false, error});
    assert.equal(fixture.calls.length, 0);
  }
  for (const version of ["0.2.1", "0.3.0", "0.10.0"]) {
    assert.equal((await worker({manifest: {...manifest(), version}}).read()).ok, true);
  }
});

test("optional Chrome tab IDs are passed exactly and invalid requests never invoke the API", async () => {
  for (const tab_id of [1, 7, 2147483647]) {
    const fixture = worker();
    assert.equal((await fixture.read({source_product_id: id, tab_id})).ok, true);
    assert.deepEqual(fixture.calls, [{source_product_id: id, tab_id}]);
  }
  const cases = [[{}, "invalid_source_product_id"],
    [{source_product_id: 1005013209445272}, "invalid_source_product_id"],
    [{source_product_id: "123"}, "invalid_source_product_id"],
    [{source_product_id: id, refresh: true}, "invalid_source_product_id"],
    [{source_product_id: id, target_url: productUrl + "?tracking=1"}, "source_item_mismatch"],
    ...[-1, 0, true, "7", 1.5, 2147483648].map(tab_id => [{source_product_id: id, tab_id}, "invalid_extension_tab_id"])];
  for (const [request, error] of cases) {
    const fixture = worker();
    assert.deepEqual(await fixture.read(request), {ok: false, error});
    assert.equal(fixture.calls.length, 0);
  }
});

test("failed collection and verification diagnostics remain failures with no automatic retry", async () => {
  for (const error of ["verification_required", "login_required", "product_not_loaded", "source_tab_not_found",
    "ambiguous_source_tabs", "source_item_mismatch", "source_tab_unavailable", "source_tab_mismatch",
    "browser_injection_failed", "page_navigation_during_collection"]) {
    const result = {ok: false, error, diagnostics: {state: "verification_failed", error_code: "punished", retry_count: 2}};
    const fixture = worker({result});
    assert.deepEqual(await fixture.read(), result);
    assert.equal(fixture.calls.length, 1);
  }
  const throwing = worker({apiFailure: true});
  assert.deepEqual(await throwing.read(), {ok: false, error: "extension_collection_failed"});
  assert.equal(throwing.calls.length, 1);
});

test("success requires matching source and installed-extension identity", async () => {
  for (const changed of [{source_product_id: "1005013209445273"}, {source_url: productUrl.replace("5272", "5273")}, {source: "amazon"}]) {
    const fixture = worker(); fixture.mutate("Object.assign(apiResult.product, " + JSON.stringify(changed) + ")");
    assert.deepEqual(await fixture.read(), {ok: false, error: "source_item_mismatch"});
  }
  for (const mutation of ["apiResult.collector_origin = 'same_core_direct'", "apiResult.extension.id = 'b'.repeat(32)",
    "apiResult.extension.name = 'Other collector'", "apiResult.extension.version = '0.1.2'", "delete apiResult.extension"]) {
    const fixture = worker(); fixture.mutate(mutation);
    assert.deepEqual(await fixture.read(), {ok: false, error: "extension_identity_mismatch"});
  }
});

test("malformed API results are never converted into successful product reads", async () => {
  for (const result of [{product: product()}, {ok: "true", product: product()},
    {ok: false}, {ok: false, error: "failed with private details"},
    {ok: false, error: "verification_required", diagnostics: []}]) {
    assert.deepEqual(await worker({result}).read(), {ok: false, error: "invalid_extension_result"});
  }
  const unavailable = worker(); unavailable.mutate("apiResult = undefined");
  assert.deepEqual(await unavailable.read(), {ok: false, error: "invalid_extension_json"});
});

test("invalid or unbounded returned JSON rejects cycles, getters and nonfinite data without evaluating getters", async () => {
  for (const mutation of ["apiResult.product.extra = NaN", "apiResult.product.extra = Infinity", "apiResult.product.extra = undefined",
    "apiResult.product.extra = () => 1", "apiResult.product.extra = apiResult", "apiResult.product.images.length = 2",
    "apiResult.product.images.extra = true", "apiResult.product.extra = Symbol('x')",
    "Object.defineProperty(apiResult.product, 'extra', {enumerable:true, get(){getterCalls++; return 1;}})",
    "Object.defineProperty(apiResult.product, 'extra', {enumerable:false, get(){getterCalls++; return 1;}})",
    "apiResult.product.extra = Array(5001).fill(0)",
    "apiResult.product.extra = {}; let branch=apiResult.product.extra; for(let i=0;i<30;i++){branch.next={};branch=branch.next;}"]) {
    const fixture = worker(); fixture.mutate(mutation);
    assert.deepEqual(await fixture.read(), {ok: false, error: "invalid_extension_json"});
    assert.equal(fixture.calls.length, 1);
    assert.equal(fixture.mutate("getterCalls"), 0);
  }
  const oversized = worker(); oversized.mutate("apiResult.product.description = 'x'.repeat(1500001)");
  assert.deepEqual(await oversized.read(), {ok: false, error: "extension_json_too_large"});
});

test("array and title requirements are explicit while empty variants, currency and description remain unchanged", async () => {
  for (const changed of [{title: " "}, {images: null}, {specifications: {}}, {variants: null}]) {
    const fixture = worker(); fixture.mutate("Object.assign(apiResult.product, " + JSON.stringify(changed) + ")");
    assert.deepEqual(await fixture.read(), {ok: false, error: "invalid_extension_product"});
  }
  const fixture = worker(); fixture.mutate("apiResult.product.variants = []; apiResult.product.specifications = []");
  const result = await fixture.read();
  assert.deepEqual(result.product.variants, []);
  assert.deepEqual(result.product.specifications, []);
  assert.equal(result.product.currency, null);
  assert.equal(result.product.description, null);
});
