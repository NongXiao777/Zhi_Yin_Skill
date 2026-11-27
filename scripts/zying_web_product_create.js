// Run in the existing authenticated Product Collection tab. ProductApi owns
// the vendor transport. A null update response can still mean creation: only
// the new record's marker and complete detail readback establish success.
// Native variants are explicit caller data; source stock is not ERP inventory.
async function zyingWebProductCreate(request, testTransport) {
  const origin = "https://erp.zying.net", route = "#/product/1688/collectionlist";
  const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
  const plain = value => value !== null && typeof value === "object" && !Array.isArray(value) &&
    [Object.prototype, null].includes(Object.getPrototypeOf(value));
  const stop = error => { throw Object.assign(new Error(error), {createError: error}); };
  const clone = (value, depth = 0, seen = new Set()) => {
    if (depth > 25 || seen.has(value)) stop("invalid_json_data");
    if (value === null || ["string", "boolean"].includes(typeof value)) return value;
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (!plain(value) && !Array.isArray(value)) stop("invalid_json_data");
    seen.add(value);
    const result = Array.isArray(value) ? Array.from({length: value.length}, (_, index) => {
      const descriptor = Object.getOwnPropertyDescriptor(value, String(index));
      if (!descriptor || !own(descriptor, "value")) stop("invalid_json_data");
      return clone(descriptor.value, depth + 1, seen);
    }) :
      Object.fromEntries(Object.keys(value).sort().map(key => {
        const descriptor = Object.getOwnPropertyDescriptor(value, key);
        if (!own(descriptor, "value")) stop("invalid_json_data");
        return [key, clone(descriptor.value, depth + 1, seen)];
      }));
    seen.delete(value);
    return result;
  };
  const state = value => JSON.stringify(clone(value));
  const same = (left, right) => state(left) === state(right);
  const text = (value, maximum, error, empty = false) => {
    if (typeof value !== "string" || value.length > maximum || /\u0000/.test(value) || (!empty && !value.trim())) stop(error);
    return value;
  };
  const integer = (value, minimum = 0) => {
    if (!/^(0|[1-9]\d{0,9})$/.test(String(value)) || Number(value) < minimum || Number(value) > 2147483647) stop("invalid_integer");
    return Number(value);
  };
  const decimal = value => {
    if (!["string", "number"].includes(typeof value)) stop("invalid_decimal");
    const match = /^(0|[1-9]\d{0,9})(?:\.(\d{1,6}))?$/.exec(String(value));
    if (!match) stop("invalid_decimal");
    const fraction = (match[2] || "").replace(/0+$/, "");
    return match[1] + (fraction ? "." + fraction : "");
  };
  const validRoute = () => {
    if (typeof location !== "object" || location.origin !== origin || location.hash.split("?")[0] !== route) {
      stop("open_zying_web_collection");
    }
  };
  const sourceData = value => {
    if (!plain(value) || value.source !== "aliexpress" || typeof value.source_product_id !== "string" ||
      !/^\d{10,24}$/.test(value.source_product_id)) stop("invalid_source");
    let url;
    try { url = new URL(value.source_url); } catch { stop("invalid_source_url"); }
    if (typeof value.source_url !== "string" || value.source_url.length > 2000 || url.protocol !== "https:" ||
      url.username || url.password || url.port || url.search || url.hash ||
      !/^(?:(?:www|m)\.)?aliexpress\.com$/i.test(url.hostname) ||
      url.pathname.match(/^\/(?:item|i)\/(\d{10,24})\.html\/?$/i)?.[1] !== value.source_product_id) stop("source_item_mismatch");
    const title = text(value.title, 1000, "invalid_english_title");
    if (!Array.isArray(value.images) || !value.images.length || value.images.length > 40) stop("invalid_images");
    const images = value.images.map(address => {
      let image; try { image = new URL(address); } catch { stop("invalid_image_url"); }
      if (typeof address !== "string" || address.length > 2000 || address.includes(",") || image.protocol !== "https:" ||
        image.username || image.password || image.port || image.search || image.hash ||
        ![".alicdn.com", ".aliexpress-media.com"].some(suffix => image.hostname.endsWith(suffix))) stop("invalid_image_url");
      return address;
    });
    if (new Set(images).size !== images.length) stop("duplicate_image_url");
    const description = value.description == null || (typeof value.description === "string" && !value.description.trim()) ? null :
      text(value.description, 100000, "invalid_description", true);
    return {source: "aliexpress", source_product_id: value.source_product_id, source_url: value.source_url, title, images, description};
  };
  const metadataData = value => {
    const allowed = ["category_id", "english_short", "weight_g", "cost", "currency", "note", "native_pair", "native_stock"];
    if (!plain(value) || Object.keys(value).some(key => !allowed.includes(key)) ||
      ["category_id", "english_short", "weight_g", "cost", "currency"].some(key => !own(value, key))) stop("invalid_metadata");
    const category_id = integer(value.category_id, 1), weight_g = integer(value.weight_g, 1);
    const english_short = text(value.english_short, 200, "invalid_english_short");
    const cost = decimal(value.cost);
    if (typeof value.currency !== "string" || !/^[A-Z]{3}$/.test(value.currency)) stop("invalid_currency");
    const note = own(value, "note") ? text(value.note, 8000, "invalid_note", true) : "";
    if (note.includes("CODEX_BROWSER_CREATE_")) stop("invalid_note_marker");
    if (own(value, "native_pair") !== own(value, "native_stock")) stop("native_pair_and_stock_required_together");
    const pair = own(value, "native_pair") ? clone(value.native_pair) : {};
    if (!plain(pair) || Object.keys(pair).length > 8) stop("invalid_native_pair");
    for (const [key, options] of Object.entries(pair)) {
      text(key, 200, "invalid_native_pair");
      if (!Array.isArray(options) || !options.length || options.length > 500 || new Set(options).size !== options.length) stop("invalid_native_pair");
      options.forEach(option => text(option, 1000, "invalid_native_pair"));
    }
    const rows = own(value, "native_stock") ? clone(value.native_stock) : [];
    if (!Array.isArray(rows) || rows.length > 500 || (rows.length > 0 && !Object.keys(pair).length)) stop("invalid_native_stock");
    const keys = new Set(), columns = ["key", "no", "spec", "num", "weight", "money", "areas", "pic", "img"];
    for (const row of rows) {
      if (!plain(row) || Object.keys(row).some(key => !columns.includes(key))) stop("invalid_native_stock");
      text(row.key, 2000, "invalid_native_key");
      if (keys.has(row.key)) stop("duplicate_native_key");
      keys.add(row.key);
      row.num = integer(row.num ?? 0); row.weight = integer(row.weight ?? 0);
      const money = decimal(row.money ?? 0);
      // Keep decimal strings as strings, avoiding a Number round trip. The
      // web stock control itself emits strings; readback compares semantics.
      row.money = typeof row.money === "string" ? money : Number(money);
      for (const field of ["no", "pic", "img"]) if (own(row, field)) text(row[field], 2000, "invalid_native_stock", true);
    }
    if (state(rows).length > 1000000) stop("native_stock_too_large");
    if (rows.reduce((sum, row) => sum + row.num, 0) > 2147483647) stop("invalid_inventory_total");
    return {category_id, english_short, weight_g, cost, currency: value.currency, note, native_pair: pair, native_stock: rows};
  };
  const payloadData = (source, metadata, marker) => ({
    sale_localid: metadata.category_id, sale_en: metadata.english_short, sale_weight: metadata.weight_g,
    sale_cost: metadata.cost, sale_cur: metadata.currency, sale_source: source.source_url,
    sale_title: JSON.stringify({en: source.title}), sale_pic: source.images.join(","),
    ...(source.description === null ? {} : {sale_intro: JSON.stringify({en: source.description})}),
    sale_stat: 3411, sale_flag: 400, sale_level: 10, sale_grade: 1, sale_adult: false,
    sale_pair: JSON.stringify(metadata.native_pair), sale_stock: JSON.stringify(metadata.native_stock),
    sale_num: metadata.native_stock.reduce((sum, row) => sum + row.num, 0), sale_items: 1, sale_local: "",
    sale_memo: (metadata.note ? metadata.note + "\n" : "") + "[" + marker + "]"
  });
  const jsonValue = (value, empty) => {
    if (value == null || value === "") return clone(empty);
    try { return typeof value === "string" ? clone(JSON.parse(value)) : clone(value); } catch { stop("web_detail_unreadable"); }
  };
  let transport, source, metadata, limit, snapshot, payload, marker, saveAttempted = false;
  const readIds = async () => {
    const ids = new Set(), pagesize = Math.min(100, limit);
    let count = null;
    for (let page = 1; ids.size < limit; page++) {
      validRoute();
      let result;
      try { result = await transport.handleProduct("spider", "stat", {page, pagesize, ...(page === 1 ? {} : {maxcount: count})}); }
      catch { stop("web_product_list_unavailable"); }
      validRoute();
      if (!plain(result?.list) || !Array.isArray(result.list.data)) stop("web_product_list_unreadable");
      const observed = integer(result.list.maxcount);
      if (count === null) count = observed;
      if (observed !== count || count > limit) stop("web_product_list_changed_or_scan_limit");
      const rows = result.list.data;
      if (rows.length > pagesize) stop("web_product_list_unreadable");
      for (const row of rows) {
        if (!plain(row)) stop("web_product_list_unreadable");
        const id = integer(row.id, 1);
        if (ids.has(id)) stop("web_product_list_changed_or_scan_limit");
        ids.add(id);
      }
      if (ids.size === count) return [...ids].sort((a, b) => a - b);
      if (!rows.length || ids.size > count) stop("web_product_list_unreadable");
    }
    stop("web_product_list_changed_or_scan_limit");
  };
  const readRecord = async id => {
    validRoute();
    let result;
    try { result = await transport.handleProduct("spider", "detail", {id}); } catch { stop("web_detail_unavailable"); }
    validRoute();
    if (!Array.isArray(result?.root) || result.root.length !== 1 || !plain(result.root[0]) ||
      integer(result.root[0].sale_id, 1) !== id) stop("unexpected_product_detail");
    return clone(result.root[0]);
  };
  const compare = record => {
    const rows = jsonValue(record.sale_stock, []);
    if (!Array.isArray(rows)) stop("web_detail_unreadable");
    const normalizedRows = value => value.map(row => {
      if (!plain(row)) stop("web_detail_unreadable");
      const result = clone(row);
      result.num = integer(result.num ?? 0); result.weight = integer(result.weight ?? 0);
      result.money = decimal(result.money ?? 0);
      return result;
    });
    const pics = Array.isArray(record.sale_pic) ? record.sale_pic :
      typeof record.sale_pic === "string" ? record.sale_pic.split(",").filter(Boolean) : [];
    const checks = {source: record.sale_source === payload.sale_source, marker: record.sale_memo === payload.sale_memo,
      title: same(jsonValue(record.sale_title, {}), {en: source.title}), images: same(pics, source.images),
      category: integer(record.sale_localid) === metadata.category_id, englishShort: record.sale_en === metadata.english_short,
      weight: integer(record.sale_weight) === metadata.weight_g, cost: decimal(record.sale_cost) === metadata.cost,
      currency: record.sale_cur === metadata.currency, status: integer(record.sale_stat) === 3411,
      pair: same(jsonValue(record.sale_pair, {}), metadata.native_pair),
      stock: same(normalizedRows(rows), normalizedRows(metadata.native_stock)),
      inventory: integer(record.sale_num) === payload.sale_num, items: integer(record.sale_items) === 1,
      local: record.sale_local == null || record.sale_local === ""};
    const serverOmittedFields = [];
    // Live spider.detail can omit this field. An omission cannot establish
    // that the submitted false value was stored by the server.
    if (own(record, "sale_adult")) checks.adult = record.sale_adult === false;
    else serverOmittedFields.push("sale_adult");
    if (source.description !== null) checks.description = same(jsonValue(record.sale_intro, {}), {en: source.description});
    return {verified: Object.values(checks).every(Boolean), checks, serverOmittedFields};
  };
  const findMarker = async (extraIds = []) => {
    const ids = await readIds(), matches = [];
    for (const id of [...new Set([...extraIds, ...ids])]) {
      const record = await readRecord(id);
      if (typeof record.sale_memo === "string" && record.sale_memo.includes(marker)) matches.push(record);
    }
    if (matches.length > 1) stop("duplicate_creation_marker");
    if (!matches.length) return null;
    const record = matches[0], id = integer(record.sale_id, 1);
    const bound = JSON.parse(snapshot.state);
    if (bound.before_ids.includes(id)) stop("creation_marker_on_existing_record");
    const result = compare(record);
    if (!result.verified) return {ok: false, stage: "product_create_unverified", created: false, verified: false,
      product_id: id, marker, error: "web_creation_readback_mismatch", ...result};
    return {ok: true, stage: "product_create_verified", created: true, verified: true, product_id: id, marker, ...result};
  };
  const attemptState = value => {
    const key = "zying:create:v1:" + marker;
    if (testTransport) {
      if (!(globalThis.__zyingWebProductCreateAttempts instanceof Map)) globalThis.__zyingWebProductCreateAttempts = new Map();
      if (value) globalThis.__zyingWebProductCreateAttempts.set(key, clone(value));
      return globalThis.__zyingWebProductCreateAttempts.get(key) || null;
    }
    // This tab's sessionStorage survives reloads. Persist before the write so
    // an unverified attempt can only be recovered by readback, never retried.
    try {
      if (value) sessionStorage.setItem(key, JSON.stringify(value));
      const stored = sessionStorage.getItem(key);
      return stored ? JSON.parse(stored) : null;
    } catch { stop("web_creation_attempt_state_unavailable"); }
  };
  try {
    if (!plain(request)) stop("invalid_request");
    request = clone(request);
    if (Object.keys(request).some(key => !["action", "source", "metadata", "expected", "limit"].includes(key)) ||
      !["preview", "apply", "verify"].includes(request.action)) stop("invalid_request");
    if (state(request).length > 2000000) stop("request_too_large");
    source = sourceData(request.source); metadata = metadataData(request.metadata);
    limit = request.limit ?? 1000;
    if (!Number.isInteger(limit) || limit < 1 || limit > 1000) stop("invalid_scan_limit");
    if (request.action === "preview" && own(request, "expected")) stop("invalid_request");
    validRoute(); transport = testTransport;
    if (!transport) {
      const assets = new Set();
      if (typeof performance !== "object" || typeof performance.getEntriesByType !== "function") stop("web_product_module_unavailable");
      for (const entry of performance.getEntriesByType("resource")) {
        let url; try { url = new URL(entry.name); } catch { continue; }
        if (url.origin === origin && /^\/assets\/ProductApi-[\w-]+\.js$/.test(url.pathname)) assets.add(url.href);
      }
      if (assets.size !== 1) stop("web_product_module_unavailable");
      try { transport = (await import([...assets][0])).P; } catch { stop("web_product_module_unavailable"); }
    }
    if (typeof transport?.handleProduct !== "function") stop("web_product_module_changed");
    if (request.action === "preview") {
      const before_ids = await readIds();
      const random = new Uint32Array(4);
      if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(random);
      else if (testTransport) for (let i = 0; i < random.length; i++) random[i] = Math.floor(Math.random() * 4294967296);
      else stop("web_creation_marker_unavailable");
      marker = "CODEX_BROWSER_CREATE_" + Date.now().toString(36).toUpperCase() + "_" +
        [...random].map(value => value.toString(16).padStart(8, "0")).join("").toUpperCase();
      payload = payloadData(source, metadata, marker);
      if (payload.sale_num > 2147483647) stop("invalid_inventory_total");
      snapshot = {version: 1, origin, route, marker, state: state({source, metadata, payload, before_ids, limit})};
      if (snapshot.state.length > 1500000) stop("creation_plan_too_large");
      attemptState({state: snapshot.state, attempted: false});
      return {ok: true, stage: "product_create_preview", created: false, verified: false, saveAttempted: false,
        marker, payload: clone(payload), snapshot, scannedBeforeCount: before_ids.length};
    }
    snapshot = clone(request.expected);
    if (!plain(snapshot) || Object.keys(snapshot).length !== 5 || snapshot.version !== 1 || snapshot.origin !== origin ||
      snapshot.route !== route || typeof snapshot.marker !== "string" ||
      !/^CODEX_BROWSER_CREATE_[A-Z0-9]+_[A-F0-9]{32}$/.test(snapshot.marker) ||
      typeof snapshot.state !== "string" || snapshot.state.length > 1500000) stop("invalid_expected_snapshot");
    marker = snapshot.marker; payload = payloadData(source, metadata, marker);
    let bound;
    try { bound = JSON.parse(snapshot.state); } catch { stop("invalid_expected_snapshot"); }
    if (!plain(bound) || !Array.isArray(bound.before_ids) || bound.before_ids.length > limit ||
      new Set(bound.before_ids).size !== bound.before_ids.length || bound.before_ids.some(id => integer(id, 1) !== id) ||
      snapshot.state !== state({source, metadata, payload, before_ids: bound.before_ids, limit})) stop("expected_snapshot_mismatch");
    let stored;
    try { stored = attemptState(); }
    catch (error) { if (request.action !== "verify") throw error; }
    if (stored && stored.state !== snapshot.state) stop("creation_attempt_snapshot_mismatch");
    const current = await findMarker(stored?.id ? [stored.id] : []);
    if (current) return {...current, saveAttempted: false};
    if (request.action === "verify" || stored?.attempted) return {ok: false, stage: "product_create_unverified", created: false,
      verified: false, marker, saveAttempted: false, error: stored?.attempted ? "web_creation_outcome_uncertain" : "created_product_not_found"};
    // A copied preview or cleared browser state must not turn an old uncertain
    // attempt into a fresh write. Verify remains available as a read-only recovery.
    if (!stored) stop("creation_preview_state_missing");
    validRoute();
    // Check and set without awaiting: concurrent calls in this tab cannot
    // both pass this gate. No update includes an existing product ID.
    const gate = attemptState();
    if (!gate) stop("creation_preview_state_missing");
    if (gate.state !== snapshot.state) stop("creation_attempt_snapshot_mismatch");
    if (gate.attempted) stop("web_creation_outcome_uncertain");
    attemptState({state: snapshot.state, attempted: true});
    saveAttempted = true;
    let response, saveResponse = "received";
    try { response = await transport.handleProduct("spider", "update", clone(payload)); }
    catch { saveResponse = "unavailable"; }
    const idValue = typeof response === "number" ? response : response?.result;
    const id = /^[1-9]\d{0,9}$/.test(String(idValue)) && Number(idValue) <= 2147483647 ? Number(idValue) : null;
    if (id) attemptState({state: snapshot.state, attempted: true, id});
    const result = await findMarker(id ? [id] : []);
    if (result) return {...result, stage: result.verified ? "product_create_applied" : result.stage, saveAttempted, saveResponse};
    return {ok: false, stage: "product_create_unverified", created: false, verified: false, marker, saveAttempted, saveResponse,
      error: "web_creation_outcome_uncertain"};
  } catch (error) {
    return {ok: false, stage: "product_create_unverified", created: false, verified: false, saveAttempted,
      ...(marker ? {marker} : {}), error: error?.createError || "web_product_create_failed"};
  }
}

if (typeof module === "object") module.exports = zyingWebProductCreate;
