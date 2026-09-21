import datetime
import os
import tempfile
import unittest
from pathlib import Path

import compliance_store
import marketing_consent as marketing
import privacy_suppression as privacy


class MarketingConsentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_private = os.environ.get("CYBERCHECK_PRIVATE_DIR")
        self.old_data = os.environ.get("CYBERCHECK_DATA_DIR")
        os.environ["CYBERCHECK_PRIVATE_DIR"] = self.tmp.name
        os.environ["CYBERCHECK_DATA_DIR"] = self.tmp.name
        self.addCleanup(self._restore)
        self.db = Path(self.tmp.name) / "compliance.sqlite3"
        marketing.init_db(self.db)

    def _restore(self):
        for key, value in (
            ("CYBERCHECK_PRIVATE_DIR", self.old_private),
            ("CYBERCHECK_DATA_DIR", self.old_data),
        ):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def payload(self, channel="email", subject="alice@example.test", **overrides):
        value = {
            "channel": channel,
            "subjectRef": subject,
            "controllerName": "Checkup Auto",
            "thirdPartyName": "",
            "goodsServicesScope": "Offres et services Checkup Auto liés au contrôle technique automobile",
            "statementVersion": "1.0",
            "statementText": (
                "J’accepte de recevoir des offres commerciales Checkup Auto "
                "par le canal choisi. Mon consentement peut être retiré à tout moment."
            ),
            "source": "consent-test",
            "evidenceRef": "evidence-123",
            "withdrawalMethod": "Demande auprès de Checkup Auto ou lien de désinscription du message.",
            "positiveAction": True,
        }
        value.update(overrides)
        return value

    def test_email_marketing_is_denied_until_explicit_consent_exists(self):
        result = marketing.authorize("email", "alice@example.test", db_path=self.db)
        self.assertFalse(result["authorized"])
        self.assertEqual(result["reason"], "explicit_consent_missing")

        consent = marketing.record_consent(self.payload(), self.db)
        self.assertEqual(consent["channel"], "email")
        allowed = marketing.require_authorized(
            "email", "alice@example.test", db_path=self.db
        )
        self.assertTrue(allowed["authorized"])

    def test_cgv_acceptance_never_counts_as_marketing_consent(self):
        compliance_store.save_document({
            "type": "terms",
            "version": "1.0",
            "title": "CGV",
            "body": "Conditions générales juridiquement validées. " * 8,
            "action": "publish",
        }, self.db)
        compliance_store.record_acceptance("contract-1", db_path=self.db)
        result = marketing.authorize("email", "alice@example.test", db_path=self.db)
        self.assertFalse(result["authorized"])
        self.assertEqual(result["reason"], "explicit_consent_missing")

    def test_positive_action_is_mandatory(self):
        with self.assertRaises(ValueError):
            marketing.record_consent(
                self.payload(positiveAction=False),
                self.db,
            )

    def test_future_dated_consent_is_rejected(self):
        future = (
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=1)
        ).isoformat()
        with self.assertRaises(ValueError):
            marketing.record_consent(
                self.payload(consentedAt=future),
                self.db,
            )

    def test_phone_consent_period_is_bounded_to_one_year_and_proof_to_three_years(self):
        consented = datetime.datetime(2026, 9, 21, 12, 0, tzinfo=datetime.timezone.utc)
        too_late = consented.replace(year=2027) + datetime.timedelta(days=1)
        with self.assertRaises(ValueError):
            marketing.record_consent(
                self.payload(
                    channel="phone",
                    subject="+33123456789",
                    consentedAt=consented.isoformat(),
                    validUntil=too_late.isoformat(),
                ),
                self.db,
            )

        valid_until = consented.replace(year=2027)
        row = marketing.record_consent(
            self.payload(
                channel="phone",
                subject="+33123456789",
                consentedAt=consented.isoformat(),
                validUntil=valid_until.isoformat(),
            ),
            self.db,
        )
        self.assertEqual(
            datetime.datetime.fromisoformat(row["validUntil"]),
            valid_until,
        )
        self.assertEqual(
            datetime.datetime.fromisoformat(row["proofRetainUntil"]),
            consented.replace(year=2029),
        )
        self.assertTrue(row["positiveAction"])
        self.assertIn("retiré", row["statementText"])

    def test_withdrawal_denies_marketing_but_preserves_durable_proof(self):
        marketing.record_consent(self.payload(), self.db)
        result = marketing.withdraw(
            "email",
            "alice@example.test",
            source="consumer-request",
            db_path=self.db,
        )
        self.assertEqual(result["activeConsentRowsWithdrawn"], 1)
        denied = marketing.authorize("email", "alice@example.test", db_path=self.db)
        self.assertFalse(denied["authorized"])
        self.assertEqual(denied["reason"], "privacy_suppressed")
        proof = marketing.proof("email", "alice@example.test", db_path=self.db)
        self.assertEqual(proof["records"][0]["state"], "withdrawn")
        self.assertEqual(proof["records"][0]["withdrawalSource"], "consumer-request")
        self.assertTrue(proof["records"][0]["withdrawnAt"])

    def test_new_consent_lifts_only_channel_specific_suppression(self):
        marketing.record_consent(self.payload(), self.db)
        marketing.withdraw("email", "alice@example.test", db_path=self.db)
        self.assertTrue(
            privacy.is_suppressed(
                "email",
                "alice@example.test",
                "direct_marketing_email",
                db_path=self.db,
            )
        )
        marketing.record_consent(
            self.payload(statementVersion="2.0", evidenceRef="evidence-456"),
            self.db,
        )
        self.assertFalse(
            privacy.is_suppressed(
                "email",
                "alice@example.test",
                "direct_marketing_email",
                db_path=self.db,
            )
        )
        self.assertTrue(
            marketing.authorize("email", "alice@example.test", db_path=self.db)["authorized"]
        )

    def test_all_processing_suppression_always_wins_over_new_marketing_consent(self):
        privacy.suppress(
            "email",
            "alice@example.test",
            ["all_processing"],
            request_id="erasure",
            db_path=self.db,
        )
        marketing.record_consent(self.payload(), self.db)
        denied = marketing.authorize("email", "alice@example.test", db_path=self.db)
        self.assertFalse(denied["authorized"])
        self.assertEqual(denied["reason"], "privacy_suppressed")

    def test_expired_consent_is_denied_and_state_is_persisted(self):
        consented = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
        valid_until = datetime.datetime(2025, 2, 1, tzinfo=datetime.timezone.utc)
        marketing.record_consent(
            self.payload(
                consentedAt=consented.isoformat(),
                validUntil=valid_until.isoformat(),
            ),
            self.db,
        )
        denied = marketing.authorize(
            "email",
            "alice@example.test",
            at=datetime.datetime(2025, 3, 1, tzinfo=datetime.timezone.utc),
            db_path=self.db,
        )
        self.assertFalse(denied["authorized"])
        self.assertEqual(denied["reason"], "consent_expired")
        rows = marketing.recent(self.db)
        self.assertEqual(rows[0]["state"], "expired")

    def test_raw_recipient_and_evidence_reference_are_not_stored(self):
        marketing.record_consent(self.payload(), self.db)
        raw = self.db.read_bytes()
        self.assertNotIn(b"alice@example.test", raw)
        self.assertNotIn(b"evidence-123", raw)
        rows = marketing.recent(self.db)
        self.assertEqual(len(rows[0]["subjectHash"]), 16)
        self.assertEqual(len(rows[0]["evidenceRefHash"]), 64)

    def test_phone_proof_contains_required_durable_fields(self):
        consented = datetime.datetime(2026, 9, 21, 12, 0, tzinfo=datetime.timezone.utc)
        marketing.record_consent(
            self.payload(
                channel="phone",
                subject="+33123456789",
                thirdPartyName="Prestataire appels test",
                consentedAt=consented.isoformat(),
                validUntil=consented.replace(year=2027).isoformat(),
            ),
            self.db,
        )
        record = marketing.proof(
            "phone", "+33123456789", db_path=self.db
        )["records"][0]
        for key in (
            "controllerName",
            "thirdPartyName",
            "goodsServicesScope",
            "statementText",
            "consentedAt",
            "validUntil",
            "withdrawalMethod",
            "proofRetainUntil",
        ):
            self.assertTrue(record[key], key)


if __name__ == "__main__":
    unittest.main()
