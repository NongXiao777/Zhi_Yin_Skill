#!/usr/bin/env python3
"""Build a self-contained browser helper invocation without opening a browser.

The output is an async function expression for evaluate_script(sourcePath=...,
format="function"). Input JSON remains data, including quotes and newlines.
Only the explicitly supplied JSON files and the colocated helper are read.
"""

import argparse
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlsplit


HELPERS = {
    "collect": ("aliexpress_browser_collect.js", "collectAliExpressProduct"),
    "extension-read": ("aliexpress_extension_read.js", "zyingAliExpressExtensionRead"),
    "new-draft": ("zying_web_new_draft.js", "zyingWebNewDraft"),
    "product-edit": ("zying_web_product_edit.js", "zyingWebProductEdit"),
    "product-create": ("zying_web_product_create.js", "zyingWebProductCreate"),
}
PREVIEW_STAGES = {"new-draft": "new_draft_preview", "product-edit": "product_edit_preview",
                  "product-create": "product_create_preview"}
SCRIPTS_DIR = Path(__file__).resolve().parent
MAX_JSON_BYTES = 2_000_000
ITEM_ID = re.compile(r"^[0-9]{10,24}$")
EXPORT_GUARD = re.compile(
    r"^[ \t]*if[ \t]*\([ \t]*typeof[ \t]+module[ \t]*===[ \t]*"
    r"(?P<quote>[\"'])object(?P=quote)[ \t]*\)[ \t]*"
    r"module\.exports[ \t]*=[ \t]*[A-Za-z_$][\w$]*[ \t]*;[ \t]*$",
    re.MULTILINE,
)


class BrowserCallError(Exception):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class JSONArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise BrowserCallError("invalid_arguments", message)


def _object(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise BrowserCallError("invalid_json_object", label + " must be a JSON object")
    return value


def _unique_object(pairs: Any) -> Dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BrowserCallError("duplicate_json_key", "JSON contains a duplicate object key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise BrowserCallError("invalid_json_number", "JSON numbers must be finite")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        _invalid_constant(value)
    return number


def read_json(path: Path, label: str) -> Dict[str, Any]:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_JSON_BYTES + 1)
    except OSError:
        raise BrowserCallError("json_file_unreadable", label + " could not be read", path=str(path)) from None
    if len(raw) > MAX_JSON_BYTES:
        raise BrowserCallError("json_file_too_large", label + " exceeds the JSON size limit", path=str(path))
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                           parse_constant=_invalid_constant, parse_float=_finite_float)
    except (UnicodeError, ValueError, RecursionError):
        raise BrowserCallError("invalid_json", label + " must contain UTF-8 JSON", path=str(path)) from None
    return _object(value, label)


def canonical_aliexpress_url(address: Any) -> Dict[str, str]:
    """Accept an item link, discard tracking data, and reject deceptive hosts."""
    if not isinstance(address, str) or not address or len(address) > 2000 or any(
            ord(character) < 33 or ord(character) == 127 for character in address):
        raise BrowserCallError("invalid_aliexpress_url", "Use an HTTPS AliExpress item link")
    try:
        url = urlsplit(address)
        valid = (url.scheme.lower() == "https" and not url.username and not url.password and
                 url.port is None and url.hostname in {"aliexpress.com", "www.aliexpress.com", "m.aliexpress.com"})
        match = re.fullmatch(r"/(?:item|i)/([0-9]{10,24})\.html/?", url.path, re.IGNORECASE)
    except ValueError:
        valid, match = False, None
    if not valid or not match:
        raise BrowserCallError("invalid_aliexpress_url", "Use an HTTPS AliExpress item link")
    product_id = match.group(1)
    return {"target_url": "https://www.aliexpress.com/item/" + product_id + ".html",
            "source_product_id": product_id}


def _merge(request: Dict[str, Any], key: str, value: Any) -> None:
    if key in request and request[key] != value:
        raise BrowserCallError("conflicting_input", "Supplied inputs disagree on " + key)
    request[key] = value


def _check_keys(request: Dict[str, Any], allowed: Any) -> None:
    if set(request) - set(allowed):
        raise BrowserCallError("invalid_request_fields", "Request contains unsupported fields")


def _preview(path: Path, helper: str) -> Dict[str, Any]:
    value = read_json(path, "preview file")
    stage = PREVIEW_STAGES[helper]
    if value.get("ok") is not True or value.get("stage") != stage:
        raise BrowserCallError("invalid_preview", "Preview file must be a successful " + helper + " preview")
    snapshot = value.get("snapshot")
    if not isinstance(snapshot, dict) or not snapshot:
        raise BrowserCallError("invalid_preview_snapshot", "Successful preview is missing its snapshot")
    return snapshot


def _source_file(path: Path) -> Dict[str, Any]:
    source = read_json(path, "source file")
    if "ok" in source or "product" in source:
        if source.get("ok") is not True or not isinstance(source.get("product"), dict):
            raise BrowserCallError("invalid_source_file", "Source wrapper must contain ok:true and product")
        source = source["product"]
    return source


def build_request(helper: str, request_file: Optional[Path] = None,
                  action: Optional[str] = None, source_file: Optional[Path] = None,
                  preview_file: Optional[Path] = None, url: Optional[str] = None) -> Dict[str, Any]:
    if helper not in HELPERS:
        raise BrowserCallError("unknown_helper", "Choose collect, extension-read, new-draft, product-edit, or product-create")
    request = read_json(request_file, "request file") if request_file is not None else {}
    if helper == "collect":
        if any(value is not None for value in (action, source_file, preview_file)):
            raise BrowserCallError("invalid_arguments", "Collector accepts only a request file and an optional URL")
        _check_keys(request, {"target_url", "source_product_id"})
        target = canonical_aliexpress_url(request["target_url"]) if "target_url" in request else None
        if "source_product_id" in request and (not isinstance(request["source_product_id"], str) or
                                              not ITEM_ID.fullmatch(request["source_product_id"])):
            raise BrowserCallError("invalid_source_product_id", "Source product ID must be a 10 to 24 digit string")
        if target:
            _merge(request, "source_product_id", target["source_product_id"])
            request["target_url"] = target["target_url"]
        if url is not None:
            target = canonical_aliexpress_url(url)
            for key, value in target.items():
                _merge(request, key, value)
        if "source_product_id" in request and "target_url" not in request:
            request["target_url"] = "https://www.aliexpress.com/item/" + request["source_product_id"] + ".html"
        return request
    if helper == "extension-read":
        if any(value is not None for value in (action, source_file, preview_file)):
            raise BrowserCallError("invalid_arguments", "Extension read accepts only a request file and an optional URL")
        _check_keys(request, {"target_url", "source_product_id", "tab_id"})
        if "tab_id" in request and (type(request["tab_id"]) is not int or not 1 <= request["tab_id"] <= 2_147_483_647):
            raise BrowserCallError("invalid_extension_tab_id", "Extension tab ID must be a positive Int32 Chrome tab ID")
        if "source_product_id" in request and (not isinstance(request["source_product_id"], str) or
                                              not ITEM_ID.fullmatch(request["source_product_id"])):
            raise BrowserCallError("invalid_source_product_id", "Source product ID must be a 10 to 24 digit string")
        if "target_url" in request:
            target = canonical_aliexpress_url(request["target_url"])
            _merge(request, "source_product_id", target["source_product_id"])
            request["target_url"] = target["target_url"]
        if url is not None:
            for key, value in canonical_aliexpress_url(url).items():
                _merge(request, key, value)
        if "source_product_id" not in request:
            raise BrowserCallError("source_product_id_required", "Extension read requires a known AliExpress source product ID or URL")
        request.setdefault("target_url", "https://www.aliexpress.com/item/" + request["source_product_id"] + ".html")
        return request
    if url is not None:
        raise BrowserCallError("invalid_arguments", "URL is only supported for collect or extension-read")
    if action is not None:
        _merge(request, "action", action)
    if helper == "new-draft":
        _check_keys(request, {"action", "source", "expected"})
        if source_file is not None:
            _merge(request, "source", _source_file(source_file))
        if not isinstance(request.get("action"), str) or request["action"] not in {"read", "preview", "fill", "verify"}:
            raise BrowserCallError("invalid_action", "New draft action must be read, preview, fill, or verify")
        if request["action"] != "read" and "source" not in request:
            raise BrowserCallError("source_required", "This new draft action requires a source file or request.source")
        if "source" in request:
            _object(request["source"], "request.source")
        needs_expected = request["action"] == "fill"
    elif helper == "product-create":
        if request_file is None:
            raise BrowserCallError("request_file_required", "Product create requires a request file")
        _check_keys(request, {"action", "source", "metadata", "expected", "limit"})
        if source_file is not None:
            _merge(request, "source", _source_file(source_file))
        if not isinstance(request.get("action"), str) or request["action"] not in {"preview", "apply", "verify"}:
            raise BrowserCallError("invalid_action", "Product create action must be preview, apply, or verify")
        if "source" not in request:
            raise BrowserCallError("source_required", "Product create requires a source file or request.source")
        _object(request["source"], "request.source")
        if "metadata" not in request:
            raise BrowserCallError("metadata_required", "Product create requires request.metadata")
        _object(request["metadata"], "request.metadata")
        # The creation helper validates source and metadata semantics and binds
        # them to the preview. Keep their values unchanged in the invocation.
        needs_expected = request["action"] in {"apply", "verify"}
    else:
        if source_file is not None:
            raise BrowserCallError("invalid_arguments", "Product edit source is supplied in the request file")
        if request_file is None:
            raise BrowserCallError("request_file_required", "Product edit requires a request file")
        _check_keys(request, {"action", "source", "product_id", "limit", "changes", "expected"})
        if not isinstance(request.get("action"), str) or request["action"] not in {"read", "preview", "apply", "verify"}:
            raise BrowserCallError("invalid_action", "Product edit action must be read, preview, apply, or verify")
        if not isinstance(request.get("source"), str) or request["source"] not in {"sale", "spider"}:
            raise BrowserCallError("invalid_product_source", "Product source must be sale or spider")
        if type(request.get("product_id")) is not int or not 1 <= request["product_id"] <= 2_147_483_647:
            raise BrowserCallError("invalid_product_id", "Product ID must be a positive Int32 JSON integer")
        if "limit" in request and (type(request["limit"]) is not int or not 1 <= request["limit"] <= 50):
            raise BrowserCallError("invalid_limit", "Limit must be a JSON integer from 1 to 50")
        if request["action"] == "read" and "changes" in request:
            raise BrowserCallError("changes_not_applicable", "Product read does not accept changes")
        if request["action"] != "read" and not isinstance(request.get("changes"), dict):
            raise BrowserCallError("changes_required", "This product edit action requires request.changes")
        if "changes" in request:
            _object(request["changes"], "request.changes")
        needs_expected = request["action"] in {"apply", "verify"}
    if preview_file is not None:
        if not needs_expected:
            raise BrowserCallError("preview_not_applicable", "Preview file is only used for fill, apply, or product verify")
        snapshot = _preview(preview_file, helper)
        if helper == "product-edit" and (snapshot.get("source") != request["source"] or
                type(snapshot.get("product_id")) is not int or snapshot["product_id"] != request["product_id"]):
            raise BrowserCallError("preview_product_mismatch", "Preview belongs to a different product or source")
        _merge(request, "expected", snapshot)
    if needs_expected:
        if not isinstance(request.get("expected"), dict) or not request["expected"]:
            raise BrowserCallError("expected_required", "Use a successful preview file or request.expected snapshot")
        if helper == "product-edit" and (request["expected"].get("source") != request["source"] or
                type(request["expected"].get("product_id")) is not int or
                request["expected"]["product_id"] != request["product_id"]):
            raise BrowserCallError("preview_product_mismatch", "Expected snapshot belongs to a different product or source")
    elif "expected" in request:
        raise BrowserCallError("expected_not_applicable", "Expected snapshot is not used for this action")
    return request


COLLECT_IDENTITY_CHECK = r"""  if (request.source_product_id) {
    let current;
    try { current = new URL(location.href); } catch { return {ok: false, error: "source_item_mismatch"}; }
    const id = current.pathname.match(/^\/(?:item|i)\/([0-9]{10,24})\.html\/?$/i)?.[1];
    if (current.protocol !== "https:" || current.username || current.password || current.port ||
        !/^(?:(?:www|m)\.)?aliexpress\.com$/i.test(current.hostname) || id !== request.source_product_id) {
      return {ok: false, error: "source_item_mismatch", source_product_id: request.source_product_id};
    }
  }
"""


def generate_invocation(helper: str, request: Dict[str, Any], scripts_dir: Optional[Path] = None) -> str:
    if helper not in HELPERS:
        raise BrowserCallError("unknown_helper", "Choose collect, extension-read, new-draft, product-edit, or product-create")
    filename, function = HELPERS[helper]
    path = (scripts_dir or SCRIPTS_DIR) / filename
    try:
        source = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        raise BrowserCallError("helper_unreadable", "Colocated browser helper could not be read", path=str(path)) from None
    source = EXPORT_GUARD.sub("", source).rstrip()
    if "module.exports" in source:
        raise BrowserCallError("unsupported_export_guard", "Browser helper has an unsupported Node export guard")
    if not re.search(r"\bfunction\s+" + re.escape(function) + r"\s*\(", source):
        raise BrowserCallError("helper_function_missing", "Browser helper function was not found")
    try:
        # JSON.parse preserves JSON's own __proto__ keys as data. Both layers
        # use JSON encoding; no input is interpreted as JavaScript source.
        data = json.dumps(request, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        literal = json.dumps(data, ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise BrowserCallError("invalid_request_json", "Request must be finite JSON data") from None
    gate = COLLECT_IDENTITY_CHECK if helper == "collect" else ""
    argument = "" if helper == "collect" else "request"
    return "async () => {\n" + source + "\n\n  const request = JSON.parse(" + literal + ");\n" + gate + \
        "  return " + function + "(" + argument + ");\n}\n"


def write_invocation(path: Path, source: str, inputs: Any = ()) -> Path:
    if not path.is_absolute():
        raise BrowserCallError("absolute_output_required", "Output must be an absolute file path")
    path = path.resolve()
    protected = [SCRIPTS_DIR / filename for filename, _ in HELPERS.values()] + [Path(__file__)]
    protected += [value for value in inputs if value is not None]
    if any(os.path.normcase(str(path)) == os.path.normcase(str(value.resolve())) for value in protected):
        raise BrowserCallError("output_overlaps_input", "Output must differ from helper and input files")
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", prefix=".browser-call-",
                                         suffix=".tmp", dir=str(path.parent), delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(source)
        os.replace(str(temporary), str(path))
    except OSError:
        raise BrowserCallError("output_unwritable", "Browser invocation could not be written", path=str(path)) from None
    finally:
        if temporary is not None and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass
    return path


def parser() -> argparse.ArgumentParser:
    result = JSONArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="helper", required=True)
    for helper in HELPERS:
        command = commands.add_parser(helper)
        command.add_argument("--request-file", type=Path, help="UTF-8 JSON request object")
        command.add_argument("--output", type=Path, required=True, help="Absolute output file path")
        if helper in {"collect", "extension-read"}:
            command.add_argument("--url", help="AliExpress item link; use the product page for collect or the installed collector service worker for extension-read")
        elif helper == "new-draft":
            command.add_argument("--action", choices=("read", "preview", "fill", "verify"))
            command.add_argument("--source-file", type=Path, help="Raw product JSON or successful collector result")
            command.add_argument("--preview-file", type=Path, help="Successful new_draft_preview JSON result")
        elif helper == "product-edit":
            command.add_argument("--preview-file", type=Path, help="Successful product_edit_preview JSON result")
        else:
            command.add_argument("--source-file", type=Path, help="Raw product JSON or successful collector result")
            command.add_argument("--preview-file", type=Path, help="Successful product_create_preview JSON result")
    return result


def main(argv: Optional[Any] = None) -> int:
    try:
        args = parser().parse_args(argv)
        request = build_request(args.helper, args.request_file, getattr(args, "action", None),
                                getattr(args, "source_file", None), getattr(args, "preview_file", None),
                                getattr(args, "url", None))
        source = generate_invocation(args.helper, request)
        output = write_invocation(args.output, source, (args.request_file, getattr(args, "source_file", None),
                                                       getattr(args, "preview_file", None)))
        summary = {"ok": True, "helper": args.helper, "sourcePath": str(output), "format": "function"}
        for key in ("action", "source_product_id", "target_url", "product_id"):
            if key in request:
                summary[key] = request[key]
        print(json.dumps(summary, ensure_ascii=True))
        return 0
    except BrowserCallError as error:
        print(json.dumps({"ok": False, "error": error.code, "message": str(error), **error.details}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
