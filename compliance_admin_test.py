import tempfile
import unittest
from pathlib import Path

import compliance_admin
import compliance_operations
import compliance_register_attestation
import compliance_store
import marketing_campaigns
import processing_risk_review


class ComplianceAdminSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "compliance.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def activity(self, **overrides):
        payload = {
            "name": "Gestion des rendez-vous",
            "role": "controller",
            "purposes": ["Planifier et exécuter les contrôles techniques"],
            "dataCategories": ["coordonnées", "données véhicule"],
            "dataSubjects": ["clients"],
            "legalBases": ["contrat"],
            "recipients": ["équipe du centre"],
            "transfers": [],
            "retention": "Durée documentée dans la politique de conservation applicable",
            "securityControls": ["contrôle d'accès", "journalisation"],
            "systems": ["CheckupAuto", "Mercure"],
            "owner": "Responsable conformité",
            "riskLevel": "standard",
            "dpiaStatus": "not_required",
            "reviewDueAt": "2099-12-31",
            "status": "active",
        }
        payload.update(overrides)
        return payload

    def processor(self, **overrides):
        payload = {
            "name": "Prestataire documenté",
            "service": "Service externe classifié par le responsable conformité",
            "dpaStatus": "signed",
            "hostingLocation": "Lieu documenté par le contrat",
            "transferRequired": False,
            "transferMechanism": "",
            "subprocessors": [],
            "reviewDueAt": "2099-12-31",
            "status": "active",
        }
        payload.update(overrides)
        return payload

    def ready_registers(self):
        compliance_operations.upsert_processing_activity(self.activity(), self.db)
        compliance_operations.upsert_processor(self.processor(), self.db)

    def attest_registers(self):
        reviewed_hash = compliance_register_attestation.register_hash(self.db)
        return compliance_register_attestation.attest(
            self.db,
            expected_register_hash=reviewed_hash,
        )

    def test_empty_operational_registers_fail_closed(self):
        state = compliance_admin.snapshot(self.db)
        self.assertFalse(state["summary"]["operationalRegistersReady"])
        blockers = {item["type"] for item in state["summary"]["operationalBlockers"]}
        self.assertIn("processing_register_missing", blockers)
        self.assertIn("processor_inventory_missing", blockers)
        self.assertIn("operational_register_attestation_missing", blockers)
        self.assertFalse(state["summary"]["readyForPublicContracting"])
        self.assertEqual(state["operations"]["summary"]["activeActivityCount"], 0)
        self.assertEqual(state["operations"]["summary"]["activeProcessorCount"], 0)

    def test_complete_activity_without_processor_inventory_fails_closed(self):
        compliance_operations.upsert_processing_activity(self.activity(), self.db)
        state = compliance_admin.snapshot(self.db)
        self.assertFalse(state["summary"]["operationalRegistersReady"])
        blockers = {item["type"] for item in state["summary"]["operationalBlockers"]}
        self.assertIn("processor_inventory_missing", blockers)
        self.assertIn("operational_register_attestation_missing", blockers)
        self.assertFalse(state["summary"]["readyForPublicContracting"])

    def test_complete_registers_without_attestation_fail_closed(self):
        self.ready_registers()
        state = compliance_admin.snapshot(self.db)
        self.assertFalse(state["summary"]["operationalRegistersReady"])
        self.assertIn(
            "operational_register_attestation_missing",
            {item["type"] for item in state["summary"]["operationalBlockers"]},
        )
        self.assertFalse(state["summary"]["operationalRegisterAttestationCurrent"])

    def test_attested_activity_and_processor_inventory_make_operational_register_ready(self):
        self.ready_registers()
        self.attest_registers()
        state = compliance_admin.snapshot(self.db)
        self.assertTrue(state["summary"]["operationalRegistersReady"])
        self.assertTrue(state["summary"]["operationalRegisterAttestationCurrent"])
        self.assertEqual(state["summary"]["operationalBlockers"], [])
        self.assertTrue(state["operationalRegisterAttestation"]["current"])
        self.assertIn("settings", state)
        self.assertIn("documentTypes", state)
        # Contracting remains blocked by the existing CGV/withdrawal/rights gates.
        self.assertFalse(state["summary"]["readyForPublicContracting"])

    def test_register_edit_makes_attestation_stale_and_fails_closed(self):
        self.ready_registers()
        self.attest_registers()
        activity = compliance_operations.processing_activities(self.db)[0]
        compliance_operations.upsert_processing_activity(
            self.activity(id=activity["id"], retention="Politique de conservation révisée"), self.db
        )
        state = compliance_admin.snapshot(self.db)
        self.assertFalse(state["summary"]["operationalRegistersReady"])
        self.assertIn(
            "operational_register_attestation_stale",
            {item["type"] for item in state["summary"]["operationalBlockers"]},
        )
        self.assertTrue(state["operationalRegisterAttestation"]["stale"])

    def test_withdrawal_ready_still_fails_closed_for_remaining_phase2_controls(self):
        identity = {key: "value" for key in compliance_store.SETTINGS_FIELDS}
        identity.update({
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
        compliance_store.save_settings(identity, self.db)
        for doc_type, meta in compliance_store.DOCUMENT_TYPES.items():
            compliance_store.save_document({
                "type": doc_type,
                "version": "1.0",
                "title": meta["label"],
                "body": ("Document juridiquement validé pour le test. " * 6) + doc_type,
                "action": "publish",
            }, self.db)
        self.ready_registers()
        self.attest_registers()

        state = compliance_admin.snapshot(self.db)
        self.assertTrue(state["summary"]["checkoutAcceptanceBound"])
        self.assertTrue(state["summary"]["withdrawalFunctionBound"])
        self.assertTrue(state["summary"]["operationalRegistersReady"])
        self.assertFalse(state["summary"]["dataSubjectExecutionBound"])
        self.assertFalse(state["summary"]["retentionEnforcementBound"])
        self.assertFalse(state["summary"]["readyForPublicContracting"])
        self.assertEqual(state["withdrawal"]["path"], "/retractation")

    def test_high_risk_pending_dpia_is_visible_in_same_snapshot(self):
        compliance_operations.upsert_processing_activity(
            self.activity(riskLevel="high", dpiaStatus="required_pending"), self.db
        )
        compliance_operations.upsert_processor(self.processor(), self.db)
        state = compliance_admin.snapshot(self.db)
        self.assertFalse(state["summary"]["operationalRegistersReady"])
        self.assertIn(
            "dpia_unresolved",
            {item["type"] for item in state["summary"]["operationalBlockers"]},
        )

    def test_high_risk_approved_dpia_still_requires_security_and_privacy_reviews(self):
        activity = compliance_operations.upsert_processing_activity(
            self.activity(riskLevel="high", dpiaStatus="approved"), self.db
        )
        compliance_operations.upsert_processor(self.processor(), self.db)
        self.attest_registers()

        state = compliance_admin.snapshot(self.db)
        blockers = {item["type"] for item in state["summary"]["operationalBlockers"]}
        self.assertFalse(state["summary"]["operationalRegistersReady"])
        self.assertFalse(state["summary"]["processingRiskReviewsReady"])
        self.assertIn("processing_security_review_not_approved", blockers)
        self.assertIn("processing_privacy_review_not_approved", blockers)
        self.assertTrue(state["operationalRegisterAttestation"]["current"])

        review_row = state["processingRiskReview"]["activities"][0]
        processing_risk_review.record_review(
            activity["id"],
            expected_activity_hash=review_row["currentActivityHash"],
            security_status="approved",
            privacy_status="approved",
            evidence=b"document de revue externe borne au test",
            db_path=self.db,
        )

        state = compliance_admin.snapshot(self.db)
        blockers = {item["type"] for item in state["summary"]["operationalBlockers"]}
        self.assertTrue(state["summary"]["processingRiskReviewsReady"])
        self.assertNotIn("processing_security_review_not_approved", blockers)
        self.assertNotIn("processing_privacy_review_not_approved", blockers)
        self.assertTrue(state["summary"]["operationalRegistersReady"])
        self.assertTrue(state["operationalRegisterAttestation"]["current"])

    def test_marketing_campaign_evidence_is_visible_without_raw_audience_or_content(self):
        marketing_campaigns.init_db(self.db)
        with compliance_store.connect(self.db) as db:
            db.execute(
                """INSERT INTO marketing_campaign_run(
                     run_id,channel,reference_hash,content_hash,audience_count,
                     attempted_count,delivered_count,blocked_count,failed_count,
                     pending_count,status,started_at,completed_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "run-test",
                    "email",
                    "a" * 64,
                    "b" * 64,
                    5,
                    5,
                    3,
                    1,
                    1,
                    0,
                    "partial",
                    "2026-09-21T20:00:00+00:00",
                    "2026-09-21T20:01:00+00:00",
                ),
            )

        state = compliance_admin.snapshot(self.db)
        self.assertTrue(state["summary"]["marketingCampaignsBound"])
        self.assertEqual(state["summary"]["marketingCampaignRunCount"], 1)
        self.assertEqual(state["marketingCampaigns"]["capability"]["channels"], ["email", "push"])
        run = state["marketingCampaigns"]["recent"][0]
        self.assertEqual(run["deliveredCount"], 3)
        self.assertEqual(run["blockedCount"], 1)
        self.assertEqual(run["failedCount"], 1)
        self.assertEqual(run["pendingCount"], 0)
        serialized = str(state["marketingCampaigns"])
        self.assertNotIn("client@example.test", serialized)
        self.assertNotIn("message secret", serialized)


if __name__ == "__main__":
    unittest.main()
