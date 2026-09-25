import ast
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import payment_contract_store as store
import payment_contract_http as http
import payment_contract_cli as cli

FIXTURE = {"platform": "Payline Monext", "brand": "SYNTHETIC GARAGE", "siret": "12345678901234",
           "mcc": "1234", "bankCode": "00012", "acquirerBin": "00012345678", "acquirerTpe": "0004567",
           "nlsa": "001", "ertTpe": "24", "allowedErt": "24/27", "currency": "EUR",
           "bin3dsCb": "00012345678", "bin3dsVisa": "000123", "bin3dsMc": "000456", "merchantIdMc": "0000007"}


class ContractStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "vault"
        self.store = store.ContractStore(self.root)

    def save(self, fields=FIXTURE, revision=0, mode="manual"):
        return self.store.update({"revision": revision, "mode": mode, "fields": fields})

    def test_empty_defaults_have_no_merchant_data_or_live_payment(self):
        result = self.store.snapshot()
        self.assertEqual(result["revision"], 0)
        self.assertTrue(all(value == "" for value in result["fields"].values()))
        self.assertTrue(all(value is False for value in result["status"].values()))
        self.assertFalse((self.root / "contract.key").exists())

    def test_all_sheet_fields_roundtrip_including_leading_zeroes(self):
        self.assertEqual(set(FIXTURE), set(store.FIELDS))
        self.save()
        result = store.ContractStore(self.root).snapshot()
        self.assertEqual(result["fields"], FIXTURE)
        self.assertEqual(result["revision"], 1)
        self.assertFalse(result["status"]["livePaymentsEnabled"])
        self.assertFalse(result["status"]["contractVerified"])

    def test_state_is_encrypted_and_key_and_files_are_private(self):
        self.save()
        raw = (self.root / "contract.enc").read_bytes()
        for value in (FIXTURE["brand"], FIXTURE["siret"], FIXTURE["acquirerTpe"]):
            self.assertNotIn(value.encode(), raw)
        for name in ("contract.enc", "contract.key", "contract.lock"):
            self.assertEqual((self.root / name).stat().st_mode & 0o777, 0o600)

    def test_import_only_fills_missing_and_is_idempotent(self):
        self.save({"brand": "MANUAL NAME"})
        result = self.save(revision=1, mode="import_missing")
        self.assertEqual(result["fields"]["brand"], "MANUAL NAME")
        self.assertEqual(result["fields"]["nlsa"], "001")
        self.assertEqual(result["revision"], 2)
        retry = self.save(revision=2, mode="import_missing")
        self.assertEqual(retry["revision"], 2)
        self.assertEqual(retry["changedFields"], [])

    def test_imported_values_remain_manually_editable(self):
        self.save(mode="import_missing")
        result = self.save({"acquirerTpe": "0008899", "nlsa": ""}, revision=1)
        self.assertEqual(result["fields"]["acquirerTpe"], "0008899")
        self.assertEqual(result["fields"]["nlsa"], "")
        self.assertEqual(result["fields"]["brand"], FIXTURE["brand"])

    def test_stale_revision_is_refused_without_overwrite(self):
        self.save()
        with self.assertRaises(store.ContractConflict):
            self.save({"brand": "STALE"})
        self.assertEqual(self.store.snapshot()["fields"], FIXTURE)

    def test_concurrent_saves_only_one_wins(self):
        def attempt(name):
            try:
                self.save({"brand": name})
                return "saved"
            except store.ContractConflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, ["FIRST", "SECOND"]))
        self.assertCountEqual(results, ["saved", "conflict"])
        self.assertEqual(len(self.store.snapshot()["audit"]), 1)

    def test_numeric_identifiers_are_refused_not_coerced(self):
        for field in ("nlsa", "merchantIdMc", "acquirerTpe", "siret"):
            with self.subTest(field=field), self.assertRaises(store.ContractInvalid):
                self.save({field: 1})

    def test_api_secrets_card_data_and_payment_switch_are_not_accepted(self):
        for field in ("accessKey", "merchantId", "contractNumber", "clientSecret", "cardNumber", "cvv"):
            with self.subTest(field=field), self.assertRaises(store.ContractInvalid):
                self.save({field: "DO_NOT_STORE"})
        with self.assertRaises(store.ContractInvalid):
            self.store.update({"revision": 0, "mode": "manual", "fields": {}, "livePaymentsEnabled": True})

    def test_invalid_formats_and_non_payline_platform_are_refused(self):
        for fields in ({"siret": "123"}, {"mcc": "12345"}, {"platform": "Monetico"},
                       {"currency": "USD"}, {"brand": "<script>"}, {"allowedErt": "24//27"}):
            with self.subTest(fields=fields), self.assertRaises(store.ContractInvalid):
                self.save(fields)
        self.assertEqual(self.store.snapshot()["revision"], 0)

    def test_audit_records_only_changed_names_not_values(self):
        self.save()
        audit = json.dumps(self.store.snapshot()["audit"])
        for value in FIXTURE.values():
            if len(value) > 5:
                self.assertNotIn(value, audit)
        self.assertIn("acquirerTpe", audit)
        self.assertNotIn("oldValue", audit)

    def test_corrupted_ciphertext_fails_closed_without_overwriting(self):
        self.save()
        path = self.root / "contract.enc"
        raw = path.read_bytes(); corrupted = raw[:-1] + bytes([raw[-1] ^ 1]); path.write_bytes(corrupted)
        with self.assertRaises(store.ContractStorageError):
            self.save({"brand": "NEW"}, revision=1)
        self.assertEqual(path.read_bytes(), corrupted)

    def test_missing_key_does_not_regenerate_over_existing_store(self):
        self.save(); (self.root / "contract.key").unlink()
        with self.assertRaises(store.ContractStorageError):
            self.store.snapshot()
        self.assertFalse((self.root / "contract.key").exists())

    def test_symlink_and_insecure_permissions_are_refused(self):
        self.save()
        (self.root / "contract.enc").chmod(0o644)
        with self.assertRaises(store.ContractStorageError):
            self.store.snapshot()
        alias = Path(self.temp.name) / "alias"; alias.symlink_to(self.root)
        with self.assertRaises(store.ContractStorageError):
            store.ContractStore(alias).snapshot()

    def test_import_schema_cannot_infer_api_credentials(self):
        self.assertEqual(store.validate_import({"schemaVersion": 1, "provider": store.PROVIDER, "fields": FIXTURE}), FIXTURE)
        for bad in ({"schemaVersion": True, "provider": store.PROVIDER, "fields": FIXTURE},
                    {"schemaVersion": 1, "provider": "monetico", "fields": FIXTURE},
                    {"schemaVersion": 1, "provider": store.PROVIDER, "fields": FIXTURE, "accessKey": "secret"}):
            with self.assertRaises(store.ContractInvalid):
                store.validate_import(bad)

    def test_duplicate_json_and_oversized_import_are_refused(self):
        for raw in (b'{"fields":{"nlsa":"001","nlsa":"002"}}', b'[]', b' ' * (store.MAX_BYTES + 1)):
            with self.assertRaises(store.ContractInvalid):
                store.parse_json(raw)

    def test_private_cli_import_redacts_values_and_preserves_manual_data(self):
        path = Path(self.temp.name) / "import.json"
        path.write_text(json.dumps({"schemaVersion": 1, "provider": store.PROVIDER, "fields": FIXTURE})); path.chmod(0o600)
        output = io.StringIO()
        with patch("sys.stdout", output):
            status = cli.main(["--file", str(path), "--store", str(self.root), "--revision", "0"])
        self.assertEqual(status, 0)
        self.assertEqual(self.store.snapshot()["fields"], FIXTURE)
        self.assertNotIn(FIXTURE["siret"], output.getvalue())
        self.assertNotIn(FIXTURE["brand"], output.getvalue())


class FakeHandler:
    def __init__(self, command="GET", body=None):
        self.command = command; self.path = http.ROUTE; self.auth = True; self.mfa = True; self.origin = True
        self.headers = {"Authorization": "Basic synthetic", "Cookie": "session=synthetic"}
        raw = json.dumps(body).encode() if body is not None else b""
        self.rfile = io.BytesIO(raw); self.headers["Content-Length"] = str(len(raw))
        self.headers["Content-Type"] = "application/json"
        self.headers["X-CheckupAuto-Payments-CSRF"] = http.csrf_token("synthetic-secret", self.headers)
        self.response = None
    def authorized(self): return self.auth
    def _mfa_session_valid(self): return self.mfa
    def _admin_origin_ok(self): return self.origin
    def require_auth(self): self.send_json({"error": "unauthorized"}, 401)
    def require_mfa(self): self.send_json({"error": "two_factor_required"}, 403)
    def send_json(self, data, status=200): self.response = (status, data)


class ContractHTTPTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        patcher = patch.dict(os.environ, {"CYBERCHECK_PRIVATE_DIR": self.temp.name}); patcher.start(); self.addCleanup(patcher.stop)

    def call(self, handler):
        self.assertTrue(http.handle(handler, secret="synthetic-secret"))
        return handler.response

    def post(self):
        return FakeHandler("POST", {"revision": 0, "mode": "manual", "fields": FIXTURE})

    def test_auth_and_mfa_before_store_access(self):
        for name, status in (("auth", 401), ("mfa", 403)):
            h = self.post(); setattr(h, name, False)
            with patch.object(http, "ContractStore") as mocked:
                self.assertEqual(self.call(h)[0], status)
            mocked.assert_not_called()

    def test_unrelated_route_not_intercepted(self):
        h = FakeHandler(); h.path = "/api/admin/config"
        self.assertFalse(http.handle(h, secret="synthetic-secret"))
        self.assertIsNone(h.response)

    def test_read_save_read_roundtrip(self):
        read = self.call(FakeHandler())[1]
        self.assertEqual(read["revision"], 0)
        self.assertEqual(len(read["csrfToken"]), 64)
        self.assertEqual(self.call(self.post())[0], 200)
        self.assertEqual(self.call(FakeHandler())[1]["fields"], FIXTURE)

    def test_csrf_and_origin_before_store_access(self):
        cases = []
        h = self.post(); h.headers.pop("X-CheckupAuto-Payments-CSRF"); cases.append(h)
        h = self.post(); h.headers["Cookie"] = "session=foreign"; cases.append(h)
        h = self.post(); h.origin = False; cases.append(h)
        h = self.post(); h.headers["Sec-Fetch-Site"] = "cross-site"; cases.append(h)
        for h in cases:
            with patch.object(http, "ContractStore") as mocked:
                self.assertEqual(self.call(h)[0], 403)
            mocked.assert_not_called()

    def test_expired_csrf_token_is_refused(self):
        h = self.post(); h.headers["X-CheckupAuto-Payments-CSRF"] = http.csrf_token("synthetic-secret", h.headers, 1)
        self.assertEqual(self.call(h)[0], 403)

    def test_content_type_size_and_transfer_encoding(self):
        for key, value, status in (("Content-Type", "text/plain", 415), ("Content-Length", "40000", 413),
                                   ("Content-Length", "bad", 400), ("Transfer-Encoding", "chunked", 400)):
            h = self.post(); h.headers[key] = value
            self.assertEqual(self.call(h)[0], status)

    def test_query_and_fragment_refused(self):
        for suffix in ("?accessKey=do-not-log", "#fragment"):
            h = FakeHandler(); h.path += suffix
            self.assertEqual(self.call(h)[0], 400)

    def test_revision_conflict_preserves_data(self):
        self.call(self.post())
        self.assertEqual(self.call(self.post())[0], 409)
        self.assertEqual(self.call(FakeHandler())[1]["fields"], FIXTURE)

    def test_invalid_field_and_storage_errors_are_sanitized(self):
        h = self.post(); h.rfile = io.BytesIO(b'{"secret":"do-not-echo"}'); h.headers["Content-Length"] = str(len(h.rfile.getvalue()))
        status, body = self.call(h)
        self.assertEqual(status, 400); self.assertNotIn("do-not-echo", repr(body))
        with patch.object(http.ContractStore, "snapshot", side_effect=RuntimeError("private-bank-information")):
            status, body = self.call(FakeHandler())
        self.assertEqual(status, 500); self.assertNotIn("private-bank-information", repr(body))


class PaymentContractUIContractTest(unittest.TestCase):
    def test_editor_does_not_embed_bank_values_or_use_html_insertion(self):
        root = Path(__file__).resolve().parent
        html = (root / "admin/payments.html").read_text()
        js = (root / "admin/payments.js").read_text()
        self.assertIn("Payline / Monext", html)
        self.assertIn("Paiements", html)
        self.assertIn("import_missing", js)
        self.assertIn("input.type='text'", js)
        self.assertIn("textContent", js)
        self.assertNotIn("innerHTML", js)
        self.assertNotIn("localStorage", js)
        self.assertNotIn("sessionStorage", js)
        self.assertIn("X-CheckupAuto-Payments-CSRF", js)
        self.assertIn("accessKey=$('#paylineAccessKey').value", js)
        self.assertNotIn("data.accessKey", js)
        self.assertNotIn("data.status.accessKey", js)
        self.assertIn("$('#paylineAccessKey').value=''", js)
        self.assertNotIn("console.log", js)

    def test_routes_are_wired_after_guard_and_menu_link_exists(self):
        root = Path(__file__).resolve().parent
        # Local standalone module tests can run without a full application tree.
        if not (root / "admin_server.py").exists():
            self.skipTest("integration assertion runs in repository CI")
        source = (root / "admin_server.py").read_text()
        tree = ast.parse(source)
        self.assertIn("import payment_contract_http", source)
        handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Handler")
        for name in ("do_GET", "do_POST"):
            method = next(n for n in handler.body if isinstance(n, ast.FunctionDef) and n.name == name)
            text = ast.get_source_segment(source, method)
            self.assertLess(text.index("self._guard()"), text.index("payment_contract_http.handle"))
        index = (root / "admin/index.html").read_text()
        self.assertIn('href="/admin/payments.html"', index)


if __name__ == "__main__":
    unittest.main()
