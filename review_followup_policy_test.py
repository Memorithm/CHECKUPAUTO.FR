import datetime
import os
import tempfile
import unittest
from unittest.mock import patch

_TMP = tempfile.TemporaryDirectory()
os.environ["CYBERCHECK_DATA_DIR"] = _TMP.name

import review_followup as followup
import mercure_admin_client as mercure


class ReviewFollowupPolicyTest(unittest.TestCase):
    def test_mercure_email_sender_is_disabled(self):
        with self.assertRaises(RuntimeError):
            mercure.send_google_review_email("123")

    @patch.object(followup.mercure, "session_status", return_value={"connected": True})
    @patch.object(
        followup.mercure,
        "native_review_email_status",
        return_value={"nativeFavorableOnlyEmailEnabled": False},
    )
    def test_waits_until_exact_mercure_email_field_is_verified(self, _native, _session):
        with patch.dict(os.environ, {}, clear=True):
            result = followup.process_once()
        self.assertEqual(result["state"], "waiting_mercure_email_field")
    @patch.object(followup, "_mark")
    @patch.object(followup, "_state", return_value=None)
    @patch.object(followup.mail, "send_email")
    @patch.object(followup.mercure, "send_google_review_email")
    @patch.object(followup.mercure, "review_followup_rows")
    @patch.object(
        followup.mercure,
        "native_review_email_status",
        return_value={"nativeFavorableOnlyEmailEnabled": False},
    )
    @patch.object(followup.mercure, "session_status", return_value={"connected": True})
    def test_uses_checkupauto_mail_gateway_only(
        self,
        _session,
        _native,
        rows,
        mercure_send,
        own_send,
        _state,
        mark,
    ):
        now = datetime.datetime.now(datetime.timezone.utc)
        rows.return_value = [{
            "id": "42",
            "dateRdv": (now - datetime.timedelta(hours=1)).isoformat(),
            "honored": True,
            "finished": True,
            "name": "Client",
            "email": "client@example.fr",
        }]
        env = {
            "CYBERCHECK_MERCURE_CUSTOMER_EMAIL_FIELD": "verified_email_field",
            "CYBERCHECK_SMTP_FROM": "rappel@checkupauto.fr",
            "CYBERCHECK_GOOGLE_REVIEW_URL": "https://g.page/r/checkupauto/review",
        }
        with patch.dict(os.environ, env, clear=True):
            result = followup.process_once()

        self.assertTrue(result["ok"])
        self.assertEqual(result["sent"], 1)
        own_send.assert_called_once()
        mercure_send.assert_not_called()
        mark.assert_called_once_with("42", "sent")


if __name__ == "__main__":
    unittest.main()
