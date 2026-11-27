const assert = require("node:assert/strict");
const test = require("node:test");
const zyingWebNewDraft = require("../scripts/zying_web_new_draft.js");

const source = {
  source: "aliexpress", source_product_id: "1005013209445272",
  source_url: "https://www.aliexpress.com/item/1005013209445272.html",
  title: "Black nitrile O-ring kit", images: ["https://ae-pic-a1.aliexpress-media.com/kf/rings.jpg"],
  description: null,
};
const copy = value => structuredClone(value);

// This small DOM/React model represents the observed browser interface. Its
// callbacks update the form store immediately, but publish captured parent
// detail and control props on the next frame, as the native React form does.
// A fresh callback must therefore be discovered after each frame.
function page(options = {}) {
  let store = {stat: 1000, flag: 0, level: 10, grade: 8, pic: [], ...copy(options.values || {})};
  let detail = {tLans: {zh: "中文标题"}, iLans: {fr: "Texte français"}, ...copy(options.detail || {})};
  let pictures = copy(options.nativePictures || store.pic);
  const languages = options.languages || ["en", ""];
  const pending = [];
  const mutations = [];
  const rootState = {current: null};
  const originalFibers = new Map();
  let imageFailures = options.failImageChanges || 0;
  const fieldNames = ["title", "brief", "keys", "bullet", "intro"];
  const editors = fieldNames.map(field => ({field, textContent: store[field] || ""}));
  const upload = {field: "pic"};
  const localid = {};
  const fiberKey = options.fiberKey || "__reactInternalInstance$fixture";
  const formApi = {
    getFieldsValue(all) { assert.equal(all, true); return copy(store); },
    setFieldsValue(values) {
      mutations.push({kind: "setFieldsValue", values: copy(values)});
      Object.assign(store, values);
      pending.push(() => { if (options.updateDetailScalars) Object.assign(detail, values); });
    },
    submit() { assert.fail("Draft helper attempted submit"); },
    resetFields() { assert.fail("Draft helper attempted reset"); },
  };
  const formNode = {
    querySelector(selector) {
      if (selector === '#localid') return options.missingLocalid ? null : localid;
      if (selector === '[contenteditable="true"]') return editors[0];
      assert.fail(`Unexpected selector ${selector}`);
    },
    querySelectorAll(selector) {
      if (selector === '[contenteditable="true"]') return options.missingIntro ? editors.slice(0, 4) : editors;
      if (selector === 'input[type="file"]') return options.missingUpload ? [] : [upload];
      assert.fail(`Unexpected selector ${selector}`);
    },
  };
  function Et() {}
  function ContentEditableEX() {}
  function MultiUploadEX() {}
  const hooks = values => values.reduceRight((next, memoizedState) => ({memoizedState, next}), null);
  const bind = (element, fiber) => {
    if (options.staleDomFibers && originalFibers.has(element)) {
      const original = originalFibers.get(element);
      original.alternate = fiber;
      fiber.alternate = original;
      element[fiberKey] = original;
    } else {
      originalFibers.set(element, fiber);
      element[fiberKey] = fiber;
    }
  };
  const render = () => {
    const capturedDetail = copy(detail);
    const root = {tag: 3, stateNode: rootState, return: null};
    const formParent = {memoizedProps: {form: formApi}, return: root};
    const hostForm = {memoizedProps: {}, return: formParent};
    const parent = {type: Et, memoizedProps: {detail: capturedDetail, setDetail: next => { detail = next; }},
      memoizedState: hooks([0, {}, ...languages]), return: hostForm};
    root.child = formParent;
    formParent.child = hostForm;
    hostForm.child = parent;
    rootState.current = root;
    bind(formNode, hostForm);
    const children = [];
    for (const element of editors) {
      const field = element.field;
      element.textContent = store[field] || "";
      const onChange = text => {
        mutations.push({kind: "nativeText", field, value: text});
        store[field] = text;
        pending.push(() => {
          if (field === "title" || field === "intro") {
            const map = field === "title" ? "tLans" : "iLans";
            detail = {...capturedDetail, [map]: {...(capturedDetail[map] || {}), en: text}};
            if (options.updateDetailScalars) detail[field] = text;
          }
          if (options.breakTitleSync && field === "title") delete detail.tLans.en;
        });
      };
      const wrapper = {memoizedProps: {fld: field}, return: parent};
      const component = {type: ContentEditableEX, memoizedProps: {value: store[field], onChange}, return: wrapper};
      const host = {memoizedProps: {}, return: component};
      wrapper.child = component;
      component.child = host;
      children.push(wrapper);
      bind(element, host);
    }
    const uploadComponent = {type: MultiUploadEX,
      memoizedProps: {fld: "pic", value: options.changedUploadValue ? "changed control" : copy(pictures),
        onChange: urls => {
          mutations.push({kind: "nativeImages", value: copy(urls)});
          if (imageFailures > 0) { imageFailures--; throw new Error("Native image callback failed"); }
          store.pic = copy(urls);
          pending.push(() => {
            pictures = copy(urls);
            if (options.updateDetailScalars) detail.pic = copy(urls);
          });
        }}, return: parent};
    const uploadHost = {memoizedProps: {}, return: uploadComponent};
    uploadComponent.child = uploadHost;
    children.push(uploadComponent);
    parent.child = children[0];
    for (let index = 0; index < children.length - 1; index++) children[index].sibling = children[index + 1];
    bind(upload, uploadHost);
  };
  render();
  global.location = {origin: "https://erp.zying.net", hash: "#/product/myproduct/productlist"};
  global.document = {querySelectorAll(selector) {
    assert.equal(selector, "form");
    const irrelevantSearchForm = {querySelector: () => null};
    return options.missingForm ? [irrelevantSearchForm] : [irrelevantSearchForm, formNode,
      ...(options.duplicateForm ? [{...formNode}] : [])];
  }};
  global.requestAnimationFrame = callback => queueMicrotask(() => {
    while (pending.length) pending.shift()();
    if (options.onFrame) options.onFrame({store, detail, mutations});
    render();
    callback(0);
  });
  global.fetch = () => assert.fail("Draft helper attempted a network call");
  global.XMLHttpRequest = class { constructor() { assert.fail("Draft helper attempted a network call"); } };
  return {mutations, read: () => ({store: copy(store), detail: copy(detail), pictures: copy(pictures)}),
    change: values => { Object.assign(store, values); render(); },
    changeDetail: values => { Object.assign(detail, values); render(); }};
}

async function preview(data = source) {
  const result = await zyingWebNewDraft({action: "preview", source: data});
  assert.equal(result.ok, true, JSON.stringify(result));
  return result;
}

test("read and preview are read-only and preserve an exact JSON-roundtrip snapshot", async () => {
  const current = page({values: {weight: undefined, cost: "2.50"}});
  const before = current.read();
  const result = await preview();
  assert.equal(result.serverRecordCreated, false);
  assert.equal(result.alreadyMatches, false);
  assert.equal(result.scope, "basic_source_fields_only");
  assert.deepEqual(result.sourceCompleteness, {imageCount: 1, hasDescription: false, hasCurrency: false, variantCount: 0});
  const read = await zyingWebNewDraft({action: "read"});
  assert.deepEqual(read.snapshot, JSON.parse(JSON.stringify(result.snapshot)));
  assert.deepEqual(current.read(), before);
  assert.deepEqual(current.mutations, []);
});

test("native fill synchronizes displayed text, form store, maps, and image state while preserving other values", async () => {
  const current = page({updateDetailScalars: true, staleDomFibers: true,
    values: {weight: "31", cost: "2.50", cur: "USD", localid: 77, en: "Kit", brief: "Keep brief"},
    detail: {custom: {keep: [1, 2], a: {b: {c: {d: {e: "preserve"}}}}},
      tLans: {zh: "中文标题", pt: "Título"}, iLans: {fr: "Conserver"}}});
  const before = current.read();
  const data = {...source, description: "Nitrile rings for faucet and hydraulic repairs.\nKeep in a dry place."};
  const result = await preview(data);
  const filled = await zyingWebNewDraft({action: "fill", source: data, expected: JSON.parse(JSON.stringify(result.snapshot))});
  assert.equal(filled.ok, true, JSON.stringify(filled));
  assert.equal(filled.verified, true);
  assert.deepEqual(filled.filledFields, ["source", "title", "pic", "intro"]);
  assert.deepEqual(filled.verifiedFields, ["source", "title", "pic", "intro"]);
  assert.deepEqual(filled.pendingFields, []);
  const after = current.read();
  assert.deepEqual(after.detail.tLans, {...before.detail.tLans, en: data.title});
  assert.deepEqual(after.detail.iLans, {...before.detail.iLans, en: data.description});
  assert.deepEqual(after.detail.custom, before.detail.custom);
  assert.equal(after.detail.title, data.title);
  assert.equal(after.detail.intro, data.description);
  assert.equal(after.detail.source, data.source_url);
  assert.deepEqual(after.detail.pic, data.images);
  for (const field of ["stat", "flag", "level", "grade", "weight", "cost", "cur", "localid", "en", "brief"]) {
    assert.deepEqual(after.store[field], before.store[field]);
  }
  assert.deepEqual(after.pictures, data.images);
  assert.deepEqual(current.mutations.map(item => item.kind), ["setFieldsValue", "nativeText", "nativeImages", "nativeText"]);
  const verified = await zyingWebNewDraft({action: "verify", source: data});
  assert.equal(verified.verified, true);
  assert.ok(Object.values(verified.checks).every(Boolean));
});

test("null, absent, and blank descriptions preserve existing descriptions and their full language maps", async () => {
  for (const description of [null, undefined, "", "   \n"]) {
    const current = page({values: {intro: "Existing English description"},
      detail: {iLans: {en: "Existing English description", zh: "保留"}}});
    const before = current.read();
    const data = {...source, description};
    const result = await preview(data);
    const filled = await zyingWebNewDraft({action: "fill", source: data, expected: result.snapshot});
    assert.equal(filled.ok, true, JSON.stringify(filled));
    assert.equal(current.read().store.intro, before.store.intro);
    assert.deepEqual(current.read().detail.iLans, before.detail.iLans);
    assert.ok(current.mutations.every(item => item.field !== "intro"));
  }
});

test("an already matching idless draft can be previewed, filled, and verified without mutation", async () => {
  const current = page({fiberKey: "__reactFiber$fixture", values: {title: source.title, source: source.source_url, pic: source.images},
    detail: {tLans: {en: source.title, zh: "保留"}}});
  const result = await preview();
  assert.equal(result.alreadyMatches, true);
  const filled = await zyingWebNewDraft({action: "fill", source, expected: result.snapshot});
  assert.equal(filled.stage, "new_draft_already_matches");
  assert.equal((await zyingWebNewDraft({action: "read"})).ok, true);
  assert.equal((await zyingWebNewDraft({action: "verify", source})).verified, true);
  assert.deepEqual(current.mutations, []);
});

test("wrong source identity, unsafe images, markup, and oversized data reject before any mutation", async () => {
  const cases = [
    [{...source, source_product_id: "1005013209445273"}, "source_item_mismatch"],
    [{...source, source_url: "http://www.aliexpress.com/item/1005013209445272.html"}, "source_item_mismatch"],
    [{...source, source_url: "https://www.aliexpress.com.evil.test/item/1005013209445272.html"}, "source_item_mismatch"],
    [{...source, images: ["https://aliexpress-media.com.evil.test/ring.jpg"]}, "invalid_image_url"],
    [{...source, images: ["https://user:secret@ae-pic-a1.aliexpress-media.com/ring.jpg"]}, "invalid_image_url"],
    [{...source, images: ["javascript:alert(1)"]}, "invalid_image_url"],
    [{...source, images: [source.images[0], source.images[0]]}, "invalid_image_url"],
    [{...source, description: "<img src=x onerror=alert(1)>"}, "invalid_plaintext_description"],
    [{...source, title: "x".repeat(1001)}, "invalid_english_title"],
    [{...source, ignoredMetadata: "x".repeat(210000)}, "source_too_large_or_invalid"],
  ];
  for (const [data, error] of cases) {
    const current = page();
    assert.equal((await zyingWebNewDraft({action: "preview", source: data})).error, error);
    assert.deepEqual(current.mutations, []);
  }
});

test("wrong routes, missing or ambiguous forms, positive identities, and changed controls fail closed", async () => {
  const cases = [
    [{missingForm: true}, "new_product_form_not_unique"],
    [{missingLocalid: true}, "new_product_form_not_unique"],
    [{duplicateForm: true}, "new_product_form_not_unique"],
    [{missingUpload: true}, "draft_field_control_unavailable"],
    [{changedUploadValue: true}, "draft_field_control_unavailable"],
    [{detail: {id: 23}}, "existing_product_rejected"],
    [{values: {id: "23"}}, "existing_product_rejected"],
    [{detail: {sale_id: "100001"}}, "existing_product_rejected"],
    [{languages: ["zh", ""]}, "select_english_language"],
    [{languages: ["en", "es"]}, "draft_language_unreadable"],
    [{languages: ["", "unknown"]}, "draft_language_unreadable"],
  ];
  for (const [options, error] of cases) {
    const current = page(options);
    assert.equal((await zyingWebNewDraft({action: "preview", source})).error, error);
    assert.deepEqual(current.mutations, []);
  }
  for (const location of [{origin: "https://evil.test", hash: "#/product/myproduct/productlist"},
    {origin: "https://erp.zying.net", hash: "#/product/1688/collectionlist"}]) {
    const current = page();
    global.location = location;
    assert.equal((await zyingWebNewDraft({action: "preview", source})).error, "open_zying_web_new_draft");
    assert.deepEqual(current.mutations, []);
  }
  // The stale DOM fiber's old identity must never drive a read or a callback.
  for (const [oldId, currentId, expected] of [[23, undefined, null], [undefined, 23, "existing_product_rejected"]]) {
    const current = page({staleDomFibers: true, detail: {id: oldId}});
    current.changeDetail({id: currentId});
    const result = await zyingWebNewDraft({action: "preview", source});
    if (expected === null) assert.equal(result.ok, true, JSON.stringify(result));
    else assert.equal(result.error, expected);
    assert.deepEqual(current.mutations, []);
  }
});

test("a nonempty unrelated draft and mismatched content in the same source draft cannot be overwritten", async () => {
  const cases = [
    [{title: "Keep this draft"}, {}, "new_draft_not_empty"],
    [{pic: source.images}, {}, "new_draft_not_empty"],
    [{source: "https://www.aliexpress.com/item/1005013209445273.html"}, {}, "new_draft_source_conflict"],
    [{source: source.source_url, title: "Custom edited title"}, {}, "new_draft_field_conflict"],
    [{source: source.source_url}, {tLans: {en: "Different English title"}}, "new_draft_field_conflict"],
  ];
  for (const [values, detail, error] of cases) {
    const current = page({values, detail});
    const before = current.read();
    assert.equal((await zyingWebNewDraft({action: "preview", source})).error, error);
    assert.deepEqual(current.read(), before);
    assert.deepEqual(current.mutations, []);
  }
});

test("fill requires the exact preview and catches even undefined-field or other-language conflicts", async () => {
  const current = page({values: {weight: undefined}});
  const result = await preview();
  assert.equal((await zyingWebNewDraft({action: "fill", source})).error, "expected_snapshot_conflict");
  current.change({weight: "50"});
  assert.equal((await zyingWebNewDraft({action: "fill", source, expected: result.snapshot})).error, "expected_snapshot_conflict");
  current.change({weight: undefined});
  current.changeDetail({tLans: {zh: "已修改"}});
  assert.equal((await zyingWebNewDraft({action: "fill", source, expected: result.snapshot})).error, "expected_snapshot_conflict");
  assert.deepEqual(current.mutations, []);
});

test("a concurrent user edit stops further fields without rolling back the native change", async () => {
  let edited = false;
  const current = page({onFrame({store}) { if (!edited) { edited = true; store.cost = "User entered cost"; } }});
  const result = await preview();
  const filled = await zyingWebNewDraft({action: "fill", source, expected: result.snapshot});
  assert.equal(filled.error, "draft_changed_during_fill");
  assert.equal(filled.stage, "partial_draft_fill");
  assert.deepEqual(filled.filledFields, ["source"]);
  assert.deepEqual(filled.verifiedFields, ["source"]);
  assert.deepEqual(filled.attemptedFields, ["source"]);
  assert.equal(filled.recoverable, true);
  assert.deepEqual(filled.snapshot, (await zyingWebNewDraft({action: "read"})).snapshot);
  assert.equal(current.read().store.cost, "User entered cost");
  assert.equal(current.read().store.source, source.source_url);
  assert.deepEqual(current.mutations.map(item => item.kind), ["setFieldsValue"]);
});

test("native callback synchronization failures are visible and stop before subsequent fields", async () => {
  const current = page({breakTitleSync: true});
  const result = await preview();
  const filled = await zyingWebNewDraft({action: "fill", source, expected: result.snapshot});
  assert.equal(filled.error, "draft_field_verification_failed");
  const verified = await zyingWebNewDraft({action: "verify", source});
  assert.equal(verified.verified, false);
  assert.equal(verified.ok, false);
  assert.equal(verified.stage, "new_draft_mismatch");
  assert.equal(filled.recoverable, true);
  assert.deepEqual(filled.verifiedFields, ["source"]);
  assert.equal(current.read().store.source, source.source_url);
  assert.deepEqual(current.mutations.map(item => item.kind), ["setFieldsValue", "nativeText"]);
});

test("editing an earlier filled title during the image frame stops before the description and disables recovery", async () => {
  let frame = 0;
  const current = page({onFrame({store, detail}) {
    frame++;
    if (frame === 3) { store.title = "User changed title"; detail.tLans.en = store.title; }
  }});
  const data = {...source, description: "Plain description"};
  const result = await preview(data);
  const filled = await zyingWebNewDraft({action: "fill", source: data, expected: result.snapshot});
  assert.equal(filled.error, "draft_field_verification_failed");
  assert.equal(current.read().store.title, "User changed title");
  assert.equal(current.read().store.source, source.source_url);
  assert.equal(current.read().store.intro, undefined);
  assert.equal(filled.recoverable, false);
  assert.equal(filled.recoveryError, "new_draft_field_conflict");
  assert.deepEqual(filled.verifiedFields, ["source", "pic"]);
  assert.deepEqual(current.mutations.map(item => item.kind), ["setFieldsValue", "nativeText", "nativeImages"]);
});

test("an interrupted same-product fill resumes from a fresh preview and preserves unrelated user edits", async () => {
  const current = page({failImageChanges: 1, staleDomFibers: true,
    values: {cost: "2.50", brief: "Keep original brief"}, detail: {custom: {preserve: true}}});
  const before = current.read();
  const first = await preview();
  const failed = await zyingWebNewDraft({action: "fill", source, expected: first.snapshot});
  assert.equal(failed.ok, false);
  assert.equal(failed.stage, "partial_draft_fill");
  assert.deepEqual(failed.attemptedFields, ["source", "title", "pic"]);
  assert.deepEqual(failed.verifiedFields, ["source", "title"]);
  assert.deepEqual(failed.filledFields, ["source", "title"]);
  assert.equal(failed.recoverable, true);
  assert.equal(failed.draft.source_url, source.source_url);
  assert.equal(failed.draft.english_title, source.title);
  assert.deepEqual(failed.draft.images, []);
  assert.deepEqual(failed.snapshot, (await zyingWebNewDraft({action: "read"})).snapshot);
  current.change({cost: "3.75", brief: "User kept this text"});
  current.changeDetail({tLans: {en: source.title, zh: "用户补充"}});
  const edited = current.read();
  const mutationsBeforeRetry = current.mutations.length;
  assert.equal((await zyingWebNewDraft({action: "fill", source, expected: first.snapshot})).error, "expected_snapshot_conflict");
  assert.equal(current.mutations.length, mutationsBeforeRetry);
  const read = await zyingWebNewDraft({action: "read", source});
  const second = await preview();
  assert.deepEqual(second.snapshot, read.snapshot);
  const completed = await zyingWebNewDraft({action: "fill", source, expected: second.snapshot});
  assert.equal(completed.ok, true, JSON.stringify(completed));
  assert.deepEqual(completed.attemptedFields, ["pic"]);
  assert.deepEqual(completed.filledFields, ["pic"]);
  assert.deepEqual(completed.verifiedFields, ["source", "title", "pic"]);
  assert.equal(current.read().store.cost, edited.store.cost);
  assert.equal(current.read().store.brief, edited.store.brief);
  assert.deepEqual(current.read().detail.tLans, edited.detail.tLans);
  assert.deepEqual(current.read().detail.custom, before.detail.custom);
  assert.equal((await zyingWebNewDraft({action: "verify", source})).verified, true);
  assert.deepEqual(current.mutations.slice(mutationsBeforeRetry), [{kind: "nativeImages", value: source.images}]);
  const wrongSource = {...source, source_product_id: "1005013209445273",
    source_url: "https://www.aliexpress.com/item/1005013209445273.html"};
  const rejected = await zyingWebNewDraft({action: "preview", source: wrongSource});
  assert.equal(rejected.error, "new_draft_source_conflict");
  assert.equal(rejected.recoverable, false);
});

test("unverified description controls and request mutations are rejected", async () => {
  const current = page({missingIntro: true});
  assert.equal((await zyingWebNewDraft({action: "preview", source: {...source, description: "Plain description"}})).error,
    "description_control_unavailable");
  for (const request of [{action: "save", source}, {action: "fill", source, submit: true},
    {action: "preview", source, changes: {cost: "5"}}]) {
    assert.equal((await zyingWebNewDraft(request)).error, "invalid_request");
  }
  assert.deepEqual(current.mutations, []);
});
