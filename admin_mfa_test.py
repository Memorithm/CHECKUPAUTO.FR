import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import admin_mfa as mfa


class AdminMFATest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(
            os.environ,
            {
                "CYBERCHECK_PRIVATE_DIR": str(self.root / "private"),
                "CYBERCHECK_ADMIN_MFA_DIR": str(self.root / "mfa"),
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_rfc6238_sha1_vector(self):
        secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
        self.assertEqual(
            mfa.totp_at(secret, 59, digits=8, period=30),
            "94287082",
        )

    def test_totp_accepts_current_and_adjacent_step_only(self):
        secret = mfa.generate_secret()
        now = 1_700_000_000
        current = mfa.totp_at(secret, now)
        previous = mfa.totp_at(secret, now - 30)
        too_old = mfa.totp_at(secret, now - 90)
        self.assertTrue(mfa.verify_totp(secret, current, now=now))
        self.assertTrue(mfa.verify_totp(secret, previous, now=now))
        self.assertFalse(mfa.verify_totp(secret, too_old, now=now))
        self.assertFalse(mfa.verify_totp(secret, "12345x", now=now))

    def test_enrollment_secret_and_pending_file_are_private(self):
        started = mfa.begin_enrollment(now=1000)
        self.assertIn("otpauth://totp/", started["otpauthUri"])
        self.assertIn("issuer=CheckupAuto", started["otpauthUri"])
        self.assertEqual(started["expiresAt"], 1000 + mfa.PENDING_TTL_SECONDS)
        path = mfa._pending_path()
        self.assertTrue(path.is_file())
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_pending_qr_contains_png_without_exposing_secret_to_disk(self):
        mfa.begin_enrollment(now=1000)
        png = mfa.pending_qr_png()
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        files = {p.name for p in mfa._mfa_dir().iterdir()}
        self.assertEqual(files, {"totp-pending.json"})

    def test_confirm_enrollment_creates_session_and_hashed_recovery_codes(self):
        started = mfa.begin_enrollment(now=1000)
        code = mfa.totp_at(started["secret"], 1030)
        result = mfa.confirm_enrollment(code, now=1030)

        self.assertTrue(mfa.configured())
        self.assertTrue(mfa.validate_session(result["sessionToken"], now=1030))
        self.assertEqual(len(result["recoveryCodes"]), 10)
        self.assertEqual(result["recoveryRemaining"], 10)

        recovery_raw = mfa._recovery_path().read_text(encoding="utf-8")
        for code_value in result["recoveryCodes"]:
            self.assertNotIn(code_value, recovery_raw)
            self.assertNotIn(code_value.replace("-", ""), recovery_raw)
        payload = json.loads(recovery_raw)
        self.assertEqual(len(payload["hashes"]), 10)
        self.assertTrue(all(len(value) == 64 for value in payload["hashes"]))
        self.assertEqual(mfa._secret_path().stat().st_mode & 0o777, 0o600)
        self.assertEqual(mfa._session_key_path().stat().st_mode & 0o777, 0o600)

    def test_recovery_code_is_single_use(self):
        started = mfa.begin_enrollment(now=1000)
        enrolled = mfa.confirm_enrollment(
            mfa.totp_at(started["secret"], 1030),
            now=1030,
        )
        recovery = enrolled["recoveryCodes"][0]

        first = mfa.verify_login(recovery, now=1060)
        self.assertTrue(first["usedRecoveryCode"])
        self.assertEqual(first["recoveryRemaining"], 9)
        self.assertTrue(mfa.validate_session(first["sessionToken"], now=1060))

        with self.assertRaises(PermissionError):
            mfa.verify_login(recovery, now=1090)

    def test_session_rejects_tampering_and_expiry(self):
        started = mfa.begin_enrollment(now=1000)
        enrolled = mfa.confirm_enrollment(
            mfa.totp_at(started["secret"], 1030),
            now=1030,
        )
        token = enrolled["sessionToken"]
        self.assertTrue(mfa.validate_session(token, now=1030))
        self.assertFalse(
            mfa.validate_session(token + "x", now=1030)
        )
        self.assertFalse(
            mfa.validate_session(
                token,
                now=1030 + mfa.SESSION_TTL_SECONDS + 1,
            )
        )

    def test_session_cookie_is_secure_http_only_and_strict(self):
        started = mfa.begin_enrollment(now=1000)
        enrolled = mfa.confirm_enrollment(
            mfa.totp_at(started["secret"], 1030),
            now=1030,
        )
        cookie = mfa.session_cookie(enrolled["sessionToken"])
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertIn("Path=/admin", cookie)
        token = mfa.token_from_cookie(cookie)
        self.assertEqual(token, enrolled["sessionToken"])

    def test_expired_pending_enrollment_is_destroyed(self):
        started = mfa.begin_enrollment(now=1000)
        code = mfa.totp_at(started["secret"], 1000)
        with self.assertRaisesRegex(RuntimeError, "expiré"):
            mfa.confirm_enrollment(
                code,
                now=1000 + mfa.PENDING_TTL_SECONDS + 1,
            )
        self.assertFalse(mfa._pending_path().exists())
        self.assertFalse(mfa.configured())


if __name__ == "__main__":
    unittest.main()
