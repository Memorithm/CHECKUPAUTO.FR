import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import review_followup as followup


class ReviewFollowupBoundaryTest(unittest.TestCase):
    def test_native_policy_failure_does_not_expose_exception_text(self):
        leaked = "client@example.fr bearer_secret=SUPER-SECRET-VALUE"
        with (
            patch.object(followup.mercure, "session_status", return_value={"connected": True}),
            patch.object(
                followup.mercure,
                "native_review_email_status",
                return_value={"nativeFavorableOnlyEmailEnabled": True},
            ),
            patch.object(
                followup.mercure,
                "disable_native_review_email_automation",
                side_effect=RuntimeError(leaked),
            ),
        ):
            result = followup.process_once()
        self.assertEqual(result["state"], "native_positive_only_enabled")
        self.assertEqual(result["error"], "Politique avis Mercure non modifiable")
        self.assertNotIn("client@example.fr", repr(result))
        self.assertNotIn("SUPER-SECRET-VALUE", repr(result))

    def test_invalid_email_transport_does_not_expose_exception_text(self):
        leaked = "smtp://user:password@example.invalid SECRET-TOKEN"
        with (
            patch.object(followup.mercure, "session_status", return_value={"connected": True}),
            patch.object(
                followup.mercure,
                "native_review_email_status",
                return_value={"nativeFavorableOnlyEmailEnabled": False},
            ),
            patch.object(followup.mail, "configured", side_effect=ValueError(leaked)),
        ):
            result = followup.process_once()
        self.assertEqual(result["state"], "invalid_email_transport")
        self.assertEqual(result["error"], "Transport email Checkup Auto invalide")
        self.assertNotIn("password", repr(result))
        self.assertNotIn("SECRET-TOKEN", repr(result))

    def test_status_survives_invalid_email_transport_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            with (
                patch.object(followup, "DATA_DIR", data_dir),
                patch.object(followup, "DB", data_dir / "review-followup.sqlite3"),
                patch.object(followup.mercure, "session_status", return_value={"connected": False}),
                patch.object(followup.mail, "configured", side_effect=ValueError("SECRET")),
                patch.object(followup.mail, "preflight", side_effect=ValueError("SECRET")),
                patch.object(followup.notifications, "status", return_value={}),
            ):
                followup.init_db()
                result = followup.status()
        self.assertFalse(result["emailTransportConfigured"])
        self.assertFalse(result["emailTransportReady"])
        self.assertEqual(result["emailPreflightState"], "unavailable")
        self.assertNotIn("SECRET", repr(result))


if __name__ == "__main__":
    unittest.main()
