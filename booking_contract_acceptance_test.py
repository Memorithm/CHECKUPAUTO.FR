import os
import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import booking_bridge as booking
import compliance_store as compliance


class BookingContractAcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old_db = analytics.DB
        self.old_secret = booking.SECRET_FILE
        self.old_data_dir = os.environ.get("CYBERCHECK_DATA_DIR")
        analytics.DB = root / "analytics.sqlite3"
        booking.SECRET_FILE = root / "mercure-webhook-secret"
        os.environ["CYBERCHECK_DATA_DIR"] = str(root)
        analytics.init_db()
        booking.init_db()
        compliance.save_document({
            "type": "terms",
            "version": "2026-09",
            "title": "Conditions générales de vente",
            "body": "Conditions générales de vente de qualification. " * 8,
            "action": "publish",
        })

    def tearDown(self):
        analytics.DB = self.old_db
        booking.SECRET_FILE = self.old_secret
        if self.old_data_dir is None:
            os.environ.pop("CYBERCHECK_DATA_DIR", None)
        else:
            os.environ["CYBERCHECK_DATA_DIR"] = self.old_data_dir
        self.tmp.cleanup()

    def intent(self):
        return booking.create_intent(
            {
                "referrer": "",
                "utmSource": "",
                "utmCampaign": "",
                "device": "desktop",
                "path": "/",
                "service": "Contrôle technique",
            },
            "https://rdv.checkupauto.fr/",
        )

    def acceptance_payload(self, intent):
        terms = compliance.published_document("terms")
        return {
            "ccid": intent["token"],
            "cct": booking.browser_token(intent["token"]),
            "termsVersion": terms["version"],
            "termsContentHash": terms["contentHash"],
            "accepted": True,
            "reviewed": True,
            "immediatePerformance": False,
        }

    def test_review_page_requires_explicit_unticked_acceptance(self):
        intent = self.intent()
        page = booking.auto_submit_html(intent["token"], "Contrôle technique", "nonce").decode()
        self.assertIn('id="terms" type="checkbox"', page)
        self.assertNotIn('id="terms" type="checkbox" checked', page)
        self.assertIn('id="continue" type="submit" disabled', page)
        self.assertIn("/api/booking/accept-terms", page)
        self.assertIn("/cgv", page)
        self.assertIn("Modifier mon choix", page)

    def test_browser_confirmation_fails_closed_without_acceptance(self):
        intent = self.intent()
        with self.assertRaises(PermissionError):
            booking.browser_confirmation({
                "ccid": intent["token"],
                "cct": booking.browser_token(intent["token"]),
                "route": "/confirmation",
            })

    def test_acceptance_is_promoted_to_contract_receipt_on_confirmation(self):
        intent = self.intent()
        acceptance = booking.record_terms_acceptance(self.acceptance_payload(intent))
        self.assertTrue(acceptance["reviewed"])
        result = booking.browser_confirmation({
            "ccid": intent["token"],
            "cct": booking.browser_token(intent["token"]),
            "route": "/confirmation",
        })
        self.assertTrue(result["contractAcceptanceBound"])
        receipts = compliance.consent_receipts()
        receipt = next(row for row in receipts if row["contractRef"] == result["externalId"])
        terms = compliance.published_document("terms")
        self.assertEqual(receipt["documentVersion"], terms["version"])
        self.assertEqual(receipt["contentHash"], terms["contentHash"])


if __name__ == "__main__":
    unittest.main()
