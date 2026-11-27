// Run inside the already-open My Products > Add Product form. This helper only
// reads or fills the current idless draft; it never saves, submits, or resets it.
// Request: {action: "read"|"preview"|"fill"|"verify", source?: collector.product,
//           expected?: preview.snapshot}. Only fill requires expected.
async function zyingWebNewDraft(request) {
  const route = "#/product/myproduct/productlist";
  const applied = [];
  const attempted = [];
  let targetSource = null;
  const stop = error => { throw Object.assign(new Error(error), {draftError: error}); };
  const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
  const plain = value => value && typeof value === "object" && !Array.isArray(value) &&
    [Object.prototype, null].includes(Object.getPrototypeOf(value));
  // Tagged values preserve undefined and distinguish absent fields from fields
  // with undefined values when the preview travels through JSON.
  const encoded = (value, depth = 0, seen = new Set()) => {
    if (depth > 18) stop("draft_state_unreadable");
    if (value === undefined) return ["undefined"];
    if (value === null) return ["null"];
    if (["string", "boolean"].includes(typeof value)) return [typeof value, value];
    if (typeof value === "number" && Number.isFinite(value)) return ["number", value];
    if ((!plain(value) && !Array.isArray(value)) || seen.has(value)) stop("draft_state_unreadable");
    seen.add(value);
    const result = Array.isArray(value) ? ["array", value.map(item => encoded(item, depth + 1, seen))] :
      ["object", Object.keys(value).sort().map(key => {
        const descriptor = Object.getOwnPropertyDescriptor(value, key);
        if (!own(descriptor, "value")) stop("draft_state_unreadable");
        return [key, encoded(descriptor.value, depth + 1, seen)];
      })];
    seen.delete(value);
    return result;
  };
  const same = (left, right) => JSON.stringify(encoded(left)) === JSON.stringify(encoded(right));
  const bounded = (value, limit, error) => {
    let text;
    try { text = JSON.stringify(encoded(value)); } catch { stop(error); }
    if (text.length > limit) stop(error);
  };
  const clone = value => {
    if (Array.isArray(value)) return value.map(clone);
    if (plain(value)) return Object.fromEntries(Object.keys(value).map(key => [key, clone(value[key])]));
    return value;
  };
  const nonempty = value => value != null && (typeof value === "string" ? value.trim() !== "" :
    Array.isArray(value) ? value.length !== 0 : true);
  const text = (value, limit, error) => {
    if (typeof value !== "string" || !value.trim() || value.length > limit || /[<>\u0000]/.test(value)) stop(error);
    return value;
  };
  const itemId = address => {
    let url;
    try { url = new URL(address); } catch { return null; }
    if (url.protocol !== "https:" || url.username || url.password || url.port || url.search || url.hash ||
        !/^(?:(?:www|m)\.)?aliexpress\.com$/i.test(url.hostname)) return null;
    return url.pathname.match(/^\/(?:item|i)\/(\d{10,24})\.html\/?$/i)?.[1] || null;
  };
  const sourceData = source => {
    if (!plain(source)) stop("invalid_source");
    bounded(source, 200000, "source_too_large_or_invalid");
    if (source.source !== "aliexpress" || typeof source.source_product_id !== "string" ||
        !/^\d{10,24}$/.test(source.source_product_id)) stop("invalid_source_product_id");
    if (typeof source.source_url !== "string" || source.source_url.length > 2000 ||
        itemId(source.source_url) !== source.source_product_id) stop("source_item_mismatch");
    const title = text(source.title, 1000, "invalid_english_title");
    if (!Array.isArray(source.images) || source.images.length > 40) stop("invalid_images");
    const images = [];
    for (const address of source.images) {
      let url;
      try { url = new URL(address); } catch { stop("invalid_image_url"); }
      if (typeof address !== "string" || address.length > 2000 || url.protocol !== "https:" ||
          url.username || url.password || url.port || url.search || url.hash ||
          ![".alicdn.com", ".aliexpress-media.com"].some(suffix => url.hostname.endsWith(suffix)) ||
          images.includes(address)) stop("invalid_image_url");
      images.push(address);
    }
    const description = source.description == null ||
      (typeof source.description === "string" && !source.description.trim()) ? undefined :
      text(source.description, 8000, "invalid_plaintext_description");
    return {title, images, source_url: source.source_url, source_product_id: source.source_product_id, description,
      completeness: {imageCount: images.length, hasDescription: description !== undefined,
        hasCurrency: typeof source.currency === "string" && !!source.currency.trim(),
        variantCount: Array.isArray(source.variants) ? source.variants.length : 0}};
  };
  let mountedTrees = new Map();
  const fibers = node => {
    const key = Object.getOwnPropertyNames(node).find(name => /^__react(?:Fiber|InternalInstance)\$/.test(name));
    const attached = key ? node[key] : null;
    let root = attached;
    for (let depth = 0; root?.return && depth < 128; depth++) root = root.return;
    const currentRoot = root?.stateNode?.current;
    let current = attached;
    let parents = null;
    if (currentRoot) {
      if (!mountedTrees.has(currentRoot)) {
        const members = new Set();
        const parentMap = new Map();
        const pending = [[currentRoot, null]];
        while (pending.length) {
          const [fiber, parent] = pending.pop();
          if (members.has(fiber) || members.size >= 50000) stop("draft_current_fiber_unavailable");
          members.add(fiber);
          parentMap.set(fiber, parent);
          if (fiber.sibling) pending.push([fiber.sibling, parent]);
          if (fiber.child) pending.push([fiber.child, fiber]);
        }
        mountedTrees.set(currentRoot, {members, parents: parentMap});
      }
      const tree = mountedTrees.get(currentRoot);
      const matches = [attached, attached?.alternate].filter(fiber => fiber && tree.members.has(fiber));
      current = unique(matches, "draft_current_fiber_unavailable");
      parents = tree.parents;
    } else if (attached?.alternate) {
      stop("draft_current_fiber_unavailable");
    }
    // React 16 keeps the original DOM fiber key while alternating trees. Walk
    // the mounted HostRoot tree's parent paths, not stale .return pointers.
    const chain = [];
    for (let fiber = current, depth = 0; fiber && depth < 128;
      fiber = parents ? parents.get(fiber) : fiber.return, depth++) chain.push(fiber);
    return chain;
  };
  const unique = (values, error) => {
    const distinct = [...new Set(values)];
    if (distinct.length !== 1) stop(error);
    return distinct[0];
  };
  const observe = () => {
    mountedTrees = new Map();
    if (typeof location !== "object" || location.origin !== "https://erp.zying.net" ||
        location.hash.split("?")[0] !== route) stop("open_zying_web_new_draft");
    const nodes = [...document.querySelectorAll("form")].filter(node =>
      node.querySelector('[contenteditable="true"]') && node.querySelector("#localid"));
    const node = unique(nodes, "new_product_form_not_unique");
    const form = unique(fibers(node).map(fiber => fiber.memoizedProps?.form).filter(value =>
      typeof value?.getFieldsValue === "function" && typeof value?.setFieldsValue === "function"),
    "new_product_form_api_unavailable");
    const editors = [...node.querySelectorAll('[contenteditable="true"]')];
    const detailFiber = unique(editors.flatMap(fibers).filter(fiber =>
      plain(fiber.memoizedProps?.detail) && typeof fiber.memoizedProps?.setDetail === "function"),
    "new_product_detail_not_unique");
    const languages = [];
    for (let hook = detailFiber.memoizedState, depth = 0; hook && depth < 64; hook = hook.next, depth++) {
      if (["en", "es", "pt", "zh"].includes(hook.memoizedState)) languages.push(hook.memoizedState);
    }
    if (unique(languages, "draft_language_unreadable") !== "en") stop("select_english_language");
    const controls = {};
    const visible = {};
    for (const element of [...editors, ...node.querySelectorAll('input[type="file"]')]) {
      const chain = fibers(element);
      const field = chain.find(fiber => typeof fiber.memoizedProps?.fld === "string")?.memoizedProps.fld;
      if (!field) continue;
      const component = chain.find(fiber => ["ContentEditableEX", "MultiUploadEX"].includes(fiber.type?.name) &&
        typeof fiber.memoizedProps?.onChange === "function");
      if (!component) continue;
      if (controls[field]) stop("draft_field_control_not_unique");
      controls[field] = {element, props: component.memoizedProps, name: component.type.name};
      if (component.type.name === "ContentEditableEX") visible[field] = element.textContent;
    }
    if (controls.title?.name !== "ContentEditableEX" || controls.pic?.name !== "MultiUploadEX" ||
        !Array.isArray(controls.pic.props.value)) stop("draft_field_control_unavailable");
    const values = form.getFieldsValue(true);
    const detail = detailFiber.memoizedProps.detail;
    if (!plain(values) || !Array.isArray(values.pic)) stop("draft_state_unreadable");
    for (const record of [values, detail]) {
      for (const key of ["id", "sale_id", "product_id"]) {
        const value = record[key];
        if (value == null || value === "" || value === 0 || value === "0") continue;
        if ((typeof value === "number" && value > 0) || (typeof value === "string" && /^\d+$/.test(value) && /[1-9]/.test(value))) {
          stop("existing_product_rejected");
        }
        stop("draft_identity_unreadable");
      }
    }
    for (const key of ["tLans", "iLans"]) {
      if (detail[key] != null && !plain(detail[key])) stop("draft_language_map_unreadable");
    }
    const state = {form_values: clone(values), detail: clone(detail), visible_text: visible,
      native_values: Object.fromEntries(Object.entries(controls).map(([field, control]) => [field, clone(control.props.value)]))};
    bounded(state, 400000, "draft_state_too_large_or_unreadable");
    const snapshot = {version: 1, route, language: "en", state: JSON.stringify(encoded(state))};
    return {node, form, controls, values, detail, state, snapshot};
  };
  const draft = current => ({id: current.detail.id ?? null, english_title: current.values.title ?? null,
    english_description: current.values.intro ?? null, title_languages: clone(current.detail.tLans ?? {}),
    description_languages: clone(current.detail.iLans ?? {}), source_url: current.values.source ?? null,
    images: [...current.values.pic]});
  const checks = (current, source) => ({
    title: current.values.title === source.title,
    englishTitle: current.detail.tLans?.en === source.title,
    visibleTitle: current.controls.title.element.textContent === source.title,
    nativeTitle: current.controls.title.props.value === source.title,
    images: same(current.values.pic, source.images),
    nativeImages: same(current.controls.pic.props.value, source.images),
    sourceUrl: current.values.source === source.source_url,
    ...(source.description === undefined ? {} : {
      description: current.values.intro === source.description,
      englishDescription: current.detail.iLans?.en === source.description,
      visibleDescription: current.controls.intro?.element.textContent === source.description,
      nativeDescription: current.controls.intro?.props.value === source.description,
    }),
  });
  const fieldChecks = source => [
    ["source", ["sourceUrl"]],
    ["title", ["title", "englishTitle", "visibleTitle", "nativeTitle"]],
    ["pic", ["images", "nativeImages"]],
    ...(source.description === undefined ? [] : [["intro", ["description", "englishDescription", "visibleDescription", "nativeDescription"]]]),
  ];
  const matchingFields = (current, source) => {
    const result = checks(current, source);
    return fieldChecks(source).filter(([, keys]) => keys.every(key => result[key])).map(([field]) => field);
  };
  const suitable = (current, source) => {
    if (source.description !== undefined && current.controls.intro?.name !== "ContentEditableEX") stop("description_control_unavailable");
    const existingSource = current.values.source;
    if (nonempty(existingSource) && (existingSource !== source.source_url || itemId(existingSource) !== source.source_product_id)) {
      stop("new_draft_source_conflict");
    }
    const targets = [
      [current.values.title, source.title], [current.detail.tLans?.en, source.title],
      [current.controls.title.element.textContent, source.title], [current.controls.title.props.value, source.title],
      [current.values.pic, source.images], [current.controls.pic.props.value, source.images],
      ...(source.description === undefined ? [] : [[current.values.intro, source.description],
        [current.detail.iLans?.en, source.description], [current.controls.intro.element.textContent, source.description],
        [current.controls.intro.props.value, source.description]]),
    ];
    if (!nonempty(existingSource) && targets.some(([observed]) => nonempty(observed))) stop("new_draft_not_empty");
    if (targets.some(([observed, wanted]) => nonempty(observed) && !same(observed, wanted))) stop("new_draft_field_conflict");
  };
  const preserved = (before, after, fields, source) => {
    const wanted = {title: source.title, pic: source.images, source: source.source_url, intro: source.description};
    for (const field of fields) {
      const scalarChanged = own(before.detail, field) !== own(after.detail, field) ||
        !same(before.detail[field], after.detail[field]);
      if (scalarChanged && !same(after.detail[field], wanted[field])) return false;
    }
    const strip = state => {
      const copy = clone(state);
      for (const field of fields) {
        delete copy.form_values[field];
        delete copy.visible_text[field];
        delete copy.native_values[field];
        // Native versions may also synchronize the touched scalar on detail.
        // A changed scalar was checked against the requested value above.
        delete copy.detail[field];
        const key = field === "title" ? "tLans" : field === "intro" ? "iLans" : null;
        if (key) {
          const map = {...(copy.detail[key] || {})};
          delete map.en;
          // Adding an English map to an initially absent map is allowed.
          delete copy.detail[key];
          if (Object.keys(map).length) copy.detail[key] = map;
        }
      }
      return copy;
    };
    return same(strip(before), strip(after));
  };
  try {
    if (!plain(request) || Object.keys(request).some(key => !["action", "source", "expected"].includes(key)) ||
        !["read", "preview", "fill", "verify"].includes(request.action)) stop("invalid_request");
    bounded(request, 1000000, "request_too_large_or_invalid");
    const source = targetSource = request.action === "read" && request.source === undefined ? null : sourceData(request.source);
    let current = observe();
    const base = {ok: true, source: "web_new_product_form", scope: "basic_source_fields_only", serverRecordCreated: false,
      ...(source ? {sourceCompleteness: source.completeness} : {})};
    if (request.action === "read") return {...base, stage: "new_draft_read", draft: draft(current), snapshot: current.snapshot};
    if (request.action === "verify") {
      const result = checks(current, source);
      const verified = Object.values(result).every(Boolean);
      return {...base, ok: verified, stage: verified ? "new_draft_verified" : "new_draft_mismatch", verified,
        ...(verified ? {} : {error: "draft_verification_mismatch"}), checks: result, verifiedFields: matchingFields(current, source),
        draft: draft(current), snapshot: current.snapshot};
    }
    suitable(current, source);
    const comparison = [
      {field: "english_title", observed: current.values.title ?? null, wanted: source.title},
      {field: "images", observed: [...current.values.pic], wanted: [...source.images]},
      {field: "source_url", observed: current.values.source ?? null, wanted: source.source_url},
      ...(source.description === undefined ? [] : [{field: "english_description", observed: current.values.intro ?? null, wanted: source.description}]),
    ];
    if (request.action === "preview") return {...base, stage: "new_draft_preview", draft: draft(current),
      comparison, snapshot: current.snapshot, alreadyMatches: Object.values(checks(current, source)).every(Boolean)};
    if (!plain(request.expected) || !same(request.expected, current.snapshot)) stop("expected_snapshot_conflict");
    if (typeof requestAnimationFrame !== "function") stop("animation_frame_unavailable");
    const initialNode = current.node;
    const initialForm = current.form;
    const before = current.state;
    const changed = [];
    const completedChecks = [];
    let previous = current.snapshot;
    const operations = [
      // Establish the exact product identity first so an interrupted import can
      // be previewed again and resumed without clearing its completed fields.
      ["source", () => ["sourceUrl"], () => current.form.setFieldsValue({source: source.source_url})],
      ["title", () => ["title", "englishTitle", "visibleTitle", "nativeTitle"], control => control.props.onChange(source.title)],
      ["pic", () => ["images", "nativeImages"], control => control.props.onChange([...source.images])],
      ...(source.description === undefined ? [] : [["intro", () => ["description", "englishDescription", "visibleDescription", "nativeDescription"],
        control => control.props.onChange(source.description)]]),
    ];
    for (const [field, keys, change] of operations) {
      current = observe();
      if (current.node !== initialNode || current.form !== initialForm || !same(current.snapshot, previous)) stop("draft_changed_during_fill");
      if (keys().every(key => checks(current, source)[key])) {
        completedChecks.push(...keys());
        continue;
      }
      attempted.push(field);
      change(current.controls[field]);
      applied.push(field);
      changed.push(field);
      await new Promise(resolve => requestAnimationFrame(resolve));
      current = observe();
      if (current.node !== initialNode || current.form !== initialForm || !preserved(before, current.state, changed, source)) {
        stop("draft_changed_during_fill");
      }
      completedChecks.push(...keys());
      if (!completedChecks.every(key => checks(current, source)[key])) stop("draft_field_verification_failed");
      previous = current.snapshot;
    }
    const result = {...checks(current, source), otherFieldsPreserved: preserved(before, current.state, changed, source)};
    if (!Object.values(result).every(Boolean)) stop("draft_verification_failed");
    return {...base, stage: applied.length ? "new_draft_filled" : "new_draft_already_matches", verified: true,
      checks: result, draft: draft(current), snapshot: current.snapshot, filledFields: applied,
      attemptedFields: attempted, verifiedFields: matchingFields(current, source),
      pendingFields: ["localid", "en", "weight", "cost", "cur"].filter(key => !nonempty(current.values[key]))};
  } catch (error) {
    const failure = {ok: false, error: error?.draftError || "new_draft_operation_failed", serverRecordCreated: false,
      ...(attempted.length ? {stage: "partial_draft_fill", attemptedFields: attempted} : {})};
    if (targetSource) {
      try {
        const latest = observe();
        const verifiedFields = matchingFields(latest, targetSource);
        let recoverable = true;
        let recoveryError;
        try { suitable(latest, targetSource); }
        catch (reason) { recoverable = false; recoveryError = reason?.draftError || "new_draft_operation_failed"; }
        return {...failure, checks: checks(latest, targetSource), verifiedFields,
          filledFields: applied.filter(field => verifiedFields.includes(field)), draft: draft(latest), snapshot: latest.snapshot,
          recoverable, ...(recoveryError ? {recoveryError} : {})};
      } catch {
        // An unreadable, replaced, or existing-record form is never reused for
        // recovery. Preserve the original failure and leave the draft as found.
      }
    }
    return failure;
  }
}

if (typeof module === "object") module.exports = zyingWebNewDraft;
