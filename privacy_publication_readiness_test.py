import tempfile,unittest
from pathlib import Path
import compliance_store
class PrivacyPublicationReadinessTest(unittest.TestCase):
 def test_missing_privacy_is_reported(self):
  with tempfile.TemporaryDirectory() as tmp:
   db=Path(tmp)/"c.sqlite3"
   state=compliance_store.summary(db)
   self.assertIn("privacy",state["missingDocuments"])
   self.assertFalse(state["readyForPublicContracting"])
if __name__=="__main__": unittest.main()
