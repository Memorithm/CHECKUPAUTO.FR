import datetime
import os
import tempfile
import unittest
from unittest.mock import ANY, patch

_TMP = tempfile.TemporaryDirectory()
os.environ["CYBERCHECK_DATA_DIR"] = _TMP.name

import review_followup as followup
import mercure_admin_client as mercure


class ReviewFollowupPolicyTest(unittest.TestCase):
    def test_mercure_email_sender_is_disabled(self):
        with self.assertRaises(RuntimeError):
            mercure.send_google_review_email("123")

    @patch.object(followup, "_mark")
    @patch.object(followup, "_state", return_value=None)
    @patch.object(followup.notifications, "send_email")
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
        own_send.return_value = {"ok": True, "status": "sent", "inFlight": False}
        rows.return_value = [{
            "id": "42",
            "dateRdv": (now - datetime.timedelta(hours=1)).isoformat(),
            "honored": True,
            "finished": True,
            "name": "Client",
            "email": "client@example.fr",
        }]
        env = {"CYBERCHECK_GOOGLE_REVIEW_URL": "https://g.page/r/checkupauto/review"}
        with patch.dict(os.environ, env, clear=True), patch.object(followup.mail, "configured", return_value=True):
            result = followup.process_once()

        self.assertTrue(result["ok"])
        self.assertEqual(result["sent"], 1)
        own_send.assert_called_once_with(
            "client@example.fr", "Votre avis sur Checkup Auto", ANY, ANY,
            category="google_review", reference="42",
        )
        mercure_send.assert_not_called()
        mark.assert_called_once_with("42", "sent")


if __name__ == "__main__":
    unittest.main()
