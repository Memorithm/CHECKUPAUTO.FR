import unittest
from unittest import mock

import mobile_devices


INSTALLATION_ID = "11111111-1111-1111-1111-111111111111"
REGISTRATION_SECRET = "s" * 32


class _Cursor:
    def fetchone(self):
        return None


class _DB:
    def __init__(self):
        self.execute = mock.Mock(return_value=_Cursor())


class _Context:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, exc_type, exc, tb):
        return False


class MobileDevicePrivacyBoundaryTests(unittest.TestCase):
    def test_installation_registration_fails_closed_before_database_write(self):
        with mock.patch.object(mobile_devices.privacy, "is_suppressed", return_value=True) as suppressed, \
             mock.patch.object(mobile_devices, "init_db") as init_db:
            with self.assertRaisesRegex(PermissionError, "traitement mobile refusé"):
                mobile_devices.register_installation({"installationId": INSTALLATION_ID})

        suppressed.assert_called_once_with("installation", INSTALLATION_ID, "all_processing")
        init_db.assert_not_called()

    def test_apns_registration_cannot_reactivate_suppressed_installation(self):
        with mock.patch.object(mobile_devices.privacy, "is_suppressed", return_value=True) as suppressed, \
             mock.patch.object(mobile_devices, "init_db") as init_db:
            with self.assertRaisesRegex(PermissionError, "traitement mobile refusé"):
                mobile_devices.register({"installationId": INSTALLATION_ID})

        suppressed.assert_called_once_with("installation", INSTALLATION_ID, "all_processing")
        init_db.assert_not_called()

    def test_authenticated_mobile_boundary_checks_suppression_before_read(self):
        db = _DB()
        with mock.patch.object(mobile_devices.privacy, "is_suppressed", return_value=True):
            with self.assertRaisesRegex(PermissionError, "traitement mobile refusé"):
                mobile_devices._authenticated_installation(db, INSTALLATION_ID, "unused")

        db.execute.assert_not_called()

    def test_authoritative_sync_cannot_repopulate_suppressed_installation(self):
        with mock.patch.object(mobile_devices.privacy, "is_suppressed", return_value=True) as suppressed, \
             mock.patch.object(mobile_devices, "init_db") as init_db:
            with self.assertRaisesRegex(PermissionError, "traitement mobile refusé"):
                mobile_devices.sync_authoritative_deadlines(INSTALLATION_ID, [])

        suppressed.assert_called_once_with("installation", INSTALLATION_ID, "all_processing")
        init_db.assert_not_called()

    def test_cleanup_primitives_remain_available_under_suppression(self):
        db = _DB()
        context = _Context(db)
        payload = {
            "installationId": INSTALLATION_ID,
            "registrationSecret": REGISTRATION_SECRET,
        }
        with mock.patch.object(mobile_devices, "_assert_processing_allowed", side_effect=AssertionError("cleanup blocked")) as guard, \
             mock.patch.object(mobile_devices, "init_db"), \
             mock.patch.object(mobile_devices, "connect", return_value=context):
            self.assertEqual(mobile_devices.unregister(payload), {"ok": True, "removed": False})
            self.assertEqual(mobile_devices.delete_installation(payload), {"ok": True, "removed": False})

        guard.assert_not_called()


if __name__ == "__main__":
    unittest.main()
