const assert = require("node:assert/strict");
const test = require("node:test");
const edit = require("../scripts/zying_web_product_edit.js");

const routes = {sale: "#/product/myproduct/productlist", spider: "#/product/1688/collectionlist"};
const clone = value => JSON.parse(JSON.stringify(value));
const freeze = value => {
  if (value && typeof value === "object") { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
};
const original = () => ({
  sale_id: 1001, sale_cost: "2.99", sale_cur: "CNY", sale_stat: 3117, sale_log: "Before",
  sale_title: '{"en":"Old title","zh":"中文标题","es":"Título"}',
  sale_brief: '{"en":"Old brief","zh":"中文短标题","es":"Breve"}',
  sale_keys: '{"en":"old keywords","zh":"中文关键词","es":"Claves"}',
  sale_bullet: '{"en":"Old bullets","zh":"中文要点","es":"Puntos"}',
  sale_intro: '{"en":"Old description","zh":"中文描述","es":"Descripción"}',
  sale_stock: '[{"key":"A / 24V","money":1.44,"no":"SKU-A","spec":["A","24V"],"num":5,"weight":20,"pic":"a.jpg","areas":{"US":1}},{"key":"B / 12V","no":"SKU-B","num":6},{"key":"C / 12V","money":"3.00","num":7}]',
});
const five = () => ({english_title: "New title", english_brief: "New brief", english_keys: "new keywords",
  english_bullet: "First point\nSecond point", english_description: "<p>New description</p>"});
const fixture = (record = original(), source = "sale", behavior = {}) => {
  global.location = {origin: "https://erp.zying.net", hash: routes[source]};
  const calls = [];
  const state = {record: clone(record)};
  const transport = {async handleProduct(selectedSource, action, payload) {
    assert.equal(selectedSource, source);
    calls.push({source: selectedSource, action, payload: clone(payload)});
    if (action === "detail") {
      assert.deepEqual(payload, {id: 1001});
      if (behavior.read) return behavior.read(state, calls);
      return {root: [clone(state.record)]};
    }
    assert.equal(action, "update");
    if (behavior.update) return behavior.update(state, payload, calls);
    state.record = {...state.record, ...clone(payload), sale_log: "Saved"};
    return {result: 1001};
  }};
  return {state, calls, transport, source};
};
const preview = async (context, changes) => {
  const result = await edit({action: "preview", source: context.source, product_id: 1001, changes}, context.transport);
  assert.equal(result.ok, true, result.error);
  assert.equal(result.stage, "product_edit_preview");
  return result;
};
const apply = (context, changes, expected) => edit({action: "apply", source: context.source, product_id: 1001,
  changes, expected}, context.transport);

test("all five copy fields share one whitelisted save and preserve every other language", async () => {
  const context = fixture();
  const changes = freeze(five());
  const before = clone(context.state.record);
  const planned = await preview(context, changes);
  assert.deepEqual(planned.updateColumns, ["sale_id", "sale_title", "sale_brief", "sale_keys", "sale_bullet", "sale_intro"]);
  const request = freeze({action: "apply", source: "sale", product_id: "1001", changes, expected: planned.snapshot});
  const result = await edit(request, context.transport);
  assert.equal(result.ok, true, result.error);
  assert.equal(result.verified, true);
  assert.deepEqual(result.copy, changes);
  assert.deepEqual(result.serverChangedFields, ["sale_log"]);
  assert.deepEqual(context.calls.map(call => call.action), ["detail", "detail", "update", "detail"]);
  const payload = context.calls[2].payload;
  assert.equal(typeof payload.sale_id, "number");
  assert.equal(payload.sale_id, 1001);
  assert.deepEqual(Object.keys(payload), planned.updateColumns);
  for (const column of ["sale_title", "sale_brief", "sale_keys", "sale_bullet", "sale_intro"]) {
    const prior = JSON.parse(before[column]);
    const after = JSON.parse(context.state.record[column]);
    assert.equal(after.zh, prior.zh);
    assert.equal(after.es, prior.es);
  }
  assert.equal(context.state.record.sale_stock, before.sale_stock);
  assert.equal(context.state.record.sale_cost, before.sale_cost);
  const checked = await edit({action: "verify", source: "sale", product_id: 1001, changes,
    expected: planned.snapshot}, context.transport);
  assert.equal(checked.ok, true);
  assert.equal(checked.stage, "product_edit_verified");
});

test("two absolute surcharges keep all stock rows and their unrelated fields", async () => {
  const context = fixture(undefined, "spider");
  const before = JSON.parse(context.state.record.sale_stock);
  const changes = freeze({surcharges: [{key: "A / 24V", value: "2.0100"}, {key: "B / 12V", value: 0}]});
  const planned = await preview(context, changes);
  assert.deepEqual(planned.comparison.map(item => [item.observed, item.wanted]), [["1.44", "2.01"], ["0", "0"]]);
  const result = await apply(context, changes, planned.snapshot);
  assert.equal(result.ok, true);
  const payload = context.calls.find(call => call.action === "update").payload;
  assert.deepEqual(Object.keys(payload), ["sale_id", "sale_stock"]);
  const rows = JSON.parse(payload.sale_stock);
  assert.deepEqual(rows, [{...before[0], money: 2.01}, {...before[1], money: 0}, before[2]]);
  assert.equal(rows.length, 3);
  assert.equal(result.checks.allVariantsPreserved, true);
});

test("500 exact keys are supported and the 501st stock entry remains intact", async () => {
  const rows = Array.from({length: 501}, (_, i) => ({key: `Variant ${i}`, money: i / 100, no: `SKU-${i}`, num: i}));
  const context = fixture({...original(), sale_stock: JSON.stringify(rows)});
  const changes = {surcharges: rows.slice(0, 500).map((row, i) => ({key: row.key, value: `${i}.000001`}))};
  const planned = await preview(context, changes);
  assert.equal(planned.comparison.length, 500);
  const result = await apply(context, changes, planned.snapshot);
  assert.equal(result.ok, true, result.error);
  const after = JSON.parse(context.state.record.sale_stock);
  assert.equal(after.length, 501);
  assert.deepEqual(after[500], rows[500]);
  for (let i = 0; i < 500; i++) {
    assert.equal(after[i].money, Number(`${i}.000001`));
    assert.equal(after[i].num, rows[i].num);
  }
});

test("decimal strings avoid Number rounding and preserve untouched numeric tokens", async () => {
  const stock = '[{"key":"A / 24V","money":1e-3,"num":9223372036854775807,"extra":0.1234567890123456789},{"key":"C / 12V","money":3.00}]';
  const context = fixture({...original(), sale_stock: stock});
  const changes = {surcharges: [{key: "A / 24V", value: "9999999999.123456"}]};
  const planned = await preview(context, changes);
  assert.equal(planned.comparison[0].observed, "0.001");
  const result = await apply(context, changes, planned.snapshot);
  assert.equal(result.ok, true, result.error);
  assert.equal(context.state.record.sale_stock,
    '[{"key":"A / 24V","money":9999999999.123456,"num":9223372036854775807,"extra":0.1234567890123456789},{"key":"C / 12V","money":3.00}]');
  assert.equal(result.comparison[0].observed, "9999999999.123456");
});

test("optional copy can be cleared or added without replacing existing languages", async () => {
  const context = fixture({...original(), sale_brief: "", sale_keys: '{"es":"Claves"}'});
  const changes = {english_brief: "", english_keys: "New keywords"};
  const planned = await preview(context, changes);
  assert.equal((await apply(context, changes, planned.snapshot)).ok, true);
  assert.deepEqual(JSON.parse(context.state.record.sale_brief), {en: ""});
  assert.deepEqual(JSON.parse(context.state.record.sale_keys), {es: "Claves", en: "New keywords"});
});

test("read returns five copy fields and a default limit of ten variants", async () => {
  const rows = Array.from({length: 20}, (_, i) => ({key: `K${i}`, money: i}));
  const context = fixture({...original(), sale_stock: JSON.stringify(rows)});
  const result = await edit({action: "read", source: "sale", product_id: 1001}, context.transport);
  assert.equal(result.ok, true);
  assert.equal(Object.keys(result.copy).length, 5);
  assert.equal(result.variants.length, 10);
  assert.equal(result.total_variants, 20);
  assert.equal(context.calls.length, 1);
});

test("source, origin, and route gates stop without any product call", async () => {
  for (const [request, location, error] of [
    [{action: "read", source: "other", product_id: 1001}, {origin: "https://erp.zying.net", hash: routes.sale}, "invalid_source"],
    [{action: "read", source: "sale", product_id: 1001}, {origin: "https://seller.zying.net", hash: routes.sale}, "open_zying_web_my_products"],
    [{action: "read", source: "sale", product_id: 1001}, {origin: "https://erp.zying.net", hash: routes.spider}, "open_zying_web_my_products"],
    [{action: "read", source: "spider", product_id: 1001}, {origin: "https://erp.zying.net", hash: routes.sale}, "open_zying_web_collection"],
  ]) {
    global.location = location;
    const result = await edit(request, {handleProduct() { assert.fail("Unexpected product call"); }});
    assert.equal(result.error, error);
    assert.equal(result.saveAttempted, false);
  }
});

test("missing or changed IDs cannot produce a write", async () => {
  const context = fixture({...original(), sale_id: 1002});
  const result = await edit({action: "preview", source: "sale", product_id: 1001, changes: five()}, context.transport);
  assert.equal(result.error, "unexpected_product");
  assert.equal(context.calls.some(call => call.action === "update"), false);
  const valid = fixture();
  const planned = await preview(valid, five());
  const mismatched = clone(planned.snapshot);
  mismatched.product_id = 1002;
  assert.equal((await apply(valid, five(), mismatched)).error, "invalid_expected_snapshot");
  assert.equal(valid.calls.length, 1);
  assert.equal((await edit({action: "read", source: "sale", product_id: 2147483648}, valid.transport)).error, "invalid_product_id");
});

test("apply binds the exact source, full baseline, and requested changes", async () => {
  const context = fixture();
  const changes = five();
  const planned = await preview(context, changes);
  assert.equal((await apply(context, changes, undefined)).error, "invalid_expected_snapshot");
  assert.equal((await apply(context, {...changes, english_title: "Different title"}, planned.snapshot)).error, "expected_snapshot_mismatch");
  const wrongSource = {...planned.snapshot, source: "spider"};
  assert.equal((await apply(context, changes, wrongSource)).error, "invalid_expected_snapshot");
  context.state.record.sale_cost = "3.99";
  const result = await apply(context, changes, planned.snapshot);
  assert.equal(result.error, "expected_snapshot_conflict");
  assert.equal(context.calls.some(call => call.action === "update"), false);
});

test("duplicate, source SKU, negative, excessive, and imprecise surcharge input is rejected", async () => {
  const context = fixture();
  const cases = [
    [{surcharges: [{key: "A / 24V", value: 1}, {key: "A / 24V", value: 2}]}, "invalid_variant_key"],
    [{surcharges: [{key: "SKU-A", value: 1}]}, "variant_not_unique_or_unreadable"],
    [{surcharges: [{key: "A / 24V", value: -1}]}, "invalid_surcharge"],
    [{surcharges: [{key: "A / 24V", value: "0.1234567"}]}, "invalid_surcharge"],
    [{surcharges: [{key: "A / 24V", value: 0.1 + 0.2}]}, "invalid_surcharge"],
    [{surcharges: [{key: "A / 24V", value: "1e-3"}]}, "invalid_surcharge"],
    [{surcharges: [{key: "A / 24V", value: true}]}, "invalid_surcharge"],
    [{surcharges: Array.from({length: 501}, (_, i) => ({key: `K${i}`, value: 1}))}, "invalid_surcharges"],
    [{sale_cost: 5}, "invalid_changes"],
    [{english_title: ""}, "invalid_english_copy"],
  ];
  for (const [changes, error] of cases) {
    const result = await edit({action: "preview", source: "sale", product_id: 1001, changes}, context.transport);
    assert.equal(result.error, error);
  }
  assert.equal(context.calls.some(call => call.action === "update"), false);
  const duplicate = fixture({...original(), sale_stock: '[{"key":"A / 24V","money":1},{"key":"A / 24V","money":2}]'});
  const result = await edit({action: "preview", source: "sale", product_id: 1001,
    changes: {surcharges: [{key: "A / 24V", value: 3}]}}, duplicate.transport);
  assert.equal(result.error, "variant_not_unique_or_unreadable");
});

test("unreadable language data and duplicate JSON keys are never silently replaced", async () => {
  for (const record of [
    {...original(), sale_title: "Unknown language text"},
    {...original(), sale_title: '{"en":"One","en":"Two","zh":"中文"}'},
  ]) {
    const context = fixture(record);
    const result = await edit({action: "preview", source: "sale", product_id: 1001,
      changes: {english_title: "New title"}}, context.transport);
    assert.equal(result.error, "language_map_unreadable");
    assert.equal(context.calls.some(call => call.action === "update"), false);
  }
});

test("copy-only preview rejects stock that cannot be verified before any save", async () => {
  const context = fixture({...original(), sale_stock: "not-json"});
  const result = await edit({action: "preview", source: "sale", product_id: 1001,
    changes: {english_title: "New title"}}, context.transport);
  assert.equal(result.ok, false);
  assert.equal(result.error, "product_data_unreadable");
  assert.equal(context.calls.some(call => call.action === "update"), false);
});

test("target money readback permits omitted zero and decimal text while preserving the row", async () => {
  for (const [value, serverMoney] of [[0, undefined], [0, null], ["2.01", "2.0100"]]) {
    const context = fixture(undefined, "sale", {update(state, fields) {
      state.record = {...state.record, ...clone(fields)};
      const rows = JSON.parse(state.record.sale_stock);
      if (serverMoney === undefined) delete rows[0].money; else rows[0].money = serverMoney;
      state.record.sale_stock = JSON.stringify(rows);
      return {result: 1001};
    }});
    const changes = {surcharges: [{key: "A / 24V", value}]};
    const planned = await preview(context, changes);
    const result = await apply(context, changes, planned.snapshot);
    assert.equal(result.ok, true, result.error);
    assert.equal(result.checks.requestedValues, true);
    assert.equal(result.checks.allVariantsPreserved, true);
  }
});

test("an already matching preview skips the mutation", async () => {
  const context = fixture();
  const changes = {english_title: "Old title", surcharges: [{key: "A / 24V", value: "1.440"}]};
  const planned = await preview(context, changes);
  assert.equal(planned.alreadyMatches, true);
  const result = await apply(context, changes, planned.snapshot);
  assert.equal(result.ok, true);
  assert.equal(result.stage, "product_edit_already_matches");
  assert.equal(result.saveAttempted, false);
  assert.equal(context.calls.some(call => call.action === "update"), false);
});

test("a save throwing after reaching the server is still confirmed by one readback", async () => {
  const context = fixture(undefined, "sale", {update(state, fields) {
    state.record = {...state.record, ...clone(fields)};
    throw new Error("Connection lost after save");
  }});
  const changes = {english_title: "New title"};
  const planned = await preview(context, changes);
  const result = await apply(context, changes, planned.snapshot);
  assert.equal(result.ok, true);
  assert.equal(result.verified, true);
  assert.equal(result.saveResponse, "unavailable");
  assert.deepEqual(context.calls.slice(1).map(call => call.action), ["detail", "update", "detail"]);
});

test("save failure or a false acknowledgement is not success when readback mismatches", async () => {
  for (const update of [() => { throw new Error("Save failed"); }, () => ({ok: false})]) {
    const context = fixture(undefined, "sale", {update});
    const changes = {english_title: "New title"};
    const planned = await preview(context, changes);
    const result = await apply(context, changes, planned.snapshot);
    assert.equal(result.ok, false);
    assert.equal(result.verified, false);
    assert.equal(result.saveAttempted, true);
    assert.equal(result.error, "web_readback_mismatch");
    assert.equal(context.calls.filter(call => call.action === "update").length, 1);
    assert.equal(context.calls.filter(call => call.action === "detail").length, 3);
  }
});

test("readback failure reports the uncertain outcome and never retries the save", async () => {
  const context = fixture(undefined, "sale", {read(state, calls) {
    if (calls.some(call => call.action === "update")) throw new Error("Readback failed");
    return {root: [clone(state.record)]};
  }});
  const changes = {english_title: "New title"};
  const planned = await preview(context, changes);
  const result = await apply(context, changes, planned.snapshot);
  assert.equal(result.error, "web_save_outcome_uncertain");
  assert.equal(result.readbackError, "web_detail_unavailable");
  assert.equal(result.saveAttempted, true);
  assert.equal(result.verified, false);
  assert.equal(context.calls.filter(call => call.action === "update").length, 1);
  assert.equal(context.calls.filter(call => call.action === "detail").length, 3);
});

test("readback detects lost languages, omitted variants, and unexpected product changes", async () => {
  const alterations = [
    state => { state.record.sale_title = '{"en":"New title"}'; },
    state => { state.record.sale_stock = JSON.stringify(JSON.parse(state.record.sale_stock).slice(0, 2)); },
    state => { state.record.sale_cost = "99"; },
    state => { state.record.sale_id = 1002; },
  ];
  for (const alter of alterations) {
    const context = fixture(undefined, "sale", {update(state, fields) {
      state.record = {...state.record, ...clone(fields)};
      alter(state);
      return {result: 1001};
    }});
    const changes = {english_title: "New title", surcharges: [{key: "A / 24V", value: 2}]};
    const planned = await preview(context, changes);
    const result = await apply(context, changes, planned.snapshot);
    assert.equal(result.ok, false);
    assert.equal(result.verified, false);
    assert.equal(result.saveAttempted, true);
    assert.equal(context.calls.filter(call => call.action === "update").length, 1);
  }
});

test("a navigation during the pre-save read stops before writing", async () => {
  const context = fixture(undefined, "sale", {read(state, calls) {
    if (calls.length === 2) global.location.hash = routes.spider;
    return {root: [clone(state.record)]};
  }});
  const changes = {english_title: "New title"};
  const planned = await preview(context, changes);
  const result = await apply(context, changes, planned.snapshot);
  assert.equal(result.error, "open_zying_web_my_products");
  assert.equal(context.calls.some(call => call.action === "update"), false);
});

test("module lookup uses only one already-loaded same-origin ProductApi asset", async () => {
  global.location = {origin: "https://erp.zying.net", hash: routes.sale};
  global.performance = {getEntriesByType(type) {
    assert.equal(type, "resource");
    return [{name: "https://other.example/assets/ProductApi-X.js"},
      {name: "https://erp.zying.net/assets/ProductApi-A.js"},
      {name: "https://erp.zying.net/assets/ProductApi-B.js"}];
  }};
  const result = await edit({action: "read", source: "sale", product_id: 1001});
  assert.equal(result.error, "web_product_module_unavailable");
});
