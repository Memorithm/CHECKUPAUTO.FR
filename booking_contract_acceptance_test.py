import os
import tempfile
import unittest
from unittest.mock import patch
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
            "immediatePerformance": True,
        }

    def test_review_page_requires_explicit_unticked_acceptance(self):
        intent = self.intent()
        page = booking.auto_submit_html(intent["token"], "Contrôle technique", "nonce").decode()
        self.assertIn('id="terms" type="checkbox"', page)
        self.assertNotIn('id="terms" type="checkbox" checked', page)
        self.assertIn('id="continue" type="submit" disabled', page)
        self.assertIn("/api/booking/accept-terms", page)
        self.assertIn('<a href="/cgv">conditions générales de vente</a>', page)
        self.assertNotIn('href="/cgv" target="_blank"', page)
        self.assertIn("Modifier mon choix", page)

    def test_review_page_shows_selected_vehicle_without_card_grise_secret(self):
        intent=self.intent()
        page=booking.auto_submit_html(
            intent["token"],"Contrôle technique","nonce",
            vehicle={
                "vehicleId":"11111111-1111-4111-8111-111111111111",
                "registrationSystem":"siv","registration":"AA-123-AA",
                "formulaNumberPresent":True,
            },
        ).decode()
        self.assertIn("Véhicule : SIV · AA-123-AA",page)
        self.assertNotIn("formula",page.lower())
        self.assertNotIn("AB12CD34EF5",page)

    def test_review_uses_actual_provider_promotion_for_selected_slot(self):
        intent=booking.create_intent({
            'service':'Contrôle technique','preferredDate':'2026-10-12',
            'preferredTime':'15:30',
        },'https://rdv.checkupauto.fr/')
        provider={'days':[{'date':'2026-10-12','slots':[
            {'time':'15:30','price':75.0,'saving':5.0},
        ]}]}
        with patch('mercure_public_client.availability',return_value=provider) as check:
            page=booking.auto_submit_html(
                intent['token'],'Contrôle technique','nonce').decode()
        check.assert_called_once_with('technical','2026-10-12')
        self.assertIn('Tarif du créneau constaté dans Mercure : 75 € TTC',page)
        self.assertIn('le tarif final est celui confirmé avant le paiement',page)
        self.assertNotIn('Prix affiché : 80 €',page)

    def test_provider_failure_never_displays_an_unverified_saving(self):
        intent=booking.create_intent({
            'service':'Contrôle technique','preferredDate':'2026-10-12',
            'preferredTime':'15:30',
        },'https://rdv.checkupauto.fr/')
        with patch('mercure_public_client.availability',side_effect=RuntimeError('Mercure unavailable')):
            page=booking.auto_submit_html(
                intent['token'],'Contrôle technique','nonce').decode()
        self.assertIn('Tarif standard indicatif : 80 € TTC',page)
        self.assertNotIn('75 € TTC',page)

    def test_early_performance_acknowledgement_is_required_server_side(self):
        intent = self.intent()
        payload = self.acceptance_payload(intent)
        payload["immediatePerformance"] = False
        with self.assertRaises(ValueError):
            booking.record_terms_acceptance(payload)
        page = booking.auto_submit_html(intent["token"], "Contrôle technique", "nonce").decode()
        self.assertIn("après exécution complète de la prestation", page)
        self.assertIn("requiresImmediate=true", page)

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
        self.assertEqual(receipt["source"], "mercure_contract_confirmation")

    def test_public_conversion_payload_cannot_select_synthetic_receipt_source(self):
        intent = self.intent()
        booking.record_terms_acceptance(self.acceptance_payload(intent))
        result = booking.apply_conversion({
            "externalId": "provider-contract-1",
            "status": "confirmed",
            "ccid": intent["token"],
            "service": "Contrôle technique",
            "amount": 80,
            "acceptanceSource": "staging_synthetic_mercure_contract_confirmation",
        })
        self.assertTrue(result["contractAcceptanceBound"])
        receipt = compliance.contract_acceptance_receipt("provider-contract-1")
        self.assertEqual(receipt["source"], "mercure_contract_confirmation")

    def test_contract_receipt_source_cannot_drift_for_same_contract(self):
        intent = self.intent()
        booking.record_terms_acceptance(self.acceptance_payload(intent))
        compliance.finalize_checkout_acceptance(
            intent["token"],
            "provider-contract-2",
            source="staging_synthetic_mercure_contract_confirmation",
        )
        with self.assertRaisesRegex(ValueError, "provenance"):
            compliance.finalize_checkout_acceptance(
                intent["token"],
                "provider-contract-2",
                source="mercure_contract_confirmation",
            )


if __name__ == "__main__":
    unittest.main()
