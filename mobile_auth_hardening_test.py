"""S-05 / S-06 / S-08 / S-12 behavioural regression tests (real stores, HTTP handler)."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import customer_accounts
import customer_http as http
import customer_oidc
import mobile_auth_ticket
from customer_http_test import Handler


def _challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


VERIFIER = "v" * 20 + "-._~" + "x" * 24


class _Stores(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "data").mkdir(); (root / "private").mkdir()
        env = mock.patch.dict(os.environ, {"CYBERCHECK_DATA_DIR": str(root / "data"), "CYBERCHECK_PRIVATE_DIR": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        os.environ.pop(mobile_auth_ticket.PKCE_REQUIRED_ENV, None)
        os.environ.pop(customer_oidc.NATIVE_NONCE_REQUIRED_ENV, None)
        self.account = customer_accounts.create_from_verified_identity("google", "sub-1", "alice@example.test", "Alice", email_verified=True)


class MobileTicketPkceTest(_Stores):
    def test_ticket_with_challenge_requires_matching_verifier(self):
        ticket = mobile_auth_ticket.issue(self.account["accountId"], code_challenge=_challenge(VERIFIER))
        with self.assertRaises(PermissionError):
            mobile_auth_ticket.consume(ticket, "w" * 48)
        # A failed attempt burns the ticket: an interceptor gets one try only.
        with self.assertRaises(PermissionError):
            mobile_auth_ticket.consume(ticket, VERIFIER)

    def test_ticket_with_challenge_and_verifier_yields_account(self):
        ticket = mobile_auth_ticket.issue(self.account["accountId"], code_challenge=_challenge(VERIFIER))
        self.assertEqual(mobile_auth_ticket.consume(ticket, VERIFIER), self.account["accountId"])

    def test_legacy_ticket_without_challenge_is_refused_when_pkce_required(self):
        ticket = mobile_auth_ticket.issue(self.account["accountId"])
        with mock.patch.dict(os.environ, {mobile_auth_ticket.PKCE_REQUIRED_ENV: "1"}):
            with self.assertRaises(PermissionError):
                mobile_auth_ticket.consume(ticket)

    def test_no_session_token_is_stored_at_rest(self):
        mobile_auth_ticket.issue(self.account["accountId"], code_challenge=_challenge(VERIFIER))
        with sqlite3.connect(mobile_auth_ticket._path()) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(mobile_auth_ticket)")}
        self.assertNotIn("session_token", columns)

    def test_legacy_table_with_raw_session_tokens_is_dropped(self):
        path = mobile_auth_ticket._path()
        with sqlite3.connect(path) as db:
            db.execute("DROP TABLE IF EXISTS mobile_auth_ticket")
            db.execute("CREATE TABLE mobile_auth_ticket(ticket_hash TEXT PRIMARY KEY, session_token TEXT NOT NULL, expires_at TEXT NOT NULL)")
            db.execute("INSERT INTO mobile_auth_ticket VALUES('h','raw-session','2999-01-01T00:00:00+00:00')")
        mobile_auth_ticket.issue(self.account["accountId"])
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM mobile_auth_ticket").fetchone()[0], 1)
            self.assertNotIn("raw-session", repr(db.execute("SELECT * FROM mobile_auth_ticket").fetchall()))

    def test_exchange_route_issues_session_only_with_verifier(self):
        ticket = mobile_auth_ticket.issue(self.account["accountId"], code_challenge=_challenge(VERIFIER))
        bad = Handler("/api/mobile/auth/exchange", "POST", {"ticket": ticket})
        self.assertTrue(http.handle(bad))
        self.assertEqual(bad.response["status"], 401)

        ticket = mobile_auth_ticket.issue(self.account["accountId"], code_challenge=_challenge(VERIFIER))
        good = Handler("/api/mobile/auth/exchange", "POST", {"ticket": ticket, "code_verifier": VERIFIER})
        self.assertTrue(http.handle(good))
        self.assertEqual(good.response["status"], 200)
        body = good.response["json"]
        self.assertEqual(customer_accounts.authenticate_session(body["sessionToken"]), self.account["accountId"])

    def test_begin_route_carries_challenge_into_flow(self):
        h = Handler("/auth/customer/google?mobile=1&code_challenge=" + _challenge(VERIFIER))
        with mock.patch.object(http.customer_oidc, "begin", return_value="https://accounts.example/auth?state=" + "s" * 43) as begin:
            http.handle(h)
        self.assertEqual(begin.call_args.kwargs["mobile_challenge"], _challenge(VERIFIER))

    def test_mobile_callback_does_not_leave_a_browser_session(self):
        session = customer_accounts.issue_session(self.account["accountId"])
        result = {"account": self.account, "session": session, "mobile": True, "returnTo": "", "mobileChallenge": _challenge(VERIFIER)}
        h = Handler("/auth/customer/google/callback?state=" + "s" * 43 + "&code=c")
        with mock.patch.object(http.customer_oidc, "complete", return_value=result):
            http.handle(h)
        self.assertEqual(h.response["status"], 303)
        self.assertTrue(h.response["location"].startswith("checkupauto://auth/google?ticket="))
        with self.assertRaises(PermissionError):
            customer_accounts.authenticate_session(session["token"])

    def test_exchange_is_rate_limited_by_sentinel(self):
        import security_guard
        self.assertLessEqual(security_guard._ENDPOINT_LIMITS["/api/mobile/auth/exchange"], 10)
        self.assertIn("/api/mobile/auth/apple", security_guard._ENDPOINT_LIMITS)


class NativeAppleNonceTest(_Stores):
    def test_server_nonce_is_single_use(self):
        nonce = customer_oidc.issue_native_nonce()["nonce"]
        customer_oidc.consume_native_nonce(nonce)
        with self.assertRaises(customer_oidc.CustomerOIDCError):
            customer_oidc.consume_native_nonce(nonce)

    def test_client_nonce_cannot_be_replayed(self):
        nonce = "n" * 43
        customer_oidc.consume_native_nonce(nonce)
        with self.assertRaises(customer_oidc.CustomerOIDCError):
            customer_oidc.consume_native_nonce(nonce)

    def test_required_mode_refuses_client_chosen_nonce(self):
        with mock.patch.dict(os.environ, {customer_oidc.NATIVE_NONCE_REQUIRED_ENV: "1"}):
            with self.assertRaises(customer_oidc.CustomerOIDCError):
                customer_oidc.consume_native_nonce("c" * 43)
            nonce = customer_oidc.issue_native_nonce()["nonce"]
            customer_oidc.consume_native_nonce(nonce)

    def _apple(self, claims, nonce):
        payload = {"identityToken": "jwt", "authorizationCode": "code", "userIdentifier": "apple-sub",
                   "email": "attacker@example.test", "nonce": nonce}
        h = Handler("/api/mobile/auth/apple", "POST", payload)
        with mock.patch.object(http.customer_oidc, "verify_native_apple_identity", return_value=claims):
            http.handle(h)
        return h.response

    def test_replayed_identity_token_is_refused(self):
        claims = {"sub": "apple-sub", "email": "bob@example.test", "email_verified": "true"}
        nonce = customer_oidc.issue_native_nonce()["nonce"]
        self.assertEqual(self._apple(claims, nonce)["status"], 200)
        self.assertEqual(self._apple(claims, nonce)["status"], 401)

    def test_body_email_is_ignored_when_claim_missing(self):
        claims = {"sub": "apple-sub", "email_verified": "true"}
        response = self._apple(claims, customer_oidc.issue_native_nonce()["nonce"])
        self.assertEqual(response["status"], 401)

    def test_nonce_route_issues_nonce(self):
        h = Handler("/api/mobile/auth/apple/nonce", "POST", {})
        self.assertTrue(http.handle(h))
        self.assertEqual(h.response["status"], 200)
        self.assertRegex(h.response["json"]["nonce"], r"^[A-Za-z0-9_-]{43}$")


class MicrosoftLatentProviderTest(unittest.TestCase):
    def test_microsoft_without_verified_email_fails_closed(self):
        flow = {"redirect_uri": "https://x/cb", "verifier": "v", "nonce": "n", "mobile": 0, "return_to": ""}
        response = mock.Mock(status_code=200, json=lambda: {"id_token": "t"})
        with mock.patch.object(customer_oidc, "_consume_flow", return_value=flow), \
             mock.patch.object(customer_oidc, "_provider_config", return_value={"clientId": "c", "clientSecret": "s"}), \
             mock.patch.object(customer_oidc, "_verify_id_token", return_value={"sub": "m", "preferred_username": "x@example.test"}), \
             mock.patch.object(customer_oidc.customer_accounts, "create_from_verified_identity") as create:
            with self.assertRaises(customer_oidc.CustomerOIDCError):
                customer_oidc.complete("microsoft", "s", "code", browser_binding="b" * 43, origin="https://x", poster=lambda *a, **k: response)
        create.assert_not_called()


class DashboardJsonEscapingTest(_Stores):
    def test_vehicle_text_cannot_close_the_script_element(self):
        account = {"ok": True, "accountId": "a", "kind": "individual", "displayName": "A", "email": "a@example.test",
                   "companyName": "", "siret": "", "phone": "", "addressLine1": "", "addressLine2": "", "postalCode": "",
                   "city": "", "contactDetailsComplete": True, "providers": ["google"],
                   "loyalty": {"referralCode": "R", "currency": "EUR", "balanceCents": 0, "pendingCents": 0,
                               "earnedReferrals": 0, "pendingReferrals": 0},
                   "vehicles": [{"make": "</script><img src=x onerror=alert(1)>", "model": "A&B"}]}
        page = http._dashboard_page("t" * 43, account, "nonce").decode("utf-8")
        self.assertNotIn("</script><img", page)
        self.assertIn("\\u003c/script\\u003e", page)
        start = page.index("\\u003c/script")
        # The escaped payload still decodes to the original value as JSON.
        line = page[page.rfind("[", 0, start):page.index("]", start) + 1]
        self.assertEqual(json.loads(line)[0]["make"], "</script><img src=x onerror=alert(1)>")


if __name__ == "__main__":
    unittest.main()
