import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import notification_broker as broker


class NotificationPushEnvironmentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_dir, self.old_db = broker.DATA_DIR, broker.DB
        broker.DATA_DIR = Path(self.tmp.name)
        broker.DB = broker.DATA_DIR / "broker.sqlite3"
        broker.init_db()

    def tearDown(self):
        broker.DATA_DIR, broker.DB = self.old_dir, self.old_db
        self.tmp.cleanup()

    @patch.object(broker.push_transport, "send")
    def test_same_token_in_two_apns_environments_has_distinct_delivery_identity(self, send_push):
        send_push.return_value = {"ok": True}
        device_token = "cd" * 32
        broker.send_push(device_token, "Rappel", "Message", category="ct_due", reference="mobile-env", environment="sandbox")
        broker.send_push(device_token, "Rappel", "Message", category="ct_due", reference="mobile-env", environment="production")
        self.assertEqual(send_push.call_count, 2)
        self.assertEqual(send_push.call_args_list[0].kwargs.get("environment"), "sandbox")
        self.assertEqual(send_push.call_args_list[1].kwargs.get("environment"), "production")


if __name__ == "__main__":
    unittest.main()
