import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import browser_call


SOURCE = {"source": "aliexpress", "source_product_id": "1005013209445272",
          "source_url": "https://www.aliexpress.com/item/1005013209445272.html",
          "title": "An O-ring kit", "images": ["https://ae-pic-a1.aliexpress-media.com/kf/rings.jpg"]}
DRAFT_SNAPSHOT = {"version": 1, "route": "#/product/myproduct/productlist", "language": "en", "state": "[]"}
PRODUCT_SNAPSHOT = {"version": 1, "source": "sale", "product_id": 123,
                    "route": "#/product/myproduct/productlist", "state": "[]"}
CREATE_SNAPSHOT = {"version": 1, "origin": "https://erp.zying.net", "route": "#/product/1688/collectionlist",
                   "marker": "exact-preview-marker", "state": "[]"}
CREATE_METADATA = {"category_id": 123, "english_short": "ORING", "weight_g": "150", "cost": "3.25", "currency": "USD"}
NODE = shutil.which("node")
if NODE is None:
    bundled_node = Path(sys.executable).resolve().parents[1] / "node" / "bin" / ("node.exe" if os.name == "nt" else "node")
    NODE = str(bundled_node) if bundled_node.is_file() else None


class BrowserCallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="browser-call-test-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)

    def json_file(self, name, value):
        path = self.folder / name
        path.write_text(json.dumps(value, ensure_ascii=True), encoding="utf-8")
        return path

    def assert_error(self, code, function, *args, **kwargs):
        with self.assertRaises(browser_call.BrowserCallError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def stub_helpers(self):
        folder = self.folder / "helpers"
        folder.mkdir()
        for helper, (filename, function) in browser_call.HELPERS.items():
            parameters = "" if helper == "collect" else "request"
            result = "{ok:true,called:true}" if helper == "collect" else "request"
            (folder / filename).write_text("function " + function + "(" + parameters + ") { return " + result +
                                           "; }\nif (typeof module === \"object\") module.exports = " + function + ";\n",
                                           encoding="utf-8")
        return folder

    def test_collect_defaults_to_current_page_and_canonicalizes_links(self):
        self.assertEqual(browser_call.build_request("collect"), {})
        expected = {"target_url": SOURCE["source_url"], "source_product_id": SOURCE["source_product_id"]}
        for host in ("aliexpress.com", "www.aliexpress.com", "m.aliexpress.com", "WWW.ALIEXPRESS.COM"):
            with self.subTest(host=host):
                url = "https://" + host + "/i/" + SOURCE["source_product_id"] + ".html/?tracking=one#details"
                self.assertEqual(browser_call.build_request("collect", url=url), expected)
        path = self.json_file("collect.json", {"source_product_id": SOURCE["source_product_id"]})
        self.assertEqual(browser_call.build_request("collect", request_file=path), expected)

    def test_collect_rejects_deceptive_hosts_credentials_and_non_item_urls(self):
        for url in ("http://www.aliexpress.com/item/1005013209445272.html",
                    "https://aliexpress.com.evil.test/item/1005013209445272.html",
                    "https://evil.test@aliexpress.com/item/1005013209445272.html",
                    "https://www.aliexpress.com:443/item/1005013209445272.html",
                    "https://www.aliexpress.com./item/1005013209445272.html",
                    "https://shop.aliexpress.com/item/1005013209445272.html",
                    "https://www.aliexpress.com/item/123.html",
                    "https://www.aliexpress.com/item/%31%30%30%35%30%31%33%32%30%39%34%34%35%32%37%32.html",
                    "https://www.aliexpress.com\n/item/1005013209445272.html",
                    "https://www.aliexpress.com\\@evil.test/item/1005013209445272.html"):
            with self.subTest(url=url):
                self.assert_error("invalid_aliexpress_url", browser_call.build_request, "collect", url=url)
        path = self.json_file("conflict.json", {"source_product_id": "1005013209445273"})
        self.assert_error("conflicting_input", browser_call.build_request, "collect", request_file=path, url=SOURCE["source_url"])

    def test_new_draft_source_raw_and_successful_wrapper_and_fill_preview(self):
        for value in (SOURCE, {"ok": True, "product": SOURCE}):
            with self.subTest(wrapper="product" in value):
                path = self.json_file("source.json", value)
                request = browser_call.build_request("new-draft", action="preview", source_file=path)
                self.assertEqual(request, {"action": "preview", "source": SOURCE})
        preview = self.json_file("preview.json", {"ok": True, "stage": "new_draft_preview", "snapshot": DRAFT_SNAPSHOT})
        request = browser_call.build_request("new-draft", action="fill", source_file=path, preview_file=preview)
        self.assertEqual(request["expected"], DRAFT_SNAPSHOT)
        self.assertEqual(browser_call.build_request("new-draft", action="read"), {"action": "read"})
        self.assertEqual(browser_call.build_request("new-draft", action="verify", source_file=path)["action"], "verify")

    def test_new_draft_errors_are_detected_before_output(self):
        source = self.json_file("source.json", SOURCE)
        self.assert_error("expected_required", browser_call.build_request, "new-draft", action="fill", source_file=source)
        self.assert_error("source_required", browser_call.build_request, "new-draft", action="preview")
        failed_source = self.json_file("failed-source.json", {"ok": False, "product": SOURCE})
        self.assert_error("invalid_source_file", browser_call.build_request, "new-draft", action="preview", source_file=failed_source)
        request_file = self.json_file("request.json", {"action": "read"})
        self.assert_error("conflicting_input", browser_call.build_request, "new-draft", request_file=request_file, action="preview")
        for value, error in (({"ok": False, "stage": "new_draft_preview", "snapshot": DRAFT_SNAPSHOT}, "invalid_preview"),
                             ({"ok": True, "stage": "new_draft_read", "snapshot": DRAFT_SNAPSHOT}, "invalid_preview"),
                             ({"ok": True, "stage": "new_draft_preview"}, "invalid_preview_snapshot")):
            preview = self.json_file("bad-preview.json", value)
            self.assert_error(error, browser_call.build_request, "new-draft", action="fill", source_file=source, preview_file=preview)
        self.assert_error("preview_not_applicable", browser_call.build_request, "new-draft", action="preview", source_file=source, preview_file=preview)

    def test_product_preview_is_bound_to_source_and_id_and_exact_snapshot(self):
        changes = {"english_title": "Cable fitting", "english_brief": "For a panel opening",
                   "english_keys": "cord entry", "english_bullet": "Mounting body\nLocknut",
                   "english_description": "A cable mounting fitting.", "surcharges": [{"key": "sku-1", "value": "1.50"}]}
        preview = self.json_file("product-preview.json", {"ok": True, "stage": "product_edit_preview", "snapshot": PRODUCT_SNAPSHOT})
        for action in ("apply", "verify"):
            with self.subTest(action=action):
                path = self.json_file("product-request.json", {"action": action, "source": "sale", "product_id": 123, "changes": changes})
                request = browser_call.build_request("product-edit", request_file=path, preview_file=preview)
                self.assertEqual(request["expected"], PRODUCT_SNAPSHOT)
                self.assertEqual(request["changes"], changes)
        path = self.json_file("wrong-product.json", {"action": "apply", "source": "spider", "product_id": 123, "changes": changes})
        self.assert_error("preview_product_mismatch", browser_call.build_request, "product-edit", request_file=path, preview_file=preview)
        path = self.json_file("conflicting-snapshot.json", {"action": "apply", "source": "sale", "product_id": 123,
                                                           "changes": changes, "expected": {**PRODUCT_SNAPSHOT, "state": "different"}})
        self.assert_error("conflicting_input", browser_call.build_request, "product-edit", request_file=path, preview_file=preview)

    def test_product_request_rejects_bad_ids_types_and_missing_file(self):
        self.assert_error("request_file_required", browser_call.build_request, "product-edit")
        for value, code in (({"action": []}, "invalid_action"), ({"source": []}, "invalid_product_source"),
                            ({"product_id": True}, "invalid_product_id"), ({"product_id": "123"}, "invalid_product_id"),
                            ({"product_id": 2147483648}, "invalid_product_id"), ({"limit": 0}, "invalid_limit")):
            path = self.json_file("bad-request.json", {"action": "read", "source": "sale", "product_id": 123, **value})
            self.assert_error(code, browser_call.build_request, "product-edit", request_file=path)
        path = self.json_file("apply-no-preview.json", {"action": "apply", "source": "sale", "product_id": 123, "changes": {}})
        self.assert_error("expected_required", browser_call.build_request, "product-edit", request_file=path)
        path = self.json_file("read-with-changes.json", {"action": "read", "source": "sale", "product_id": 123, "changes": {}})
        self.assert_error("changes_not_applicable", browser_call.build_request, "product-edit", request_file=path)

    def test_product_create_reuses_exact_preview_for_apply_and_verify(self):
        preview = self.json_file("create-preview.json", {"ok": True, "stage": "product_create_preview", "snapshot": CREATE_SNAPSHOT})
        for action in ("apply", "verify"):
            with self.subTest(action=action):
                request_file = self.json_file("create-request.json", {"action": action, "source": SOURCE, "metadata": CREATE_METADATA, "limit": 1000})
                request = browser_call.build_request("product-create", request_file=request_file, preview_file=preview)
                self.assertEqual(request, {"action": action, "source": SOURCE, "metadata": CREATE_METADATA,
                                           "limit": 1000, "expected": CREATE_SNAPSHOT})
        request_file = self.json_file("conflicting-create-request.json", {"action": "apply", "source": SOURCE,
                                                                         "metadata": CREATE_METADATA, "expected": {**CREATE_SNAPSHOT, "state": "different"}})
        self.assert_error("conflicting_input", browser_call.build_request, "product-create", request_file=request_file, preview_file=preview)

    def test_product_create_source_file_supports_raw_and_successful_wrappers(self):
        request_file = self.json_file("create-request.json", {"action": "preview", "metadata": CREATE_METADATA})
        for value in (SOURCE, {"ok": True, "product": SOURCE}):
            with self.subTest(wrapper="product" in value):
                source_file = self.json_file("create-source.json", value)
                request = browser_call.build_request("product-create", request_file=request_file, source_file=source_file)
                self.assertEqual(request["source"], SOURCE)
        source_file = self.json_file("failed-create-source.json", {"ok": False, "product": SOURCE})
        self.assert_error("invalid_source_file", browser_call.build_request, "product-create", request_file=request_file, source_file=source_file)
        request_file = self.json_file("source-conflict.json", {"action": "preview", "source": {**SOURCE, "title": "Changed"}, "metadata": CREATE_METADATA})
        source_file = self.json_file("create-source.json", SOURCE)
        self.assert_error("conflicting_input", browser_call.build_request, "product-create", request_file=request_file, source_file=source_file)

    def test_product_create_rejects_basic_request_and_preview_errors(self):
        self.assert_error("request_file_required", browser_call.build_request, "product-create")
        for changes, code in (({"action": "read"}, "invalid_action"), ({"action": []}, "invalid_action"),
                              ({"source": []}, "invalid_json_object"), ({"metadata": []}, "invalid_json_object"),
                              ({"action": "apply"}, "expected_required")):
            request_file = self.json_file("bad-create-request.json", {"action": "preview", "source": SOURCE, "metadata": CREATE_METADATA, **changes})
            self.assert_error(code, browser_call.build_request, "product-create", request_file=request_file)
        request_file = self.json_file("missing-metadata.json", {"action": "preview", "source": SOURCE})
        self.assert_error("metadata_required", browser_call.build_request, "product-create", request_file=request_file)
        request_file = self.json_file("missing-source.json", {"action": "preview", "metadata": CREATE_METADATA})
        self.assert_error("source_required", browser_call.build_request, "product-create", request_file=request_file)
        request_file = self.json_file("create-apply.json", {"action": "apply", "source": SOURCE, "metadata": CREATE_METADATA})
        for value, code in (({"ok": False, "stage": "product_create_preview", "snapshot": CREATE_SNAPSHOT}, "invalid_preview"),
                            ({"ok": True, "stage": "product_edit_preview", "snapshot": CREATE_SNAPSHOT}, "invalid_preview"),
                            ({"ok": True, "stage": "product_create_preview"}, "invalid_preview_snapshot")):
            preview = self.json_file("bad-create-preview.json", value)
            self.assert_error(code, browser_call.build_request, "product-create", request_file=request_file, preview_file=preview)

    def test_product_create_cli_emits_only_invocation_summary(self):
        helpers = self.stub_helpers()
        source_file = self.json_file("create-source.json", {"ok": True, "product": SOURCE})
        request_file = self.json_file("create-request.json", {"action": "apply", "metadata": CREATE_METADATA})
        preview = self.json_file("create-preview.json", {"ok": True, "stage": "product_create_preview", "snapshot": CREATE_SNAPSHOT})
        output = self.folder / "create.js"
        stdout = io.StringIO()
        with mock.patch.object(browser_call, "SCRIPTS_DIR", helpers), contextlib.redirect_stdout(stdout):
            status = browser_call.main(["product-create", "--request-file", str(request_file), "--source-file", str(source_file),
                                        "--preview-file", str(preview), "--output", str(output)])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout.getvalue()), {"ok": True, "helper": "product-create", "sourcePath": str(output),
                                                        "format": "function", "action": "apply"})
        self.assertNotIn("metadata", stdout.getvalue())
        self.assertIn("return zyingWebProductCreate(request)", output.read_text(encoding="utf-8"))

    def test_unsupported_node_export_guard_is_rejected(self):
        helpers = self.stub_helpers()
        (helpers / browser_call.HELPERS["collect"][0]).write_text(
            "function collectAliExpressProduct() {}\nmodule.exports = collectAliExpressProduct;\n", encoding="utf-8")
        self.assert_error("unsupported_export_guard", browser_call.generate_invocation, "collect", {}, helpers)

    def test_json_read_rejects_duplicate_keys_nonfinite_values_and_malformed_data(self):
        for text, code in (('{"action":"read","action":"fill"}', "duplicate_json_key"),
                           ('{"amount":NaN}', "invalid_json_number"), ('{"amount":1e999}', "invalid_json_number"),
                           ('[]', "invalid_json_object"), ('{broken', "invalid_json")):
            with self.subTest(text=text):
                path = self.folder / "invalid.json"
                path.write_text(text, encoding="utf-8")
                self.assert_error(code, browser_call.read_json, path, "request file")
        self.assert_error("json_file_unreadable", browser_call.read_json, self.folder / "missing.json", "request file")

    def test_cli_returns_path_summary_and_structured_errors_only(self):
        helpers = self.stub_helpers()
        source = self.json_file("source.json", {**SOURCE, "title": "Secret draft $() `quote`\n第二行"})
        output = self.folder / "calls" / "preview.js"
        stdout = io.StringIO()
        with mock.patch.object(browser_call, "SCRIPTS_DIR", helpers), contextlib.redirect_stdout(stdout):
            result = browser_call.main(["new-draft", "--action", "preview", "--source-file", str(source), "--output", str(output)])
        self.assertEqual(result, 0)
        summary = json.loads(stdout.getvalue())
        self.assertEqual(summary["sourcePath"], str(output))
        self.assertEqual(summary["format"], "function")
        self.assertNotIn("Secret", stdout.getvalue())
        self.assertTrue(output.is_file())
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = browser_call.main(["collect", "--output", str(output), "--unexpected"])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(stdout.getvalue())["error"], "invalid_arguments")

    def test_output_must_be_absolute_and_cannot_replace_input(self):
        self.assert_error("absolute_output_required", browser_call.write_invocation, Path("relative.js"), "async()=>{}")
        path = self.json_file("input.json", SOURCE)
        original = path.read_bytes()
        self.assert_error("output_overlaps_input", browser_call.write_invocation, path, "async()=>{}", (path,))
        self.assertEqual(path.read_bytes(), original)

    @unittest.skipUnless(NODE, "Node is required for JavaScript syntax and data round-trip checks")
    def test_generated_javascript_preserves_tricky_json_as_data(self):
        helpers = self.stub_helpers()
        value = {"action": "preview", "source": {**SOURCE, "title": "quotes ' \" backtick `\n$(Get-Secret) ${notCode} \\ end \u2028中文",
                                                  "__proto__": {"polluted": True}, "nested": [None, False, {"constructor": "data"}]}}
        program = "const fs=require('node:fs'),vm=require('node:vm'); const f=vm.runInNewContext('('+fs.readFileSync(process.argv[1],'utf8')+')',{}); f().then(x=>console.log(JSON.stringify(x)));"
        requests = {"new-draft": value,
                    "product-edit": {"action": "preview", "source": "sale", "product_id": 123,
                                     "changes": {"english_description": value["source"]["title"], "__proto__": {"data": True}}},
                    "product-create": {**value, "metadata": {**CREATE_METADATA, "note": value["source"]["title"],
                                                               "native_pair": {"__proto__": ["data"]}}}}
        for helper, request in requests.items():
            with self.subTest(helper=helper):
                source = browser_call.generate_invocation(helper, request, helpers)
                self.assertNotIn("module.exports", source)
                path = self.folder / (helper + "-roundtrip.js")
                path.write_text(source, encoding="utf-8")
                result = subprocess.run([NODE, "-e", program, str(path)], capture_output=True, text=True, encoding="utf-8", timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), request)

    @unittest.skipUnless(NODE, "Node is required for JavaScript checks")
    def test_collector_checks_page_identity_before_calling_helper(self):
        helpers = self.stub_helpers()
        request = browser_call.build_request("collect", url=SOURCE["source_url"])
        path = self.folder / "collector.js"
        path.write_text(browser_call.generate_invocation("collect", request, helpers), encoding="utf-8")
        program = "const fs=require('node:fs'),vm=require('node:vm'); const f=vm.runInNewContext('('+fs.readFileSync(process.argv[1],'utf8')+')',{URL,location:{href:process.argv[2]}}); f().then(x=>console.log(JSON.stringify(x)));"
        for address, success in ((SOURCE["source_url"] + "?from=tracking", True),
                                 (SOURCE["source_url"].replace("5272", "5273"), False),
                                 (SOURCE["source_url"].replace("aliexpress.com", "aliexpress.com.evil.test"), False)):
            result = subprocess.run([NODE, "-e", program, str(path), address], capture_output=True, text=True, encoding="utf-8", timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(value["ok"], success)
            self.assertEqual(value.get("called", False), success)

    @unittest.skipUnless(NODE, "Node is required for JavaScript syntax checks")
    def test_real_colocated_helpers_generate_valid_function_expressions(self):
        for helper in browser_call.HELPERS:
            helper_path = browser_call.SCRIPTS_DIR / browser_call.HELPERS[helper][0]
            if not helper_path.is_file():
                continue
            with self.subTest(helper=helper):
                source = browser_call.generate_invocation(helper, {})
                self.assertNotIn("module.exports", source)
                result = subprocess.run([NODE, "--check"], input="(" + source + ");", capture_output=True, text=True, encoding="utf-8", timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
