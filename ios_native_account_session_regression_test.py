"""Native account and foreground-session regression contracts.

The cookie-backed /compte page is deliberately separate from the mobile bearer
API; iOS must never open it to show an already authenticated customer account.
"""
import unittest
from pathlib import Path
from unittest.mock import patch

import customer_http as http
import security_guard


ROOT = Path(__file__).resolve().parent
IOS = ROOT / "ios/CheckupAutoReminder/Sources"


class Handler:
    def __init__(self, path, method="GET", token="a" * 64, query=""):
        self.path = path + query
        self.command = method
        self.headers = {"Authorization": "Bearer " + token} if token else {}
        self.response = None

    def send_json(self, body, status=200):
        self.response = (status, body)


class NativeAccountHttpTests(unittest.TestCase):
    def test_profile_is_bound_to_exact_authenticated_account_and_minimized(self):
        handler = Handler(http.MOBILE_ACCOUNT_PROFILE_ROUTE)
        account = {
            "accountId": "account-verified", "displayName": "Cliente",
            "email": "client@example.test", "kind": "individual",
            "phone": "0102030405", "loyalty": {"balanceCents": 1400},
            "vehicles": [{"vin": "private-vin"}], "siret": "secret-data",
        }
        with patch.object(http.customer_accounts, "authenticate_session", return_value="account-verified") as auth, \
             patch.object(http.customer_accounts, "profile", return_value=account) as get_profile:
            self.assertTrue(http.handle(handler))
        self.assertEqual(handler.response, (200, {
            "ok": True, "accountId": "account-verified", "displayName": "Cliente",
            "email": "client@example.test", "kind": "individual",
            "phone": "0102030405",
        }))
        auth.assert_called_once_with("a" * 64)
        get_profile.assert_called_once_with("account-verified")
        self.assertNotIn("siret", handler.response[1])
        self.assertNotIn("loyalty", handler.response[1])
        self.assertNotIn("vehicles", handler.response[1])

    def test_no_cookie_only_or_invalid_bearer_ever_exposes_profile(self):
        for supplied in ("", "bad"):
            with self.subTest(token=supplied):
                handler = Handler(http.MOBILE_ACCOUNT_PROFILE_ROUTE, token=supplied)
                handler.headers["Cookie"] = "checkupauto_customer=browser-token"
                with patch.object(http.customer_accounts, "profile") as get_profile:
                    self.assertTrue(http.handle(handler))
                    self.assertEqual(handler.response[0], 401)
                    get_profile.assert_not_called()

    def test_expired_session_is_forbidden_and_unavailable_is_distinct(self):
        handler = Handler(http.MOBILE_ACCOUNT_PROFILE_ROUTE)
        with patch.object(http.customer_accounts, "authenticate_session", side_effect=PermissionError):
            http.handle(handler)
        self.assertEqual(handler.response[0], 401)
        handler = Handler(http.MOBILE_ACCOUNT_PROFILE_ROUTE)
        with patch.object(http.customer_accounts, "authenticate_session", return_value="account-verified"), \
             patch.object(http.customer_accounts, "profile", side_effect=RuntimeError):
            http.handle(handler)
        self.assertEqual(handler.response[0], 503)

    def test_profile_disallows_queries_and_mutating_method(self):
        handler = Handler(http.MOBILE_ACCOUNT_PROFILE_ROUTE, query="?expose=true")
        with patch.object(http.customer_accounts, "authenticate_session") as auth:
            http.handle(handler)
            self.assertEqual(handler.response[0], 401)
            auth.assert_not_called()
        handler = Handler(http.MOBILE_ACCOUNT_PROFILE_ROUTE, method="POST")
        with patch.object(http.customer_accounts, "authenticate_session") as auth:
            http.handle(handler)
            self.assertEqual(handler.response[0], 405)
            auth.assert_not_called()

    def test_profile_rate_limited_like_native_vehicle_reads(self):
        self.assertLessEqual(security_guard._ENDPOINT_LIMITS[http.MOBILE_ACCOUNT_PROFILE_ROUTE], 30)


class NativeIOSSessionContracts(unittest.TestCase):
    def read(self, filename):
        return (IOS / filename).read_text(encoding="utf-8")

    def test_quick_account_button_and_toolbar_never_open_website_login(self):
        content = self.read("ContentView.swift")
        native = self.read("NativeCustomerAccountView.swift")
        self.assertNotIn("openInApp(model.accountURL)", content)
        self.assertIn("showingNativeAccount = true", content)
        self.assertIn("NativeCustomerAccountView()", content)
        self.assertIn("AuthenticatedCustomerDashboardWebView(", native)
        self.assertIn("NativeDashboardBridge.createBrowserCookie()", native)
        # The website now owns the precise account/profile presentation.
        self.assertNotIn("SFSafariViewController", native)
        self.assertNotIn('"/compte"', native)
        self.assertIn('MobileAPI.directMercureBookingURL', content)

    def test_foreground_outage_retains_current_authenticated_session(self):
        model = self.read("AppModel.swift")
        root = self.read("CheckupAutoReminderApp.swift")
        self.assertIn("let previouslySignedIn = customerSignedIn", model)
        self.assertIn("if !previouslySignedIn { authenticationResolving = true }", model)
        self.assertIn("guard CustomerSessionKeychain.load() == requestedToken else { return }", model)
        self.assertIn("sessionRecoveryRequired = true", model)
        self.assertIn("if !previouslySignedIn", model)
        self.assertIn("} catch {", model)
        self.assertIn("if model.sessionRecoveryRequired", root)
        self.assertIn("NativeSessionRecoveryView()", root)
        self.assertIn("model.retryCustomerSession()", root)
        self.assertIn('CustomerSessionKeychain.clear(ifMatching: token)', self.read("CustomerAccountAPI.swift"))
        self.assertIn("kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly", self.read("CustomerSessionKeychain.swift"))

    def test_native_profile_reads_authenticated_api_not_web_cookie(self):
        api = self.read("CustomerAccountAPI.swift")
        self.assertIn('"/api/mobile/account/profile"', api)
        self.assertIn('request.setValue("Bearer " + token', api)
        self.assertIn("cachePolicy = .reloadIgnoringLocalCacheData", api)


if __name__ == "__main__":
    unittest.main()
