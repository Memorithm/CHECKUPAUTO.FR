import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import admin_mfa
from admin_http_test_support import AdminHttpHarness


class MfaStateMixin:
    def isolate_mfa(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, {"CYBERCHECK_ADMIN_MFA_DIR": tmp.name}, clear=False)
        env.start(); self.addCleanup(env.stop)
        os.environ.pop(admin_mfa.REQUIRED_ENV, None)

    def enroll(self, now):
        enrollment = admin_mfa.begin_enrollment(now=now)
        secret = enrollment["secret"]
        result = admin_mfa.confirm_enrollment(admin_mfa.totp_at(secret, now), now=now)
        return secret, result


class AdminMfaHardeningTest(MfaStateMixin, unittest.TestCase):
    """S-09: single-use TOTP, server-side logout, shorter sessions, safe recovery."""

    def setUp(self):
        self.isolate_mfa()

    def test_session_lifetime_is_reduced(self):
        self.assertLessEqual(admin_mfa.SESSION_TTL_SECONDS, 2 * 3600)

    def test_totp_code_cannot_be_replayed(self):
        now = 1_800_000_000
        secret, _ = self.enroll(now)
        later = now + 60
        code = admin_mfa.totp_at(secret, later)
        admin_mfa.verify_login(code, now=later)
        with self.assertRaises(PermissionError):
            admin_mfa.verify_login(code, now=later)
        # An older (still in-window) step is also refused once a newer one was used.
        with self.assertRaises(PermissionError):
            admin_mfa.verify_login(admin_mfa.totp_at(secret, later - 30), now=later)
        # The next time-step works.
        admin_mfa.verify_login(admin_mfa.totp_at(secret, later + 30), now=later + 30)

    def test_enrollment_code_cannot_be_reused_for_login(self):
        now = 1_800_000_000
        secret, _ = self.enroll(now)
        with self.assertRaises(PermissionError):
            admin_mfa.verify_login(admin_mfa.totp_at(secret, now), now=now)

    def test_revoked_session_is_rejected_while_others_stay_valid(self):
        now = int(time.time())
        secret, result = self.enroll(now)
        first = result["sessionToken"]
        second = admin_mfa.issue_session(now=now)
        self.assertTrue(admin_mfa.validate_session(first))
        self.assertTrue(admin_mfa.revoke_session(first))
        self.assertFalse(admin_mfa.validate_session(first))
        self.assertTrue(admin_mfa.validate_session(second))
        self.assertFalse(admin_mfa.revoke_session("forged.token"))

    def test_recovery_code_is_consumed_once_under_concurrency(self):
        now = 1_800_000_000
        _, result = self.enroll(now)
        code = result["recoveryCodes"][0]
        outcomes = []
        barrier = threading.Barrier(6)

        def attempt():
            barrier.wait()
            try:
                admin_mfa.verify_login(code, now=now + 120)
                outcomes.append(True)
            except PermissionError:
                outcomes.append(False)

        threads = [threading.Thread(target=attempt) for _ in range(6)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(outcomes.count(True), 1)
        self.assertEqual(admin_mfa.recovery_remaining(), len(result["recoveryCodes"]) - 1)

    def test_required_flag_is_opt_in(self):
        self.assertFalse(admin_mfa.required())
        with patch.dict(os.environ, {admin_mfa.REQUIRED_ENV: "1"}):
            self.assertTrue(admin_mfa.required())


class AdminMfaHttpTest(MfaStateMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = AdminHttpHarness()

    @classmethod
    def tearDownClass(cls):
        cls.http.close()

    def setUp(self):
        self.isolate_mfa()

    def test_required_mode_blocks_admin_api_until_enrolled_but_allows_enrollment(self):
        status, _, _ = self.http.request("GET", "/api/admin/auth/2fa/status")
        self.assertEqual(status, 200)
        with patch.dict(os.environ, {admin_mfa.REQUIRED_ENV: "1"}):
            status, body, _ = self.http.request("GET", "/api/admin/deployment/status")
            self.assertEqual(status, 403)
            self.assertEqual(body["error"], "two_factor_required")
            status, body, _ = self.http.request("POST", "/api/admin/auth/2fa/setup", {})
            self.assertEqual(status, 200, body)
            self.assertTrue(body["enrollment"]["secret"])

    def test_default_mode_keeps_basic_only_access_when_not_enrolled(self):
        status, body, _ = self.http.request("GET", "/api/admin/deployment/status")
        self.assertNotEqual(status, 403, body)

    def test_logout_invalidates_mfa_session_server_side(self):
        now = int(time.time())
        _, result = self.enroll(now)
        cookie = admin_mfa.COOKIE_NAME + "=" + result["sessionToken"]
        status, _, _ = self.http.request("GET", "/api/admin/auth/2fa/status", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertTrue(admin_mfa.validate_session(result["sessionToken"]))
        status, _, _ = self.http.request("POST", "/api/admin/auth/2fa/logout", {}, cookie=cookie)
        self.assertEqual(status, 200)
        # Replaying the old cookie no longer passes the second factor.
        status, body, _ = self.http.request("GET", "/api/admin/deployment/status", cookie=cookie)
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "two_factor_required")


if __name__ == "__main__":
    unittest.main()
