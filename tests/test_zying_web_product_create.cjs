const assert = require("node:assert/strict");
const test = require("node:test");
const create = require("../scripts/zying_web_product_create.js");

const route = "#/product/1688/collectionlist";
const clone = value => JSON.parse(JSON.stringify(value));
const freeze = value => {
  if (value && typeof value === "object") { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
};
const source = () => ({source: "aliexpress", source_product_id: "1005013209445272",
  source_url: "https://www.aliexpress.com/item/1005013209445272.html", captured_at: "2026-11-27T08:00:00Z",
  title: "Nitrile Rubber O-Ring Gasket Kit", images: ["https://ae-pic-a1.aliexpress-media.com/kf/one.jpg",
    "https://ae-pic-a1.aliexpress-media.com/kf/two.jpg"], description: "<p>Test O-ring kit description</p>",
  variants: [{source_sku_id: "120000000000001", stock_shown: 999, visible_price: "$3.99",
    options: [{name: "Color", value: "Black", image: null}]}], visible_price: "$3.99", currency: "USD"});
const metadata = () => ({category_id: 151, english_short: "O-Ring Test Kit", weight_g: 100, cost: "1.2300",
  currency: "CNY", note: "Explicit test placeholders", native_pair: {Color: ["Black", "Blue"]},
  native_stock: [{key: "Black", no: "CALLER-BLACK", spec: ["Black"], num: 0, money: "0.120000", weight: 0,
    pic: "https://ae-pic-a1.aliexpress-media.com/kf/one.jpg", areas: {US: 0}},
  {key: "Blue", no: "", num: 0, money: "0.3400", weight: 0, img: ""}]});
const unrelated = () => ({sale_id: 1001, sale_title: '{"en":"Existing unrelated product"}',
  sale_source: "https://www.aliexpress.com/item/1005000000000000.html", sale_memo: "Existing memo",
  sale_stock: "[]", sale_pic: [], sale_cost: "10", sale_cur: "USD", sale_stat: 3117});
const fixture = (behavior = {}, records = [unrelated()]) => {
  global.location = {origin: "https://erp.zying.net", hash: route};
  global.__zyingWebProductCreateAttempts = new Map();
  const calls = [];
  const state = {records: clone(records), nextId: 969086081, hidden: false, readUnavailable: false};
  const insert = payload => {
    const record = {...clone(payload), sale_id: state.nextId++, sale_pic: payload.sale_pic.split(","),
      sale_cost: String(payload.sale_cost), sale_log: "Created"};
    state.records.unshift(record);
    return record;
  };
  const transport = {async handleProduct(selectedSource, action, payload) {
    assert.equal(selectedSource, "spider");
    calls.push({source: selectedSource, action, payload: clone(payload)});
    if (action === "stat") {
      assert.ok(Number.isInteger(payload.page) && payload.page > 0);
      assert.ok(Number.isInteger(payload.pagesize) && payload.pagesize > 0 && payload.pagesize <= 1000);
      if (behavior.stat) return behavior.stat(state, payload, calls);
      if (state.readUnavailable) throw new Error("List unavailable");
      const records = state.hidden ? state.records.filter(record => record.sale_id === 1001) : state.records;
      const start = (payload.page - 1) * payload.pagesize;
      return {list: {data: records.slice(start, start + payload.pagesize).map(record => ({id: record.sale_id,
        title: JSON.parse(record.sale_title || "{}").en || ""})), maxcount: records.length}};
    }
    if (action === "detail") {
      assert.deepEqual(Object.keys(payload), ["id"]);
      if (behavior.detail) return behavior.detail(state, payload, calls);
      if (state.readUnavailable) throw new Error("Detail unavailable");
      return {root: clone(state.records.filter(record => record.sale_id === Number(payload.id)))};
    }
    assert.equal(action, "update");
    assert.equal(Object.hasOwn(payload, "sale_id"), false, "Creation must never update an existing ID");
    if (behavior.update) return behavior.update(state, payload, calls, insert);
    insert(payload);
    return null;
  }};
  return {state, calls, transport, insert};
};
const preview = async (context, product = source(), data = metadata(), extra = {}) => {
  const result = await create({action: "preview", source: product, metadata: data, ...extra}, context.transport);
  assert.equal(result.ok, true, result.error);
  assert.equal(result.stage, "product_create_preview");
  assert.ok(result.snapshot && result.snapshot.marker);
  return result;
};
const apply = (context, planned, product = source(), data = metadata()) => create({action: "apply", source: product,
  metadata: data, expected: planned.snapshot}, context.transport);
const verify = (context, planned, product = source(), data = metadata()) => create({action: "verify", source: product,
  metadata: data, expected: planned.snapshot}, context.transport);
const writes = context => context.calls.filter(call => call.action === "update");

test("null-return creation discovers and verifies the new server ID", async () => {
  const context = fixture();
  const before = clone(context.state.records[0]);
  const planned = await preview(context);
  assert.equal(writes(context).length, 0);
  const result = await apply(context, planned);
  assert.equal(result.ok, true, result.error);
  assert.equal(result.created, true);
  assert.equal(result.verified, true);
  assert.equal(result.product_id, 969086081);
  assert.equal(result.saveAttempted, true);
  assert.equal(writes(context).length, 1);
  assert.deepEqual(context.state.records.find(record => record.sale_id === 1001), before);
  assert.ok(context.calls.some(call => call.action === "detail" && call.payload.id === 969086081));
});

test("repeated apply and read-only verify cannot create another record", async () => {
  const context = fixture();
  const planned = await preview(context);
  const first = await apply(context, planned);
  const second = await apply(context, planned);
  const checked = await verify(context, planned);
  for (const result of [first, second, checked]) {
    assert.equal(result.ok, true, result.error);
    assert.equal(result.verified, true);
    assert.equal(result.product_id, 969086081);
  }
  assert.equal(second.saveAttempted, false);
  assert.equal(checked.saveAttempted, false);
  assert.equal(writes(context).length, 1);
  assert.equal(context.state.records.length, 2);
});

test("the preview binds explicit metadata and maps complete native stock without source inventory", async () => {
  const context = fixture();
  const product = freeze(source());
  const data = freeze(metadata());
  const planned = await preview(context, product, data);
  const payload = planned.payload;
  assert.equal(Object.hasOwn(payload, "sale_id"), false);
  assert.equal(payload.sale_localid, 151);
  assert.equal(payload.sale_en, data.english_short);
  assert.equal(payload.sale_weight, 100);
  assert.equal(String(payload.sale_cost), "1.23");
  assert.equal(payload.sale_cur, "CNY");
  assert.equal(payload.sale_stat, 3411);
  assert.equal(String(payload.sale_flag), "400");
  assert.equal(String(payload.sale_level), "10");
  assert.equal(String(payload.sale_grade), "1");
  assert.equal(payload.sale_source, product.source_url);
  assert.equal(payload.sale_pic, product.images.join(","));
  assert.deepEqual(JSON.parse(payload.sale_title), {en: product.title});
  assert.deepEqual(JSON.parse(payload.sale_intro), {en: product.description});
  assert.deepEqual(JSON.parse(payload.sale_pair), data.native_pair);
  const rows = JSON.parse(payload.sale_stock);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].no, "CALLER-BLACK");
  assert.deepEqual(rows[0].spec, ["Black"]);
  assert.deepEqual(rows[0].areas, {US: 0});
  assert.equal(rows[0].pic, data.native_stock[0].pic);
  assert.equal(rows[1].img, "");
  assert.equal(rows[0].num, 0);
  assert.equal(rows[1].num, 0);
  assert.equal(payload.sale_num, 0);
  assert.ok(payload.sale_memo.includes(planned.snapshot.marker));
  assert.ok(payload.sale_memo.includes(data.note));
  const result = await apply(context, planned, product, data);
  assert.equal(result.ok, true, result.error);
  assert.deepEqual(writes(context)[0].payload, payload);
});

test("absent native variants stay empty and visible source price never becomes cost", async () => {
  const context = fixture();
  const data = {category_id: 151, english_short: "Test Kit", weight_g: 100, cost: 0, currency: "CNY"};
  const planned = await preview(context, source(), data);
  assert.deepEqual(JSON.parse(planned.payload.sale_stock), []);
  assert.deepEqual(JSON.parse(planned.payload.sale_pair), {});
  assert.equal(planned.payload.sale_num, 0);
  assert.equal(String(planned.payload.sale_cost), "0");
  assert.equal((await apply(context, planned, source(), data)).ok, true);
  assert.ok(!planned.payload.sale_stock.includes("120000000000001"));
  const missingCost = {...data}; delete missingCost.cost;
  assert.equal((await create({action: "preview", source: source(), metadata: missingCost}, context.transport)).ok, false);
  assert.equal(writes(context).length, 1);
});

test("an absent description does not invent English listing text", async () => {
  const context = fixture();
  const product = {...source(), description: null};
  const planned = await preview(context, product);
  if (Object.hasOwn(planned.payload, "sale_intro")) {
    assert.ok(planned.payload.sale_intro === "" || JSON.parse(planned.payload.sale_intro).en === "");
  }
  const result = await apply(context, planned, product);
  assert.equal(result.ok, true, result.error);
});

test("decimal strings preserve six-place precision in native stock", async () => {
  const context = fixture();
  const data = metadata();
  data.native_stock[0].money = "9999999999.123456";
  data.native_stock[1].money = "0.000001";
  const planned = await preview(context, source(), data);
  assert.equal(JSON.parse(planned.payload.sale_stock)[0].money, "9999999999.123456");
  assert.equal(JSON.parse(planned.payload.sale_stock)[1].money, "0.000001");
  assert.equal((await apply(context, planned, source(), data)).ok, true);
});

test("numeric response IDs still require matching detail readback", async () => {
  const context = fixture({update(state, payload, calls, insert) {
    const record = insert(payload); state.hidden = true; return {result: record.sale_id};
  }});
  const planned = await preview(context);
  const result = await apply(context, planned);
  assert.equal(result.ok, true, result.error);
  assert.equal(result.product_id, 969086081);
  assert.equal(writes(context).length, 1);
  assert.ok(context.calls.some(call => call.action === "detail" && call.payload.id === 969086081));
});

test("a throwing save that reached the server is confirmed without another write", async () => {
  const context = fixture({update(state, payload, calls, insert) { insert(payload); throw new Error("Reply lost"); }});
  const planned = await preview(context);
  const result = await apply(context, planned);
  assert.equal(result.ok, true, result.error);
  assert.equal(result.verified, true);
  assert.equal(writes(context).length, 1);
});

test("unknown outcome persists the attempt guard and verify recovers later", async () => {
  const context = fixture({update(state, payload, calls, insert) {
    insert(payload); state.readUnavailable = true; return null;
  }});
  const planned = await preview(context);
  const uncertain = await apply(context, planned);
  assert.equal(uncertain.ok, false);
  assert.equal(uncertain.created, false);
  assert.equal(uncertain.verified, false);
  assert.equal(uncertain.saveAttempted, true);
  const repeated = await apply(context, planned);
  assert.equal(repeated.ok, false);
  assert.equal(writes(context).length, 1);
  context.state.readUnavailable = false;
  const recovered = await verify(context, planned);
  assert.equal(recovered.ok, true, recovered.error);
  assert.equal(recovered.verified, true);
  assert.equal(recovered.product_id, 969086081);
  assert.equal(recovered.saveAttempted, false);
  assert.equal(writes(context).length, 1);
});

test("a lost attempt guard cannot authorize another write and verify can recover the marker", async () => {
  const context = fixture({update(state, payload, calls, insert) {
    insert(payload); state.hidden = true; return null;
  }});
  const planned = await preview(context);
  const uncertain = await apply(context, planned);
  assert.equal(uncertain.ok, false);
  assert.equal(uncertain.created, false);
  assert.equal(uncertain.verified, false);
  assert.equal(uncertain.saveAttempted, true);
  assert.equal(writes(context).length, 1);
  global.__zyingWebProductCreateAttempts.clear();
  const repeated = await apply(context, planned);
  assert.equal(repeated.ok, false);
  assert.equal(repeated.created, false);
  assert.equal(repeated.verified, false);
  assert.equal(repeated.saveAttempted, false);
  assert.equal(writes(context).length, 1);
  context.state.hidden = false;
  const recovered = await verify(context, planned);
  assert.equal(recovered.ok, true, recovered.error);
  assert.equal(recovered.created, true);
  assert.equal(recovered.verified, true);
  assert.equal(recovered.product_id, 969086081);
  assert.equal(recovered.saveAttempted, false);
  assert.equal(writes(context).length, 1);
});

test("missing new IDs produce an unverified result and cannot retry the write", async () => {
  const context = fixture({update() { return null; }});
  const planned = await preview(context);
  const result = await apply(context, planned);
  assert.equal(result.ok, false);
  assert.equal(result.created, false);
  assert.equal(result.verified, false);
  assert.equal(result.saveAttempted, true);
  assert.ok(result.error);
  const repeated = await apply(context, planned);
  assert.equal(repeated.ok, false);
  assert.equal(writes(context).length, 1);
  assert.equal((await verify(context, planned)).ok, false);
  assert.equal(writes(context).length, 1);
});

test("a conflicting marker never causes mutation or success", async () => {
  for (const conflict of ["source", "cost", "title", "duplicate"]) {
    const context = fixture();
    const planned = await preview(context);
    const existing = context.insert(planned.payload);
    if (conflict === "source") existing.sale_source = "https://www.aliexpress.com/item/1005000000000000.html";
    if (conflict === "cost") existing.sale_cost = "99";
    if (conflict === "title") existing.sale_title = '{"en":"Different title"}';
    if (conflict === "duplicate") context.insert(planned.payload);
    const before = clone(context.state.records);
    const result = await apply(context, planned);
    assert.equal(result.ok, false, conflict);
    assert.equal(result.verified, false, conflict);
    assert.equal(writes(context).length, 0, conflict);
    assert.deepEqual(context.state.records, before);
  }
});

test("a marker appearing on a pre-existing ID cannot be adopted as a created record", async () => {
  const context = fixture();
  const planned = await preview(context);
  context.state.records[0] = {...clone(planned.payload), sale_id: 1001};
  const before = clone(context.state.records);
  const result = await apply(context, planned);
  assert.equal(result.ok, false);
  assert.equal(result.verified, false);
  assert.equal(writes(context).length, 0);
  assert.deepEqual(context.state.records, before);
});

test("readback handles images and stock in either server representation", async () => {
  for (const arrays of [true, false]) {
    const context = fixture({update(state, payload, calls, insert) {
      const record = insert(payload);
      record.sale_pic = arrays ? payload.sale_pic.split(",") : payload.sale_pic;
      record.sale_stock = arrays ? JSON.parse(payload.sale_stock) : payload.sale_stock;
      record.sale_cost = "1.230000";
      const rows = typeof record.sale_stock === "string" ? JSON.parse(record.sale_stock) : record.sale_stock;
      rows[0].money = 0.12; rows[1].money = "0.340000";
      record.sale_stock = arrays ? rows : JSON.stringify(rows);
      return null;
    }});
    const planned = await preview(context);
    const result = await apply(context, planned);
    assert.equal(result.ok, true, result.error);
    assert.equal(result.verified, true);
  }
});

test("live adult omission is reported without claiming a verified false and the same preview recovers", async () => {
  const context = fixture({update(state, payload, calls, insert) {
    const record = insert(payload);
    delete record.sale_adult;
    return null;
  }});
  const planned = await preview(context);
  const beforeSnapshot = clone(planned.snapshot);
  assert.equal(planned.payload.sale_adult, false);
  const result = await apply(context, planned);
  assert.equal(result.ok, true, result.error);
  assert.equal(result.created, true);
  assert.equal(result.verified, true);
  assert.equal(Object.hasOwn(result.checks, "adult"), false);
  assert.deepEqual(result.serverOmittedFields, ["sale_adult"]);
  const recovered = await verify(context, planned);
  assert.equal(recovered.ok, true, recovered.error);
  assert.equal(recovered.product_id, result.product_id);
  assert.equal(Object.hasOwn(recovered.checks, "adult"), false);
  assert.deepEqual(recovered.serverOmittedFields, ["sale_adult"]);
  assert.deepEqual(planned.snapshot, beforeSnapshot);
  assert.equal(writes(context).length, 1);
});

test("a returned adult field accepts only boolean false", async () => {
  for (const adult of [false, true, null, 0, "false", ""]) {
    const context = fixture({update(state, payload, calls, insert) {
      const record = insert(payload);
      record.sale_adult = adult;
      return null;
    }});
    const planned = await preview(context);
    const result = await apply(context, planned);
    assert.equal(result.ok, adult === false, String(adult));
    assert.equal(result.verified, adult === false, String(adult));
    assert.equal(result.checks.adult, adult === false, String(adult));
    assert.deepEqual(result.serverOmittedFields, []);
    assert.equal(writes(context).length, 1);
  }
});

test("readback rejects lost pictures, stock, category, and status", async () => {
  for (const alter of [record => { record.sale_pic = []; }, record => { record.sale_stock = "[]"; },
    record => { record.sale_localid = 152; }, record => { record.sale_stat = 3117; },
    record => { record.sale_weight = 101; }, record => { record.sale_cur = "USD"; },
    record => { record.sale_en = "Wrong short title"; }]) {
    const context = fixture({update(state, payload, calls, insert) { const record = insert(payload); alter(record); return null; }});
    const planned = await preview(context);
    const result = await apply(context, planned);
    assert.equal(result.ok, false);
    assert.equal(result.verified, false);
    assert.equal(result.saveAttempted, true);
    assert.equal(writes(context).length, 1);
  }
});

test("metadata, marker, and snapshot changes stop before any write", async () => {
  const context = fixture();
  const planned = await preview(context);
  for (const expected of [undefined, {...planned.snapshot, state: "not-json"},
    {...planned.snapshot, marker: "CODEX_BROWSER_CREATE_changed"}, {...planned.snapshot, version: 2}]) {
    const result = await create({action: "apply", source: source(), metadata: metadata(), expected}, context.transport);
    assert.equal(result.ok, false);
    assert.equal(result.saveAttempted, false);
  }
  const changed = {...metadata(), cost: "2"};
  assert.equal((await apply(context, planned, source(), changed)).ok, false);
  const product = {...source(), title: "Changed title"};
  assert.equal((await apply(context, planned, product)).ok, false);
  assert.equal(writes(context).length, 0);
});

test("source and required metadata validation stop before product calls", async () => {
  const context = fixture();
  const invalidSources = [null, [], {...source(), source_product_id: "wrong"},
    {...source(), source_url: "https://example.com/item/1005013209445272.html"},
    {...source(), source_url: "https://www.aliexpress.com/item/1005000000000000.html"},
    {...source(), title: ""}, {...source(), images: []}, {...source(), images: ["javascript:alert(1)"]}];
  for (const product of invalidSources) assert.equal((await create({action: "preview", source: product,
    metadata: metadata()}, context.transport)).ok, false);
  for (const [field, value] of [["category_id", 0], ["category_id", 1.5], ["category_id", 2147483648],
    ["english_short", ""], ["weight_g", -1], ["weight_g", 0.5], ["cost", -1], ["cost", "0.1234567"],
    ["cost", NaN], ["cost", 0.1 + 0.2], ["currency", ""], ["currency", "US"]]) {
    assert.equal((await create({action: "preview", source: source(), metadata: {...metadata(), [field]: value}},
      context.transport)).ok, false, `${field}=${value}`);
  }
  assert.equal(context.calls.length, 0);
});

test("native variant JSON, duplicates, and imprecise money are rejected before product calls", async () => {
  const context = fixture();
  const invalid = [
    {...metadata(), native_pair: undefined}, {...metadata(), native_stock: undefined},
    {...metadata(), native_pair: "{not-json}"}, {...metadata(), native_stock: "[not-json]"},
    {...metadata(), native_stock: [{key: "Black"}, {key: "Black"}]},
    {...metadata(), native_stock: [{key: "Black", money: "0.1234567"}]},
    {...metadata(), native_stock: [{key: "Black", money: -1}]},
    {...metadata(), native_stock: [{key: "Black", num: 0.5}]},
    {...metadata(), native_stock: [{key: "Black", source_sku_id: "120000000000001"}]},
  ];
  for (const data of invalid) {
    const result = await create({action: "preview", source: source(), metadata: data}, context.transport);
    assert.equal(result.ok, false);
  }
  assert.equal(context.calls.length, 0);
});

test("caller data and the approved preview remain immutable", async () => {
  const context = fixture();
  const product = freeze(source()); const data = freeze(metadata());
  const planned = await preview(context, product, data);
  const request = freeze({action: "apply", source: product, metadata: data, expected: planned.snapshot});
  const before = clone(request);
  const result = await create(request, context.transport);
  assert.equal(result.ok, true, result.error);
  assert.deepEqual(request, before);
});

test("only the ERP collection route may perform product calls", async () => {
  for (const location of [{origin: "https://seller.zying.net", hash: route},
    {origin: "https://erp.zying.net", hash: "#/product/myproduct/productlist"}]) {
    global.location = location;
    const result = await create({action: "preview", source: source(), metadata: metadata()},
      {handleProduct() { assert.fail("Wrong route called the product API"); }});
    assert.equal(result.ok, false);
    assert.equal(result.saveAttempted, false);
  }
});

test("navigation during the pre-save scan stops the mutation", async () => {
  const context = fixture({stat(state, payload, calls) {
    if (calls.filter(call => call.action === "stat").length === 2) global.location.hash = "#/product/myproduct/productlist";
    return {list: {data: state.records.map(record => ({id: record.sale_id})), maxcount: state.records.length}};
  }});
  const planned = await preview(context);
  const result = await apply(context, planned);
  assert.equal(result.ok, false);
  assert.equal(writes(context).length, 0);
});

test("list scans are bounded and malformed list data cannot trigger creation", async () => {
  for (const list of [{list: {data: null, maxcount: 1}}, {list: {data: [{id: "not-an-id"}], maxcount: 1}},
    {list: {data: [{id: 1001}, {id: 1001}], maxcount: 2}}]) {
    const context = fixture({stat() { return clone(list); }});
    const result = await create({action: "preview", source: source(), metadata: metadata()}, context.transport);
    assert.equal(result.ok, false);
    assert.equal(writes(context).length, 0);
  }
  const context = fixture();
  for (const limit of [0, 1001, 1.5]) assert.equal((await create({action: "preview", source: source(),
    metadata: metadata(), limit}, context.transport)).ok, false);
  assert.equal(context.calls.length, 0);
});

test("sparse images and array getters are rejected without evaluating data or calling the API", async () => {
  const sparse = [source().images[0]];
  sparse.length = 2;
  let getterReads = 0;
  const accessor = [source().images[0]];
  Object.defineProperty(accessor, "0", {enumerable: true, configurable: true,
    get() { getterReads++; return source().images[0]; }});
  for (const images of [sparse, accessor]) {
    const context = fixture();
    const result = await create({action: "preview", source: {...source(), images}, metadata: metadata()}, context.transport);
    assert.equal(result.ok, false);
    assert.equal(result.created, false);
    assert.equal(result.saveAttempted, false);
    assert.equal(context.calls.length, 0);
  }
  assert.equal(getterReads, 0);
});

test("native inventory totals beyond Int32 stop before even a list read", async () => {
  const context = fixture();
  const data = metadata();
  data.native_stock[0].num = 2147483647;
  data.native_stock[1].num = 1;
  const result = await create({action: "preview", source: source(), metadata: data}, context.transport);
  assert.equal(result.ok, false);
  assert.equal(result.created, false);
  assert.equal(result.saveAttempted, false);
  assert.equal(context.calls.length, 0);
});

test("concurrent apply calls share one attempt gate and issue exactly one create", async () => {
  const context = fixture();
  const planned = await preview(context);
  const results = await Promise.all([apply(context, planned), apply(context, planned)]);
  assert.equal(writes(context).length, 1);
  assert.equal(context.state.records.length, 2);
  assert.ok(results.some(result => result.ok && result.created && result.verified));
  assert.equal(results.filter(result => result.saveAttempted).length, 1);
  for (const result of results) if (!result.ok) {
    assert.equal(result.created, false);
    assert.equal(result.verified, false);
  }
  const recovered = await verify(context, planned);
  assert.equal(recovered.ok, true, recovered.error);
  assert.equal(recovered.product_id, 969086081);
  assert.equal(writes(context).length, 1);
});

test("the final gate rejects preview state cleared or replaced during the pre-save read", async () => {
  for (const replace of [false, true]) {
    const context = fixture({detail(state, payload) {
      const attempts = global.__zyingWebProductCreateAttempts;
      if (replace) attempts.set([...attempts.keys()][0], {state: "Different preview", attempted: false});
      else attempts.clear();
      return {root: clone(state.records.filter(record => record.sale_id === payload.id))};
    }});
    const planned = await preview(context);
    const result = await apply(context, planned);
    assert.equal(result.ok, false);
    assert.equal(result.created, false);
    assert.equal(result.saveAttempted, false);
    assert.equal(writes(context).length, 0);
    assert.equal(context.state.records.length, 1);
  }
});

test("a 101-record snapshot reads both pages with the stable maxcount", async () => {
  const records = Array.from({length: 101}, (_, index) => ({...unrelated(), sale_id: 1001 + index,
    sale_title: JSON.stringify({en: `Existing product ${index}`})}));
  const context = fixture({}, records);
  const planned = await preview(context, source(), metadata(), {limit: 101});
  assert.equal(planned.scannedBeforeCount, 101);
  assert.deepEqual(context.calls.map(call => call.action), ["stat", "stat"]);
  assert.deepEqual(context.calls[0].payload, {page: 1, pagesize: 100});
  assert.deepEqual(context.calls[1].payload, {page: 2, pagesize: 100, maxcount: 101});
  assert.equal(writes(context).length, 0);
});

test("a changing count between list pages cannot authorize a create", async () => {
  const context = fixture({stat(state, payload) {
    if (payload.page === 1) return {list: {data: Array.from({length: 100}, (_, index) => ({id: 1001 + index})), maxcount: 101}};
    return {list: {data: [{id: 1101}], maxcount: 102}};
  }});
  const result = await create({action: "preview", source: source(), metadata: metadata(), limit: 102}, context.transport);
  assert.equal(result.ok, false);
  assert.equal(result.created, false);
  assert.equal(result.saveAttempted, false);
  assert.equal(context.calls.length, 2);
  assert.equal(writes(context).length, 0);
});
