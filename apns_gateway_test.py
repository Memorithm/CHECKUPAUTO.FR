import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import apns_gateway as apns


class Response:
    def __init__(self, status, reason, headers=None):
        self.status_code = status
        self._reason = reason
        self.headers = headers or {}

    def json(self):
        return {"reason": self._reason}


class APNSGatewayTest(unittest.TestCase):
    def test_unregistered_is_terminal_for_device_token(self):
        error = apns._error_from_response(Response(410, "Unregistered", {"apns-id": "id-1"}))
        self.assertTrue(error.token_invalid)
        self.assertFalse(error.retryable)
        self.assertFalse(error.provider_error)
        self.assertEqual(error.apns_id, "id-1")

    def test_bad_device_token_is_terminal(self):
        error = apns._error_from_response(Response(400, "BadDeviceToken"))
        self.assertTrue(error.token_invalid)
        self.assertFalse(error.provider_error)

    def test_topic_mismatch_is_provider_configuration_error_not_token_retirement(self):
        error = apns._error_from_response(Response(400, "DeviceTokenNotForTopic"))
        self.assertFalse(error.token_invalid)
        self.assertTrue(error.provider_error)
        self.assertFalse(error.retryable)

    @patch.object(apns.Path, "is_file", side_effect=PermissionError("denied"))
    def test_status_treats_unreadable_private_directory_as_unconfigured(self, _is_file):
        state = apns.status()
        self.assertFalse(state["configured"])
        self.assertFalse(state["keyPresent"])
        self.assertEqual(state["state"], "awaiting_credentials")

    def test_service_and_rate_limit_errors_are_retryable(self):
        for status, reason in ((429, "TooManyRequests"), (500, "InternalServerError"), (503, "ServiceUnavailable")):
            with self.subTest(status=status):
                error = apns._error_from_response(Response(status, reason, {"retry-after": "60"}))
                self.assertTrue(error.retryable)
                self.assertFalse(error.token_invalid)
                self.assertEqual(error.retry_after, "60")


    def test_preflight_validates_p256_signing_key_without_push(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        with TemporaryDirectory() as tmp:
            key_path = Path(tmp) / "AuthKey_TEST.p8"
            key = ec.generate_private_key(ec.SECP256R1())
            key_path.write_bytes(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ))
            cfg = {"keyId": "ABC123DEFG", "teamId": "DEF123GHIJ", "keyPath": str(key_path), "topic": "fr.checkupauto.reminder"}
            with patch.object(apns, "_config", return_value=cfg):
                state = apns.preflight()
        self.assertTrue(state["ready"])
        self.assertTrue(state["keyValid"])
        self.assertEqual(state["reason"], "local_signing_validated")

    def test_preflight_rejects_non_p256_signing_key(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        with TemporaryDirectory() as tmp:
            key_path = Path(tmp) / "AuthKey_TEST.p8"
            key = ec.generate_private_key(ec.SECP384R1())
            key_path.write_bytes(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ))
            cfg = {"keyId": "ABC123DEFG", "teamId": "DEF123GHIJ", "keyPath": str(key_path), "topic": "fr.checkupauto.reminder"}
            with patch.object(apns, "_config", return_value=cfg):
                state = apns.preflight()
        self.assertFalse(state["ready"])
        self.assertFalse(state["keyValid"])
        self.assertEqual(state["state"], "invalid_configuration")


if __name__ == "__main__":
    unittest.main()
