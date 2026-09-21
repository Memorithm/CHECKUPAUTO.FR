import datetime
from pathlib import Path
import tempfile
import unittest

import compliance_store as compliance


class ComplianceStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "compliance.sqlite3"
        compliance.init_db(self.db)

    def complete_identity(self):
        payload = {key: "value" for key in compliance.SETTINGS_FIELDS}
        payload.update({
            "controllerName": "Example SAS",
            "legalForm": "SAS",
            "registeredAddress": "1 rue Exemple, 75000 Paris",
            "registrationId": "RCS PARIS 000 000 000",
            "publicationDirector": "Direction",
            "contactEmail": "contact@example.test",
            "privacyContact": "privacy@example.test",
            "mediatorName": "Médiateur test",
            "mediatorUrl": "https://example.test/mediation",
            "hostName": "Hébergeur test",
            "hostAddress": "2 rue Exemple, 75000 Paris",
            "approvalAuthority": "Autorité compétente test",
        })
        return compliance.save_settings(payload, self.db)

    def publish_required_documents(self):
        for doc_type, meta in compliance.DOCUMENT_TYPES.items():
            compliance.save_document({
                "type": doc_type,
                "version": "1.0",
                "title": meta["label"],
                "body": ("Contenu de test juridiquement relu. " * 6) + doc_type,
                "action": "publish",
            }, self.db)

    def test_publication_is_versioned_and_immutable(self):
        row = compliance.save_document({
            "type": "terms",
            "version": "1.0",
            "title": "CGV",
            "body": "Conditions contractuelles de test. " * 6,
            "action": "publish",
        }, self.db)
        self.assertEqual(row["status"], "published")
        self.assertEqual(compliance.public_document_for_path("/cgv", self.db)["version"], "1.0")
        with self.assertRaises(ValueError):
            compliance.save_document({
                "type": "terms",
                "version": "1.0",
                "title": "CGV modifiées",
                "body": "Texte modifié. " * 20,
                "action": "save",
            }, self.db)

    def test_nonessential_tracker_requires_consent(self):
        with self.assertRaises(ValueError):
            compliance.upsert_cookie({
                "key": "marketing_id",
                "provider": "Example",
                "purpose": "Mesure publicitaire",
                "category": "marketing",
                "legalBasis": "legitimate_interest",
                "durationDays": 30,
                "storageKind": "cookie",
                "essential": False,
                "enabled": True,
            }, self.db)
        row = compliance.upsert_cookie({
            "key": "marketing_id",
            "provider": "Example",
            "purpose": "Mesure publicitaire",
            "category": "marketing",
            "legalBasis": "consent",
            "durationDays": 30,
            "storageKind": "cookie",
            "essential": False,
            "enabled": True,
        }, self.db)
        self.assertTrue(row["enabled"])
        self.assertTrue(compliance.cookie_policy(self.db)["consentRequired"])

    def test_right_request_uses_calendar_month_deadline_and_hashes_reference(self):
        row = compliance.create_rights_request({
            "type": "access",
            "subjectRef": "customer@example.test",
            "notes": "Demande reçue via formulaire",
        }, self.db)
        received = datetime.datetime.fromisoformat(row["receivedAt"])
        due = datetime.datetime.fromisoformat(row["dueAt"])
        self.assertGreater(due, received + datetime.timedelta(days=27))
        self.assertLessEqual(due, received + datetime.timedelta(days=31))
        self.assertNotIn("customer@", row["subjectRefHash"])
        closed = compliance.set_rights_request_status(row["id"], "closed", self.db)
        self.assertEqual(closed["status"], "closed")

    def test_incident_with_risk_has_72_hour_deadline(self):
        row = compliance.create_incident({
            "riskLevel": "risk",
            "summary": "Incident de test",
        }, self.db)
        detected = datetime.datetime.fromisoformat(row["detectedAt"])
        due = datetime.datetime.fromisoformat(row["cnilDueAt"])
        self.assertEqual(due - detected, datetime.timedelta(hours=72))

    def test_acceptance_receipt_binds_published_version_and_hash(self):
        self.publish_required_documents()
        receipt = compliance.record_acceptance("order-123", db_path=self.db)
        terms = compliance.published_document("terms", self.db)
        self.assertEqual(receipt["documentVersion"], terms["version"])
        self.assertEqual(receipt["contentHash"], terms["contentHash"])
        self.assertEqual(receipt["contractRef"], "order-123")

    def test_checkout_acceptance_requires_current_terms_and_finalizes_to_contract(self):
        self.publish_required_documents()
        terms = compliance.published_document("terms", self.db)
        with self.assertRaises(ValueError):
            compliance.record_checkout_acceptance(
                "booking-token",
                terms_version=terms["version"],
                terms_content_hash=terms["contentHash"],
                accepted=False,
                reviewed=True,
                db_path=self.db,
            )
        with self.assertRaises(ValueError):
            compliance.record_checkout_acceptance(
                "booking-token",
                terms_version=terms["version"],
                terms_content_hash="0" * 64,
                accepted=True,
                reviewed=True,
                db_path=self.db,
            )
        acceptance = compliance.record_checkout_acceptance(
            "booking-token",
            terms_version=terms["version"],
            terms_content_hash=terms["contentHash"],
            accepted=True,
            reviewed=True,
            immediate_performance=True,
            db_path=self.db,
        )
        self.assertEqual(acceptance["termsVersion"], terms["version"])
        self.assertTrue(acceptance["reviewed"])
        first = compliance.finalize_checkout_acceptance("booking-token", "browser-123", db_path=self.db)
        final = compliance.finalize_checkout_acceptance("booking-token", "mercure-456", db_path=self.db)
        self.assertEqual(first["documentVersion"], terms["version"])
        self.assertEqual(final["contractRef"], "mercure-456")
        self.assertTrue(final["immediatePerformance"])
        with compliance.connect(self.db) as db:
            row = db.execute("SELECT booking_token_hash FROM checkout_acceptance_intents").fetchone()
        self.assertNotEqual(row["booking_token_hash"], "booking-token")

    def test_summary_claims_checkout_binding_but_stays_blocked_by_withdrawal(self):
        self.complete_identity()
        self.publish_required_documents()
        summary = compliance.summary(self.db)
        self.assertTrue(summary["identityComplete"])
        self.assertEqual(summary["publishedDocuments"], len(compliance.DOCUMENT_TYPES))
        self.assertTrue(summary["checkoutAcceptanceBound"])
        self.assertFalse(summary["withdrawalFunctionBound"])
        self.assertFalse(summary["readyForPublicContracting"])


if __name__ == "__main__":
    unittest.main()
