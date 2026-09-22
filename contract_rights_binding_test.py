import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import analytics_store
import compliance_store
import data_subject_rights as rights
import rights_subject_bindings as bindings


class ContractRightsBindingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.compliance_db = self.root / "compliance.sqlite3"
        self.old_analytics_dir, self.old_analytics_db = analytics_store.DATA_DIR, analytics_store.DB
        analytics_store.DATA_DIR = self.root / "analytics"
        analytics_store.DB = analytics_store.DATA_DIR / "analytics.sqlite3"
        self.mercure_ref = "account:client-42"
        self.contract_ref = "appointment-42"
        terms = compliance_store.save_document({
            "type": "terms",
            "version": "2026-09-22",
            "title": "Conditions générales de vente",
            "body": "Conditions contractuelles de test. " * 8,
            "action": "publish",
        }, self.compliance_db)
        compliance_store.record_checkout_acceptance(
            "booking-secret",
            terms_version=terms["version"],
            terms_content_hash=terms["contentHash"],
            accepted=True,
            reviewed=True,
            immediate_performance=True,
            db_path=self.compliance_db,
        )
        compliance_store.finalize_checkout_acceptance(
            "booking-secret", self.contract_ref, db_path=self.compliance_db,
        )
        with analytics_store.connect() as db:
            db.executescript("""
                CREATE TABLE booking_conversions(
                  provider TEXT NOT NULL, external_id TEXT NOT NULL, status TEXT NOT NULL,
                  first_seen_at TEXT NOT NULL, updated_at TEXT NOT NULL, confirmed_at TEXT,
                  appointment_at TEXT NOT NULL DEFAULT '', amount_cents INTEGER NOT NULL DEFAULT 0,
                  service TEXT NOT NULL DEFAULT '', attribution_token TEXT NOT NULL DEFAULT '',
                  source TEXT NOT NULL DEFAULT 'Non attribué', campaign TEXT NOT NULL DEFAULT '',
                  device TEXT NOT NULL DEFAULT 'unknown', referral_code TEXT NOT NULL DEFAULT '',
                  PRIMARY KEY(provider,external_id)
                );
            """)
            base = (
                self.contract_ref, "confirmed", "2026-09-22T00:00:00+00:00",
                "2026-09-22T00:01:00+00:00", "2026-09-22T00:01:00+00:00",
                "2026-10-03T09:30:00+02:00", 8000, "controle technique",
            )
            db.execute(
                "INSERT INTO booking_conversions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("mercure-rdv",) + base + ("mercure-secret", "Google", "ct", "mobile", "PARRAIN42"),
            )
            db.execute(
                "INSERT INTO booking_conversions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("other-provider",) + base + ("other-secret", "Partner", "x", "desktop", "OTHER"),
            )

    def tearDown(self):
        analytics_store.DATA_DIR, analytics_store.DB = self.old_analytics_dir, self.old_analytics_db
        self.tmp.cleanup()

    def _request(self):
        return compliance_store.create_rights_request(
            {"type": "access", "subjectRef": self.mercure_ref}, self.compliance_db,
        )

    def _mercure_snapshot(self, appointment_id=None, state="available"):
        return {
            "provider": "mercure",
            "subject": {"clientKind": "account", "clientId": "client-42"},
            "contact": {"email": "client@example.fr", "telephone": "+33102030405"},
            "operationalInventory": {
                "state": state,
                "appointments": ([{"appointmentId": appointment_id}] if appointment_id else []),
                "appointmentsTruncated": False,
            },
            "partial": True,
        }

    @patch.object(bindings.mercure_rights, "contact_snapshot")
    def test_exact_mercure_appointment_binds_contract_and_central_export(self, snapshot):
        snapshot.return_value = self._mercure_snapshot(self.contract_ref)
        request = self._request()
        bound = bindings.bind_contract_from_mercure(
            request["id"], self.mercure_ref, self.contract_ref, self.compliance_db,
        )
        self.assertTrue(bound["bound"])
        self.assertEqual(bound["adapter"], "compliance_contracts")
        self.assertEqual(bound["provenance"], "mercure_appointment")
        self.assertFalse(bound["rawSubjectReferencePersisted"])
        self.assertNotIn(self.mercure_ref, json.dumps(bound, sort_keys=True))
        self.assertNotIn(self.contract_ref, json.dumps(bound, sort_keys=True))

        rows = bindings.rows(self.compliance_db)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["adapter"], "compliance_contracts")
        self.assertEqual(rows[0]["provenance"], "mercure_appointment")
        self.assertNotIn(self.mercure_ref, json.dumps(rows, sort_keys=True))
        self.assertNotIn(self.contract_ref, json.dumps(rows, sort_keys=True))

        exported = rights.execute(
            request["id"], self.contract_ref,
            adapter="compliance_contracts", db_path=self.compliance_db,
        )
        self.assertTrue(exported["ok"])
        self.assertEqual(len(exported["data"]["bookingConversions"]), 1)
        self.assertEqual(exported["data"]["bookingConversions"][0]["provider"], "mercure-rdv")
        serialized = json.dumps(exported, sort_keys=True)
        self.assertNotIn("other-provider", serialized)
        self.assertNotIn("mercure-secret", serialized)
        self.assertNotIn("other-secret", serialized)

    @patch.object(bindings.mercure_rights, "contact_snapshot")
    def test_unrelated_mercure_appointment_cannot_bind_contract(self, snapshot):
        snapshot.return_value = self._mercure_snapshot("appointment-other")
        request = self._request()
        with self.assertRaisesRegex(PermissionError, "contrat non prouvé"):
            bindings.bind_contract_from_mercure(
                request["id"], self.mercure_ref, self.contract_ref, self.compliance_db,
            )
        self.assertEqual(bindings.rows(self.compliance_db), [])

    @patch.object(bindings.mercure_rights, "contact_snapshot")
    def test_unavailable_mercure_inventory_fails_closed(self, snapshot):
        snapshot.return_value = self._mercure_snapshot(state="unavailable")
        request = self._request()
        with self.assertRaisesRegex(RuntimeError, "inventaire Mercure indisponible"):
            bindings.bind_contract_from_mercure(
                request["id"], self.mercure_ref, self.contract_ref, self.compliance_db,
            )
        self.assertEqual(bindings.rows(self.compliance_db), [])

    @patch.object(bindings.mercure_rights, "contact_snapshot")
    def test_unverified_mercure_subject_is_refused_before_provider_call(self, snapshot):
        request = compliance_store.create_rights_request(
            {"type": "access", "subjectRef": "account:another-client"}, self.compliance_db,
        )
        with self.assertRaisesRegex(PermissionError, "référence Mercure"):
            bindings.bind_contract_from_mercure(
                request["id"], self.mercure_ref, self.contract_ref, self.compliance_db,
            )
        snapshot.assert_not_called()
        self.assertEqual(bindings.rows(self.compliance_db), [])


if __name__ == "__main__":
    unittest.main()
