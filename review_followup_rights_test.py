from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

import compliance_store
import data_subject_rights
import review_followup
import review_followup_privacy
import review_followup_rights as rights


class ReviewFollowupRightsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.review_db=root/"review-followup.sqlite3"
        self.compliance_db=root/"compliance.sqlite3"
        self.data_patch=mock.patch.object(review_followup,"DATA_DIR",root)
        self.db_patch=mock.patch.object(review_followup,"DB",self.review_db)
        self.data_patch.start(); self.db_patch.start()
        self.addCleanup(self.db_patch.stop); self.addCleanup(self.data_patch.stop)
        review_followup.init_db()

    def seed(self, appointment_id: str, *, status: str="sent") -> None:
        with review_followup.connect() as db:
            db.execute(
                """INSERT INTO review_followup(
                     appointment_id,first_seen_at,last_attempt_at,sent_at,
                     status,attempts,last_error
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    appointment_id,
                    "2026-09-24T10:00:00+00:00",
                    "2026-09-24T11:00:00+00:00",
                    "2026-09-24T11:00:00+00:00" if status=="sent" else "",
                    status,
                    1,
                    "",
                ),
            )

    def request(self, request_type: str, subject_ref: str="account:42") -> dict:
        return compliance_store.create_rights_request(
            {"type":request_type,"subjectRef":subject_ref,"notes":""},
            self.compliance_db,
        )

    @staticmethod
    def provider_snapshot(*appointment_ids: str, complete: bool=True) -> dict:
        return {
            "coverage":{"appointments":complete},
            "operationalInventory":{
                "state":"available",
                "appointments":[{"appointmentId":value} for value in appointment_ids],
                "appointmentCountInWindow":len(appointment_ids),
                "appointmentsTruncated":False,
                "appointmentIdsMissing":0,
            },
        }

    def test_access_exports_only_provider_proven_local_rows_and_audits_hash(self):
        self.seed("apt-subject")
        self.seed("apt-other")
        request=self.request("access")
        with mock.patch.object(
            rights.mercure_rights,
            "contact_snapshot",
            return_value=self.provider_snapshot("apt-subject"),
        ):
            result=rights.execute(request["id"],"account:42",self.compliance_db)

        self.assertTrue(result["ok"])
        self.assertEqual(result["adapter"],rights.ADAPTER)
        self.assertEqual(result["data"]["recordCount"],1)
        self.assertEqual(result["data"]["appointmentInventoryCount"],1)
        self.assertTrue(result["data"]["providerAppointmentCoverageComplete"])
        self.assertTrue(result["data"]["localCoverageComplete"])
        self.assertFalse(result["data"]["rawRecipientStoredLocally"])
        self.assertEqual(
            [row["appointmentId"] for row in result["data"]["records"]],
            ["apt-subject"],
        )
        self.assertNotIn("apt-other",json.dumps(result["data"]))

        audit=data_subject_rights.audit_rows(self.compliance_db)
        row=next(item for item in audit if item["adapter"]==rights.ADAPTER)
        self.assertEqual(row["action"],"export_complete")
        self.assertRegex(row["evidenceHash"],r"^[0-9a-f]{64}$")
        self.assertNotIn("apt-subject",repr(row))
        with self.assertRaises(RuntimeError):
            rights.execute(request["id"],"account:42",self.compliance_db)

    def test_portability_uses_same_complete_provider_bounded_export(self):
        self.seed("apt-portable",status="pending")
        request=self.request("portability")
        with mock.patch.object(
            rights.mercure_rights,
            "contact_snapshot",
            return_value=self.provider_snapshot("apt-portable"),
        ):
            result=rights.execute(request["id"],"account:42",self.compliance_db)
        self.assertEqual(result["format"],"application/json")
        self.assertEqual(result["data"]["records"][0]["status"],"pending")
        self.assertEqual(result["data"]["records"][0]["attempts"],1)

    def test_incomplete_provider_inventory_fails_closed_without_audit(self):
        self.seed("apt-subject")
        request=self.request("access")
        snapshot=self.provider_snapshot("apt-subject",complete=False)
        with mock.patch.object(
            rights.mercure_rights,
            "contact_snapshot",
            return_value=snapshot,
        ):
            with self.assertRaisesRegex(RuntimeError,"inventaire Mercure"):
                rights.execute(request["id"],"account:42",self.compliance_db)

        self.assertEqual(data_subject_rights.audit_rows(self.compliance_db),[])
        with review_followup.connect() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) n FROM review_followup").fetchone()["n"],
                1,
            )

    def test_erasure_reuses_transactional_receipt_and_keeps_other_subject_rows(self):
        self.seed("apt-subject")
        self.seed("apt-other")
        request=self.request("erasure")
        with mock.patch.object(
            rights.mercure_rights,
            "contact_snapshot",
            return_value=self.provider_snapshot("apt-subject"),
        ):
            result=rights.execute(request["id"],"account:42",self.compliance_db)

        self.assertEqual(result["affectedRows"],1)
        self.assertEqual(result["remainingActiveRows"],0)
        with review_followup.connect() as db:
            remaining=[
                str(row["appointment_id"])
                for row in db.execute(
                    "SELECT appointment_id FROM review_followup ORDER BY appointment_id"
                )
            ]
        self.assertEqual(remaining,["apt-other"])
        receipt=review_followup_privacy.receipt(request["id"])
        self.assertIsNotNone(receipt)
        self.assertNotIn("apt-subject",json.dumps(receipt,sort_keys=True))
        audit=data_subject_rights.audit_rows(self.compliance_db)
        row=next(item for item in audit if item["adapter"]==rights.ADAPTER)
        self.assertEqual(row["action"],"erasure_complete")

    def test_verified_mercure_binding_can_authorize_mobile_origin_request(self):
        installation=str(uuid.uuid4())
        request=self.request("access",installation)
        with mock.patch.object(
            rights.rights_subject_bindings,
            "is_bound",
            return_value=True,
        ) as is_bound, mock.patch.object(
            rights.mercure_rights,
            "contact_snapshot",
            return_value=self.provider_snapshot(),
        ):
            result=rights.execute(request["id"],"account:42",self.compliance_db)

        self.assertEqual(result["data"]["recordCount"],0)
        is_bound.assert_called_once_with(
            request["id"],
            rights.rights_subject_bindings.MERCURE_CONTACT_ADAPTER,
            "account:42",
            self.compliance_db,
        )

    def test_provider_count_mismatch_is_rejected(self):
        request=self.request("access")
        snapshot=self.provider_snapshot("apt-subject")
        snapshot["operationalInventory"]["appointmentCountInWindow"]=2
        with mock.patch.object(
            rights.mercure_rights,
            "contact_snapshot",
            return_value=snapshot,
        ):
            with self.assertRaisesRegex(RuntimeError,"incohérent"):
                rights.execute(request["id"],"account:42",self.compliance_db)

    def test_capability_is_complete_locally_but_provider_inventory_gated(self):
        state=rights.capability()
        self.assertTrue(state["bound"])
        self.assertFalse(state["partial"])
        self.assertEqual(
            state["supportedRights"],
            ["access","portability","erasure"],
        )
        self.assertTrue(state["requiresCompleteProviderAppointmentInventory"])
        self.assertTrue(state["acceptsVerifiedMercureBinding"])
        self.assertFalse(state["rawRecipientStoredLocally"])
        self.assertEqual(state["coveredStores"],["review_followup"])


if __name__=="__main__":
    unittest.main()
