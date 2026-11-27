async function zyingWebCollection(request, testReadDetail) {
  const failure = error => ({ok: false, error});
  if (location.origin !== "https://erp.zying.net" ||
      location.hash.split("?")[0] !== "#/product/1688/collectionlist") {
    return failure("open_zying_web_collection");
  }

  const idText = String(request?.product_id ?? "");
  const id = /^[1-9][0-9]{0,9}$/.test(idText) ? Number(idText) : 0;
  if (id === 0 || id > 2147483647) return failure("invalid_product_id");
  if (!["read", "preview", "verify"].includes(request.action)) return failure("invalid_action");

  const parsing = value => {
    try {
      return typeof value === "string" ? JSON.parse(value) : value;
    } catch {
      return null;
    }
  };
  const english = value => {
    const map = parsing(value);
    return typeof map?.en === "string" ? map.en : null;
  };
  const decimal = value => {
    const match = /^(0|[1-9][0-9]{0,9})(?:\.([0-9]{1,6}))?$/.exec(String(value));
    if (!match) return null;
    const fraction = (match[2] || "").replace(/0+$/, "");
    return match[1] + (fraction ? "." + fraction : "");
  };

  let readDetail = testReadDetail;
  if (!readDetail) {
    const entries = performance.getEntriesByType("resource").map(entry => new URL(entry.name));
    const assets = [...new Set(entries.filter(url => url.origin === location.origin &&
      /^\/assets\/ProductApi-[\w-]+\.js$/.test(url.pathname)).map(url => url.href))];
    if (assets.length !== 1) return failure("web_product_module_unavailable");
    try {
      const {P: productApi} = await import(assets[0]);
      if (typeof productApi?.handleProduct !== "function") return failure("web_product_module_changed");
      readDetail = productId => productApi.handleProduct("spider", "detail", {id: productId});
    } catch {
      return failure("web_product_module_unavailable");
    }
  }

  let detail;
  try {
    detail = await readDetail(id);
  } catch {
    return failure("web_detail_unavailable");
  }
  if (!Array.isArray(detail?.root) || detail.root.length !== 1) return failure("product_not_found");
  const record = detail.root[0];
  if (String(record?.sale_id) !== idText) return failure("unexpected_product");

  const stock = parsing(record.sale_stock);
  const variants = Array.isArray(stock) ? stock.filter(row => typeof row?.key === "string" && row.key)
    .map(row => ({key: row.key, surcharge: decimal(row.money ?? 0)})) : [];
  const copy = {
    english_title: english(record.sale_title),
    english_description: english(record.sale_intro),
  };
  const result = {ok: true, source: "web_spider_detail", product_id: id, copy};
  if (request.action === "read") {
    const limit = request.limit ?? 10;
    if (!Number.isInteger(limit) || limit < 1 || limit > 50) return failure("invalid_limit");
    return {...result, total_variants: variants.length, variants: variants.slice(0, limit)};
  }

  const changes = request.changes;
  if (!changes || typeof changes !== "object" || Array.isArray(changes) ||
      Object.keys(changes).some(key => !(key in copy) && key !== "surcharges")) {
    return failure("invalid_changes");
  }

  const comparison = [];
  for (const field of Object.keys(copy)) {
    if (!Object.hasOwn(changes, field)) continue;
    const wanted = changes[field];
    if (typeof wanted !== "string" || !wanted.trim() || wanted.length > 10000) {
      return failure("invalid_english_copy");
    }
    comparison.push({field, observed: copy[field], wanted});
  }

  if (Object.hasOwn(changes, "surcharges")) {
    if (!Array.isArray(changes.surcharges) || !changes.surcharges.length || changes.surcharges.length > 50) {
      return failure("invalid_surcharges");
    }
    const seen = new Set();
    for (const item of changes.surcharges) {
      if (typeof item?.key !== "string" || !item.key || seen.has(item.key)) {
        return failure("invalid_variant_key");
      }
      seen.add(item.key);
      const wanted = decimal(item.value);
      if (wanted === null) return failure("invalid_surcharge");
      const matched = variants.filter(row => row.key === item.key);
      if (matched.length !== 1 || matched[0].surcharge === null) return failure("variant_not_unique_or_unreadable");
      comparison.push({field: "surcharge", variant_key: item.key, observed: matched[0].surcharge, wanted});
    }
  }
  if (!comparison.length) return failure("empty_changes");

  if (request.action === "verify") {
    return {...result, verified: comparison.every(field => field.observed === field.wanted), comparison};
  }
  return {...result, comparison};
}

if (typeof module === "object") module.exports = zyingWebCollection;
