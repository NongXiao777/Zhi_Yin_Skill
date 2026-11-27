const assert = require("node:assert/strict");
const test = require("node:test");
const zyingWebCollection = require("../scripts/zying_web_collection.js");

global.location = {origin: "https://erp.zying.net", hash: "#/product/1688/collectionlist"};

const row = {
  sale_id: 1001,
  sale_title: '{"en":"Old title","zh":"中文"}',
  sale_intro: {en: "Old intro", fr: "Texte"},
  sale_stock: '[{"key":"A / 24V","money":1.44},{"key":"B / 12V","num":5}]',
};
const mockRead = record => async id => {
  assert.equal(id, 1001);
  return {root: [record]};
};

test("web preview uses exact variant keys and normalizes absolute decimal values", async () => {
  const changes = {english_title: "New title", surcharges: [{key: "B / 12V", value: "0.0100"}]};
  const preview = await zyingWebCollection({action: "preview", product_id: 1001, changes}, mockRead(row));
  assert.deepEqual(preview.comparison, [
    {field: "english_title", observed: "Old title", wanted: "New title"},
    {field: "surcharge", variant_key: "B / 12V", observed: "0", wanted: "0.01"},
  ]);
});

test("web verification requires a matching identity and all target values", async () => {
  const request = {action: "verify", product_id: "1001", changes: {
    english_description: "New intro", surcharges: [{key: "A / 24V", value: "2.00"}],
  }};
  assert.equal((await zyingWebCollection(request, mockRead(row))).verified, false);
  assert.equal((await zyingWebCollection(request, mockRead({...row, sale_id: 1002}))).error, "unexpected_product");
  const complete = {...row, sale_intro: '{"en":"New intro","fr":"Texte"}',
    sale_stock: [{key: "A / 24V", money: "2"}, {key: "B / 12V", num: 5}]};
  assert.equal((await zyingWebCollection(request, mockRead(complete))).verified, true);
});

test("wrong routes and ambiguous variants stop before a usable preview", async () => {
  const request = {action: "preview", product_id: 1001,
    changes: {surcharges: [{key: "A / 24V", value: 2}]}};
  const duplicate = {...row, sale_stock: [{key: "A / 24V"}, {key: "A / 24V"}]};
  assert.equal((await zyingWebCollection(request, mockRead(duplicate))).error, "variant_not_unique_or_unreadable");
  global.location.hash = "#/product/myproduct";
  try {
    const result = await zyingWebCollection(request, () => assert.fail("Unexpected product call"));
    assert.equal(result.error, "open_zying_web_collection");
  } finally {
    global.location.hash = "#/product/1688/collectionlist";
  }
});
