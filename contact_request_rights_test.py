import json
import os
import tempfile
import unittest
from pathlib import Path

import compliance_store
import contact_request
import contact_request_rights
import data_subject_rights
import rights_execution_dispatch


class ContactRequestRightsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.old_data=os.environ.get("CYBERCHECK_DATA_DIR")
        os.environ["CYBERCHECK_DATA_DIR"]=str(self.root/"data")
        self.addCleanup(self._restore_env)
        self.db=self.root/"compliance.sqlite3"

    def _restore_env(self):
        if self.old_data is None:
            os.environ.pop("CYBERCHECK_DATA_DIR",None)
        else:
            os.environ["CYBERCHECK_DATA_DIR"]=self.old_data

    def submit(self,email,name="Alice",message="Demande de contact suffisamment longue."):
        return contact_request.submit({
            "category":"general",
            "name":name,
            "email":email,
            "phone":"",
            "message":message,
            "website":"",
            "consent":"yes",
        })

    def request(self,kind,email):
        return compliance_store.create_rights_request({
            "type":kind,
            "subjectRef":email,
            "notes":"",
        },self.db)

    def test_access_exports_only_exact_normalized_email_and_audits_hash(self):
        self.submit("alice@example.test")
        self.submit("ALICE@example.test",message="Deuxième message conservé pour Alice.")
        self.submit("bob@example.test",name="Bob",message="Message distinct appartenant à Bob.")
        req=self.request("access","alice@example.test")
        out=contact_request_rights.execute(req["id"],"alice@example.test",self.db)
        self.assertEqual(out["data"]["requestCount"],2)
        serialized=json.dumps(out["data"])
        self.assertIn("alice@example.test",serialized)
        self.assertNotIn("bob@example.test",serialized)
        audit=data_subject_rights.audit_rows(self.db)
        self.assertEqual(audit[0]["adapter"],contact_request_rights.ADAPTER)
        self.assertEqual(audit[0]["action"],"export_complete")
        self.assertNotIn("alice@example.test",repr(audit))

    def test_wrong_subject_is_rejected_before_store_read(self):
        self.submit("alice@example.test")
        req=self.request("access","alice@example.test")
        with self.assertRaises(PermissionError):
            contact_request_rights.execute(req["id"],"bob@example.test",self.db)

    def test_erasure_is_exact_physical_and_preserves_other_subjects(self):
        self.submit("alice@example.test")
        self.submit("alice@example.test",message="Autre demande Alice à effacer.")
        self.submit("bob@example.test",name="Bob",message="Message Bob à conserver.")
        req=self.request("erasure","alice@example.test")
        out=contact_request_rights.execute(req["id"],"alice@example.test",self.db)
        self.assertEqual(out["removedCount"],2)
        self.assertEqual(out["remainingCount"],0)
        self.assertEqual(contact_request.privacy_snapshot("alice@example.test")["requestCount"],0)
        self.assertEqual(contact_request.privacy_snapshot("bob@example.test")["requestCount"],1)
        audit=data_subject_rights.audit_rows(self.db)
        self.assertEqual(audit[0]["action"],"erasure_complete")
        with self.assertRaisesRegex(RuntimeError,"adaptateur déjà exécuté"):
            contact_request_rights.execute(req["id"],"alice@example.test",self.db)

    def test_dispatch_and_completion_plan_capability_include_contact_adapter(self):
        self.submit("alice@example.test")
        req=self.request("portability","alice@example.test")
        out=rights_execution_dispatch.execute({
            "id":req["id"],
            "subjectRef":"alice@example.test",
            "adapter":contact_request_rights.ADAPTER,
        },self.db)
        self.assertEqual(out["adapter"],contact_request_rights.ADAPTER)
        capability=rights_execution_dispatch.capability(self.db)
        self.assertEqual(
            capability["supportedAdapters"][contact_request_rights.ADAPTER],
            ["access","portability","erasure"],
        )
        self.assertTrue(capability["contactRequests"]["bound"])

    def test_dispatch_rejects_extra_fields(self):
        req=self.request("access","alice@example.test")
        with self.assertRaises(ValueError):
            rights_execution_dispatch.execute({
                "id":req["id"],
                "subjectRef":"alice@example.test",
                "adapter":contact_request_rights.ADAPTER,
                "extra":"no",
            },self.db)


if __name__=="__main__":
    unittest.main()
