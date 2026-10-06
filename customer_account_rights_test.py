import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import compliance_store
import customer_account_erasure_plan
import customer_account_rights
import customer_accounts
import customer_ct_reports
import data_subject_rights
import rights_completion_plan
import rights_execution_dispatch
import rights_readiness


REPORT_TEXT="""PROCÈS-VERBAL DE CONTRÔLE TECHNIQUE
IMMATRICULATION : AB-123-CD
VIN : VF3ABCDEFGH123456
DATE DU CONTRÔLE : 25/09/2026
KILOMÉTRAGE RELEVÉ : 124 550
RÉSULTAT DU CONTRÔLE : FAVORABLE
"""


class CustomerAccountRightsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.env=mock.patch.dict(os.environ,{
            "CYBERCHECK_DATA_DIR":str(self.root/"data"),
            "CYBERCHECK_PRIVATE_DIR":str(self.root/"private"),
        },clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.compliance=self.root/"compliance.sqlite3"

    def account(self,email="alice@example.test",subject="alice-google-subject",name="Alice"):
        return customer_accounts.create_from_verified_identity(
            "google",subject,email,name,email_verified=True
        )

    def report(self,account_id):
        raw=b"%PDF-1.7 synthetic customer report"
        with mock.patch.object(
            customer_ct_reports,
            "extract_text",
            return_value=(REPORT_TEXT,"synthetic-test"),
        ):
            return customer_ct_reports.ingest(
                account_id,"controle.pdf","application/pdf",raw
            )

    def request(self,kind,email="alice@example.test"):
        return compliance_store.create_rights_request({
            "type":kind,
            "subjectRef":email,
            "notes":"",
        },self.compliance)

    def test_access_exports_exact_account_identities_and_full_report_payload(self):
        alice=self.account()
        self.report(alice["accountId"])
        self.account("bob@example.test","bob-google-subject","Bob")
        req=self.request("access")

        out=rights_execution_dispatch.execute({
            "id":req["id"],
            "subjectRef":"alice@example.test",
            "adapter":customer_account_rights.ADAPTER,
        },self.compliance)

        self.assertEqual(out["adapter"],customer_account_rights.ADAPTER)
        self.assertEqual(out["data"]["account"]["email"],"alice@example.test")
        self.assertEqual(out["data"]["identityCount"],1)
        self.assertEqual(out["data"]["identities"][0]["provider"],"google")
        self.assertEqual(out["data"]["reportCount"],1)
        self.assertIn(
            "AB-123-CD",
            out["data"]["reports"][0]["payload"]["extractedText"],
        )
        self.assertNotIn("bob@example.test",repr(out["data"]))
        audit=data_subject_rights.audit_rows(self.compliance)
        self.assertEqual(audit[0]["adapter"],customer_account_rights.ADAPTER)
        self.assertEqual(audit[0]["action"],"export_complete")
        self.assertNotIn("alice@example.test",repr(audit))

    def test_wrong_subject_is_rejected_before_customer_store_execution(self):
        self.account()
        req=self.request("access")
        with self.assertRaises(PermissionError):
            customer_account_rights.execute(
                req["id"],"bob@example.test",self.compliance
            )

    def test_erasure_removes_reports_account_identity_sessions_and_passages(self):
        alice=self.account()
        account_id=alice["accountId"]
        self.report(account_id)
        session=customer_accounts.issue_session(account_id)
        customer_accounts.begin_passage_confirmation(account_id)
        req=self.request("erasure")

        out=customer_account_rights.execute(
            req["id"],"alice@example.test",self.compliance
        )

        self.assertEqual(out["remainingAccountCount"],0)
        self.assertEqual(out["remainingIdentityCount"],0)
        self.assertEqual(out["remainingReportCount"],0)
        self.assertTrue(out["planCleared"])
        with customer_accounts._connect() as db:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) n FROM customer_session WHERE account_id=?",
                    (account_id,),
                ).fetchone()["n"],
                0,
            )
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) n FROM customer_passage_confirmation WHERE account_id=?",
                    (account_id,),
                ).fetchone()["n"],
                0,
            )
        with self.assertRaises(customer_accounts.CustomerAccountError):
            customer_accounts.profile(account_id)
        with self.assertRaises(PermissionError):
            customer_accounts.authenticate_session(session["token"])
        self.assertEqual(customer_ct_reports.list_reports(account_id),[])
        self.assertIsNone(
            customer_account_erasure_plan.load(req["id"],"alice@example.test")
        )
        self.assertEqual(
            data_subject_rights.audit_rows(self.compliance)[0]["action"],
            "erasure_complete",
        )

    def test_erasure_recovers_after_store_mutation_before_audit(self):
        alice=self.account()
        account_id=alice["accountId"]
        self.report(account_id)
        req=self.request("erasure")
        state=customer_account_rights.snapshot("alice@example.test")
        customer_account_erasure_plan.stage(
            req["id"],
            "alice@example.test",
            account_id,
            identity_count=state["identityCount"],
            report_count=state["reportCount"],
        )
        with customer_ct_reports._connect() as db:
            db.execute(
                "DELETE FROM customer_ct_report WHERE account_id=?",
                (account_id,),
            )
        customer_accounts.init_db()
        with customer_accounts._connect() as db:
            db.execute(
                "DELETE FROM customer_account WHERE account_id=?",
                (account_id,),
            )

        out=customer_account_rights.execute(
            req["id"],"alice@example.test",self.compliance
        )
        self.assertTrue(out["recoveredFromPlan"])
        self.assertEqual(out["plannedIdentityCount"],1)
        self.assertEqual(out["plannedReportCount"],1)
        self.assertTrue(out["planCleared"])
        self.assertEqual(
            data_subject_rights.audit_rows(self.compliance)[0]["action"],
            "erasure_complete",
        )

    def test_empty_exact_email_is_a_complete_local_noop(self):
        req=self.request("erasure","nobody@example.test")
        out=customer_account_rights.execute(
            req["id"],"nobody@example.test",self.compliance
        )
        self.assertEqual(out["removedAccountCount"],0)
        self.assertEqual(out["remainingReportCount"],0)
        self.assertFalse(out["planCleared"])
        self.assertEqual(
            data_subject_rights.audit_rows(self.compliance)[0]["action"],
            "erasure_complete",
        )

    def test_capabilities_and_completion_plan_include_customer_adapter(self):
        dispatch=rights_execution_dispatch.capability(self.compliance)
        self.assertEqual(
            dispatch["supportedAdapters"][customer_account_rights.ADAPTER],
            ["access","portability","erasure"],
        )
        self.assertTrue(dispatch["customerAccount"]["bound"])
        ready=rights_readiness.capability(self.compliance)
        self.assertEqual(
            ready["supportedAdapters"][customer_account_rights.ADAPTER],
            ["access","portability","erasure"],
        )
        self.assertIn(
            customer_account_rights.ADAPTER,
            rights_completion_plan._known_adapters("access"),
        )
        self.assertFalse(
            rights_completion_plan.capability()["globalCoverageComplete"]
        )

    def test_dispatch_rejects_extra_fields(self):
        req=self.request("access")
        with self.assertRaises(ValueError):
            rights_execution_dispatch.execute({
                "id":req["id"],
                "subjectRef":"alice@example.test",
                "adapter":customer_account_rights.ADAPTER,
                "extra":"no",
            },self.compliance)


if __name__=="__main__":
    unittest.main()
