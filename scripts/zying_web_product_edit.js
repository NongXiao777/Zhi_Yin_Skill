// Evaluate in the existing, authenticated ERP tab. The loaded ProductApi
// module supplies the vendor's transport; this helper does not construct HTTP
// routes, credentials, or signatures. testTransport is only an offline seam.
// apply and verify require the unchanged snapshot returned by preview.
async function zyingWebProductEdit(request, testTransport) {
  const routes = {sale: "#/product/myproduct/productlist", spider: "#/product/1688/collectionlist"};
  const columns = {english_title: "sale_title", english_brief: "sale_brief", english_keys: "sale_keys",
    english_bullet: "sale_bullet", english_description: "sale_intro"};
  const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
  const plain = value => value !== null && typeof value === "object" && !Array.isArray(value) &&
    [Object.prototype, null].includes(Object.getPrototypeOf(value));
  const stop = error => { throw Object.assign(new Error(error), {productEditError: error}); };
  // JSON.parse/JSON.stringify would round long decimal tokens in untouched
  // stock entries. Keep their original tokens and write requested money as a
  // JSON number without first converting its decimal string to a JS Number.
  class JsonNumber { constructor(text) { this.text = text; } }
  const numberText = value => {
    let text = value instanceof JsonNumber ? value.text : String(value);
    const parts = /^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/.exec(text);
    if (!parts) stop("product_data_unreadable");
    const exponent = Number(parts[4] || 0);
    if (!Number.isInteger(exponent) || Math.abs(exponent) > 1000) stop("product_data_unreadable");
    let digits = parts[2] + (parts[3] || "");
    const point = parts[2].length + exponent;
    text = point <= 0 ? "0." + "0".repeat(-point) + digits :
      point >= digits.length ? digits + "0".repeat(point - digits.length) :
        digits.slice(0, point) + "." + digits.slice(point);
    let [integer, fraction = ""] = text.split(".");
    integer = integer.replace(/^0+(?=\d)/, "");
    fraction = fraction.replace(/0+$/, "");
    text = integer + (fraction ? "." + fraction : "");
    return parts[1] && text !== "0" ? "-" + text : text;
  };
  const json = text => {
    if (typeof text !== "string" || text.length > 2000000) stop("product_data_unreadable");
    let index = 0;
    const whitespace = () => { while (/[\x20\t\r\n]/.test(text[index] || "x")) index++; };
    const string = () => {
      const start = index++;
      while (index < text.length) {
        if (text[index] === "\\") { index += 2; continue; }
        if (text[index++] === '"') {
          try { return JSON.parse(text.slice(start, index)); } catch { stop("product_data_unreadable"); }
        }
      }
      stop("product_data_unreadable");
    };
    const value = depth => {
      if (depth > 40) stop("product_data_unreadable");
      whitespace();
      if (text[index] === '"') return string();
      if (text[index] === "[" || text[index] === "{") {
        const array = text[index++] === "[";
        const result = array ? [] : Object.create(null);
        whitespace();
        const end = array ? "]" : "}";
        if (text[index] === end) { index++; return result; }
        while (index < text.length) {
          whitespace();
          let key;
          if (!array) {
            if (text[index] !== '"') stop("product_data_unreadable");
            key = string();
            whitespace();
            if (text[index++] !== ":" || own(result, key)) stop("product_data_unreadable");
          }
          const item = value(depth + 1);
          if (array) result.push(item); else result[key] = item;
          whitespace();
          const next = text[index++];
          if (next === end) return result;
          if (next !== ",") stop("product_data_unreadable");
        }
        stop("product_data_unreadable");
      }
      for (const [token, item] of [["true", true], ["false", false], ["null", null]]) {
        if (text.startsWith(token, index)) { index += token.length; return item; }
      }
      const match = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(text.slice(index));
      if (!match) stop("product_data_unreadable");
      index += match[0].length;
      return new JsonNumber(match[0]);
    };
    const result = value(0);
    whitespace();
    if (index !== text.length) stop("product_data_unreadable");
    return result;
  };
  const copy = (value, depth = 0, seen = new Set()) => {
    if (depth > 40 || seen.has(value)) stop("product_data_unreadable");
    if (value instanceof JsonNumber) return new JsonNumber(value.text);
    if (value == null || ["string", "boolean", "undefined"].includes(typeof value)) return value;
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (!plain(value) && !Array.isArray(value)) stop("product_data_unreadable");
    seen.add(value);
    const result = Array.isArray(value) ? value.map(item => copy(item, depth + 1, seen)) :
      Object.fromEntries(Object.keys(value).map(key => {
        const descriptor = Object.getOwnPropertyDescriptor(value, key);
        if (!own(descriptor, "value")) stop("product_data_unreadable");
        return [key, copy(descriptor.value, depth + 1, seen)];
      }));
    seen.delete(value);
    return result;
  };
  const encoded = value => {
    if (value === undefined) return ["undefined"];
    if (value === null) return ["null"];
    if (value instanceof JsonNumber) return ["json_number", value.text];
    if (["string", "boolean", "number"].includes(typeof value)) return [typeof value, value];
    if (Array.isArray(value)) return ["array", value.map(encoded)];
    return ["object", Object.keys(value).sort().map(key => [key, encoded(value[key])])];
  };
  const state = value => JSON.stringify(encoded(copy(value)));
  const decode = (value, depth = 0) => {
    if (depth > 40 || !Array.isArray(value)) stop("invalid_expected_snapshot");
    const [type, data] = value;
    if (["undefined", "null"].includes(type) && value.length === 1) return type === "null" ? null : undefined;
    if (value.length !== 2) stop("invalid_expected_snapshot");
    if (["string", "boolean", "number"].includes(type) && typeof data === type &&
      (type !== "number" || Number.isFinite(data))) return data;
    if (type === "array" && Array.isArray(data)) return data.map(item => decode(item, depth + 1));
    if (type === "object" && Array.isArray(data)) {
      const result = Object.create(null);
      for (const pair of data) {
        if (!Array.isArray(pair) || pair.length !== 2 || typeof pair[0] !== "string" || own(result, pair[0])) {
          stop("invalid_expected_snapshot");
        }
        result[pair[0]] = decode(pair[1], depth + 1);
      }
      return result;
    }
    stop("invalid_expected_snapshot");
  };
  const serialize = (value, canonical = false) => {
    if (value instanceof JsonNumber) return canonical ? numberText(value) : value.text;
    if (typeof value === "number") return numberText(value);
    if (value === null || ["string", "boolean"].includes(typeof value)) return JSON.stringify(value);
    if (Array.isArray(value)) return "[" + value.map(item => serialize(item, canonical)).join(",") + "]";
    if (!plain(value)) stop("product_data_unreadable");
    const keys = Object.keys(value);
    if (canonical) keys.sort();
    return "{" + keys.map(key => JSON.stringify(key) + ":" + serialize(value[key], canonical)).join(",") + "}";
  };
  const sameJson = (left, right) => serialize(left, true) === serialize(right, true);
  const decimal = (value, input = false) => {
    if (!(value instanceof JsonNumber) && !["string", "number"].includes(typeof value)) return null;
    let text = value instanceof JsonNumber ? numberText(value) : String(value);
    if (!input && typeof value === "number" && Number.isFinite(value)) text = numberText(value);
    const match = /^(0|[1-9][0-9]{0,9})(?:\.([0-9]{1,6}))?$/.exec(text);
    if (!match) return null;
    const fraction = (match[2] || "").replace(/0+$/, "");
    return match[1] + (fraction ? "." + fraction : "");
  };
  const languageMap = value => {
    if (value == null || value === "") return Object.create(null);
    const map = typeof value === "string" ? json(value) : copy(value);
    if (!plain(map)) stop("language_map_unreadable");
    return map;
  };
  const stocks = value => {
    if (value == null || value === "") return [];
    const rows = typeof value === "string" ? json(value) : copy(value);
    if (!Array.isArray(rows)) stop("stock_unreadable");
    return rows;
  };
  const englishCopy = record => Object.fromEntries(Object.entries(columns).map(([field, column]) => {
    try { const map = languageMap(record[column]); return [field, typeof map.en === "string" ? map.en : null]; }
    catch { return [field, null]; }
  }));
  const changesFrom = changes => {
    if (!plain(changes) || Object.keys(changes).some(key => !own(columns, key) && key !== "surcharges")) stop("invalid_changes");
    const result = {};
    for (const field of Object.keys(columns)) {
      if (!own(changes, field)) continue;
      const text = changes[field];
      if (typeof text !== "string" || text.length > 100000 || /\u0000/.test(text) ||
        (field === "english_title" && !text.trim())) stop("invalid_english_copy");
      result[field] = text;
    }
    if (own(changes, "surcharges")) {
      if (!Array.isArray(changes.surcharges) || !changes.surcharges.length || changes.surcharges.length > 500) stop("invalid_surcharges");
      const seen = new Set();
      result.surcharges = changes.surcharges.map(item => {
        if (!plain(item) || Object.keys(item).length !== 2 || !own(item, "key") || !own(item, "value") ||
          typeof item.key !== "string" || !item.key || item.key.length > 2000 || seen.has(item.key)) stop("invalid_variant_key");
        seen.add(item.key);
        const value = decimal(item.value, true);
        if (value === null) stop("invalid_surcharge");
        return {key: item.key, value};
      });
    }
    if (!Object.keys(result).length) stop("empty_changes");
    return result;
  };
  const plan = (record, changes) => {
    // Even a copy-only save must have a readable baseline for the complete
    // variant-preservation check performed after saving.
    const rows = stocks(record.sale_stock);
    const fields = {sale_id: Number(record.sale_id)};
    const comparison = [];
    for (const [field, column] of Object.entries(columns)) {
      if (!own(changes, field)) continue;
      let map;
      try { map = languageMap(record[column]); } catch { stop("language_map_unreadable"); }
      comparison.push({field, observed: typeof map.en === "string" ? map.en : null, wanted: changes[field]});
      map.en = changes[field];
      fields[column] = serialize(map);
    }
    if (own(changes, "surcharges")) {
      for (const item of changes.surcharges) {
        const matched = rows.filter(row => plain(row) && row.key === item.key);
        if (matched.length !== 1) stop("variant_not_unique_or_unreadable");
        const observed = decimal(matched[0].money ?? 0);
        if (observed === null) stop("variant_not_unique_or_unreadable");
        comparison.push({field: "surcharge", variant_key: item.key, observed, wanted: item.value});
        matched[0].money = new JsonNumber(item.value);
      }
      fields.sale_stock = serialize(rows);
    }
    return {fields, comparison};
  };
  let source, id, route, changes, baseline, transport;
  const validRoute = () => {
    if (typeof location !== "object" || location.origin !== "https://erp.zying.net" ||
      location.hash.split("?")[0] !== route) stop(source === "sale" ? "open_zying_web_my_products" : "open_zying_web_collection");
  };
  const snapshot = record => ({version: 1, source, product_id: id, route, state: state({record, changes})});
  const readRecord = async () => {
    validRoute();
    let detail;
    try { detail = await transport.handleProduct(source, "detail", {id}); } catch { stop("web_detail_unavailable"); }
    validRoute();
    if (!Array.isArray(detail?.root) || detail.root.length !== 1) stop("product_not_found");
    const record = copy(detail.root[0]);
    if (!plain(record) || String(record.sale_id) !== String(id)) stop("unexpected_product");
    if (state(record).length > 2000000) stop("product_data_too_large");
    return record;
  };
  const expectedBaseline = expected => {
    if (!plain(expected) || Object.keys(expected).length !== 5 || expected.version !== 1 || expected.source !== source ||
      expected.product_id !== id || expected.route !== route || typeof expected.state !== "string" || expected.state.length > 3000000) {
      stop("invalid_expected_snapshot");
    }
    let bound;
    try { bound = decode(JSON.parse(expected.state)); } catch { stop("invalid_expected_snapshot"); }
    if (!plain(bound) || Object.keys(bound).length !== 2 || !plain(bound.record) ||
      String(bound.record.sale_id) !== String(id) || state(bound.changes) !== state(changes) ||
      state(expected) !== state(snapshot(bound.record))) stop("expected_snapshot_mismatch");
    return bound.record;
  };
  const verify = (before, after) => {
    const wanted = plan(before, changes);
    const comparison = plan(after, changes).comparison.map(item => ({...item, matches: item.observed === item.wanted}));
    let languagesPreserved = true;
    for (const [field, column] of Object.entries(columns)) {
      if (!own(changes, field)) continue;
      const oldMap = languageMap(before[column]);
      const newMap = languageMap(after[column]);
      delete oldMap.en; delete newMap.en;
      if (!sameJson(oldMap, newMap)) languagesPreserved = false;
    }
    const normalizedTargets = rows => {
      for (const item of changes.surcharges || []) {
        for (const row of rows.filter(row => plain(row) && row.key === item.key)) {
          const money = decimal(row.money ?? 0);
          if (money !== null) row.money = new JsonNumber(money);
        }
      }
      return rows;
    };
    // The server may encode a requested zero by omitting money, or return a
    // requested decimal as text. Only target money values are normalized;
    // every other stock property and every untouched row must still match.
    const allVariantsPreserved = own(changes, "surcharges") ?
      sameJson(normalizedTargets(stocks(wanted.fields.sale_stock)), normalizedTargets(stocks(after.sale_stock))) :
      sameJson(stocks(before.sale_stock), stocks(after.sale_stock));
    const excluded = new Set(["sale_log", ...Object.keys(wanted.fields).filter(key => key !== "sale_id"), "sale_stock"]);
    const changedOtherFields = [...new Set([...Object.keys(before), ...Object.keys(after)])]
      .filter(key => !excluded.has(key) && state(before[key]) !== state(after[key]));
    const checks = {identity: String(after.sale_id) === String(id), requestedValues: comparison.every(item => item.matches),
      otherLanguagesPreserved: languagesPreserved, allVariantsPreserved,
      otherFieldsPreserved: changedOtherFields.length === 0};
    const serverChangedFields = state(before.sale_log) !== state(after.sale_log) ? ["sale_log"] : [];
    return {verified: Object.values(checks).every(Boolean), checks, comparison, changedOtherFields, serverChangedFields};
  };
  try {
    if (!plain(request) || Object.keys(request).some(key => !["action", "source", "product_id", "changes", "expected", "limit"].includes(key)) ||
      !["read", "preview", "apply", "verify"].includes(request.action)) stop("invalid_request");
    if (state(request).length > 4000000) stop("request_too_large");
    source = request.source;
    if (!own(routes, source)) stop("invalid_source");
    route = routes[source];
    const idText = String(request.product_id ?? "");
    id = /^[1-9][0-9]{0,9}$/.test(idText) ? Number(idText) : 0;
    if (id === 0 || id > 2147483647) stop("invalid_product_id");
    const limit = request.limit ?? 10;
    if (!Number.isInteger(limit) || limit < 1 || limit > 50) stop("invalid_limit");
    if (request.action === "read" && (own(request, "changes") || own(request, "expected"))) stop("invalid_request");
    if (request.action === "preview" && own(request, "expected")) stop("invalid_request");
    changes = request.action === "read" ? null : changesFrom(request.changes);
    validRoute();
    if (["apply", "verify"].includes(request.action)) baseline = expectedBaseline(request.expected);
    transport = testTransport;
    if (!transport) {
      if (typeof performance !== "object" || typeof performance.getEntriesByType !== "function") stop("web_product_module_unavailable");
      const assets = new Set();
      for (const entry of performance.getEntriesByType("resource")) {
        let url; try { url = new URL(entry.name); } catch { continue; }
        if (url.origin === location.origin && /^\/assets\/ProductApi-[\w-]+\.js$/.test(url.pathname)) assets.add(url.href);
      }
      if (assets.size !== 1) stop("web_product_module_unavailable");
      try { const module = await import([...assets][0]); transport = module.P; } catch { stop("web_product_module_unavailable"); }
    }
    if (typeof transport?.handleProduct !== "function") stop("web_product_module_changed");
    const current = await readRecord();
    const base = {ok: true, source: "web_" + source + "_detail", product_id: id};
    if (request.action === "read") {
      const rows = stocks(current.sale_stock);
      const variants = rows.filter(row => plain(row) && typeof row.key === "string" && row.key)
        .map(row => ({key: row.key, surcharge: decimal(row.money ?? 0)}));
      return {...base, stage: "product_edit_read", copy: englishCopy(current), total_variants: variants.length,
        total_stock_entries: rows.length, variants: variants.slice(0, limit)};
    }
    const wanted = plan(current, changes);
    if (request.action === "preview") return {...base, stage: "product_edit_preview", copy: englishCopy(current),
      comparison: wanted.comparison, snapshot: snapshot(current), updateColumns: Object.keys(wanted.fields),
      alreadyMatches: wanted.comparison.every(item => item.observed === item.wanted)};
    if (request.action === "verify") {
      const result = verify(baseline, current);
      return {...base, ok: result.verified, stage: "product_edit_verified", ...result, copy: englishCopy(current),
        ...(result.verified ? {} : {error: "web_readback_mismatch"})};
    }
    if (state(request.expected) !== state(snapshot(current))) stop("expected_snapshot_conflict");
    if (wanted.comparison.every(item => item.observed === item.wanted)) {
      const result = verify(baseline, current);
      return {...base, stage: "product_edit_already_matches", ...result, copy: englishCopy(current), saveAttempted: false};
    }
    validRoute();
    let saveResponse = "received";
    try { await transport.handleProduct(source, "update", copy(wanted.fields)); } catch { saveResponse = "unavailable"; }
    // One readback even when the save throws; never repeat an uncertain write.
    let after;
    try { after = await readRecord(); } catch (error) {
      return {...base, ok: false, stage: "product_edit_unverified", error: "web_save_outcome_uncertain", verified: false,
        saveAttempted: true, saveResponse, readbackError: error?.productEditError || "web_detail_unavailable"};
    }
    let result;
    try { result = verify(baseline, after); } catch (error) {
      return {...base, ok: false, stage: "product_edit_unverified", error: "web_readback_mismatch", verified: false,
        saveAttempted: true, saveResponse, readbackError: error?.productEditError || "product_data_unreadable"};
    }
    return {...base, ok: result.verified, stage: result.verified ? "product_edit_applied" : "product_edit_unverified",
      ...result, copy: englishCopy(after), saveAttempted: true, saveResponse,
      ...(result.verified ? {} : {error: "web_readback_mismatch"})};
  } catch (error) {
    return {ok: false, error: error?.productEditError || "web_product_edit_failed", verified: false, saveAttempted: false};
  }
}

if (typeof module === "object") module.exports = zyingWebProductEdit;
