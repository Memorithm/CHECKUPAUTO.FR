import ast
import datetime
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, patch

_TMP = tempfile.TemporaryDirectory()
os.environ["CYBERCHECK_DATA_DIR"] = _TMP.name

import review_followup as followup
import mercure_admin_client as mercure


class ReviewFollowupPolicyTest(unittest.TestCase):
    def test_import_has_no_database_side_effect(self):
        tree = ast.parse(Path("review_followup.py").read_text())
        module_init_calls = [
            node for node in tree.body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "init_db"
        ]
        self.assertEqual(module_init_calls, [])

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
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(followup.mail, "configured", return_value=True),
            patch.object(followup.mail, "preflight", return_value={"ok": True, "state": "ready"}),
        ):
            result = followup.process_once()

        self.assertTrue(result["ok"])
        self.assertEqual(result["sent"], 1)
        own_send.assert_called_once_with(
            "client@example.fr", "Votre avis sur Checkup Auto", ANY, ANY,
            category="google_review", reference="42",
        )
        mercure_send.assert_not_called()
        mark.assert_called_once_with("42", "sent")


    @patch.object(followup.mercure, "review_followup_rows")
    @patch.object(
        followup.mercure,
        "native_review_email_status",
        return_value={"nativeFavorableOnlyEmailEnabled": False},
    )
    @patch.object(followup.mercure, "session_status", return_value={"connected": True})
    def test_preflight_blocks_delivery_attempts_before_reading_recipients(self, _session, _native, rows):
        env = {"CYBERCHECK_GOOGLE_REVIEW_URL": "https://g.page/r/checkupauto/review"}
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(followup.mail, "configured", return_value=True),
            patch.object(followup.mail, "preflight", return_value={"ok": False, "state": "awaiting_credentials"}),
            patch.object(followup.notifications, "send_email") as send_email,
        ):
            result = followup.process_once()

        self.assertFalse(result["ok"])
        self.assertEqual(result["state"], "waiting_email_preflight")
        self.assertEqual(result["preflightState"], "awaiting_credentials")
        rows.assert_not_called()
        send_email.assert_not_called()

    def test_status_rejects_invalid_review_url_and_reports_preflight_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            with (
                patch.object(followup, "DATA_DIR", data_dir),
                patch.object(followup, "DB", data_dir / "review-followup.sqlite3"),
            ):
                followup.init_db()
                with (
                    patch.dict(os.environ, {"CYBERCHECK_GOOGLE_REVIEW_URL": "https://example.com/review"}, clear=True),
                    patch.object(followup.mercure, "session_status", return_value={"connected": False}),
                    patch.object(followup.mail, "configured", return_value=True),
                    patch.object(followup.mail, "preflight", return_value={"ok": False, "state": "provider_unavailable"}),
                    patch.object(followup.notifications, "status", return_value={}),
                ):
                    result = followup.status()

        self.assertFalse(result["reviewUrlConfigured"])
        self.assertFalse(result["emailTransportReady"])
        self.assertEqual(result["emailPreflightState"], "provider_unavailable")



if __name__ == "__main__":
    unittest.main()
