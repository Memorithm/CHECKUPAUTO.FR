import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import compliance_store
import compliance_operations

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location(
    "snapshot147", ROOT/"scripts/checkupauto-compliance-147-snapshot.py"
)
snapshot147=importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot147)


class Compliance147BoundedSnapshotTest(unittest.TestCase):
    def test_snapshot_is_bounded_and_contains_no_contract_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"compliance.sqlite3"
            compliance_store.save_settings({
                "controllerName":"CHECK UP AUTO",
                "legalForm":"SAS",
                "capital":"",
                "registeredAddress":"1 rue Niepce 78130 Les Mureaux",
                "registrationId":"TEST",
                "vatNumber":"",
                "publicationDirector":"Direction",
                "contactEmail":"contact@example.test",
                "privacyContact":"privacy@example.test",
                "mediatorName":"",
                "mediatorUrl":"",
                "mediatorAddress":"",
                "hostName":"PlanetHoster",
                "hostAddress":"France",
                "hostPhone":"",
                "approvalAuthority":"Autorité",
                "approvalReference":"",
            },db)
            state=snapshot147.snapshot(db)
        self.assertEqual(state["schema"],"checkupauto.compliance-147-bounded-snapshot/v1")
        self.assertIn("mediatorName",state["identity"]["missingFields"])
        self.assertIn("mediatorUrl",state["identity"]["missingFields"])
        self.assertFalse(state["termsEvidence"]["rawContractReferencesExposed"])
        self.assertFalse(state["personalDataExposed"])
        self.assertNotIn("settings",state)
        self.assertNotIn("rightsRequests",state)

    def test_terms_evidence_reports_only_aggregate_match_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"compliance.sqlite3"
            compliance_store.upsert_document({
                "type":"terms",
                "version":"v1",
                "title":"CGV",
                "body":"Conditions générales complètes.",
                "action":"publish",
            },db)
            doc=compliance_store.published_document("terms",db)
            compliance_store.record_consent(
                "contract-should-never-be-output",
                purpose="contract_terms",
                document_type="terms",
                immediate_performance=True,
                source="mercure_contract_confirmation",
                db_path=db,
            )
            evidence=snapshot147._terms_evidence(db)
        self.assertEqual(evidence["mercureContractReceiptCount"],1)
        self.assertEqual(evidence["matchingPublishedTermsReceiptCount"],1)
        self.assertTrue(evidence["allMercureContractReceiptsMatchPublishedTerms"])
        self.assertEqual(evidence["immediatePerformanceReceiptCount"],1)
        self.assertNotIn("contract-should-never-be-output",json.dumps(evidence))

    def test_operation_rows_expose_ids_and_dpa_states_not_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"compliance.sqlite3"
            compliance_operations.upsert_processing_activity({
                "id":"activity",
                "name":"Activity",
                "role":"controller",
                "purposes":["purpose"],
                "dataCategories":["category"],
                "dataSubjects":["subject"],
                "legalBases":["contract"],
                "recipients":["recipient"],
                "transfers":[],
                "retention":"policy",
                "securityControls":["control"],
                "systems":["system"],
                "owner":"owner",
                "riskLevel":"standard",
                "dpiaStatus":"not_required",
                "reviewDueAt":"2027-01-01",
                "status":"active",
            },db)
            compliance_operations.upsert_processor({
                "id":"processor",
                "name":"Processor",
                "service":"service",
                "dpaStatus":"pending",
                "hostingLocation":"France",
                "transferRequired":False,
                "transferMechanism":"",
                "subprocessors":[],
                "reviewDueAt":"2027-01-01",
                "status":"active",
            },db)
            state=snapshot147.snapshot(db)
        self.assertEqual(state["operations"]["activityIds"],["activity"])
        self.assertEqual(state["operations"]["processorIds"],["processor"])
        self.assertEqual(state["operations"]["processorDpaStates"],{"processor":"pending"})


if __name__=="__main__":
    unittest.main()
