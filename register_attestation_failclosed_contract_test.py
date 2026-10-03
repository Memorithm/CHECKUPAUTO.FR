import tempfile,unittest
from pathlib import Path
import compliance_register_attestation as a
class RegisterAttestationContractTest(unittest.TestCase):
 def test_unreviewed_register_is_not_current(self):
  with tempfile.TemporaryDirectory() as tmp:
   state=a.status(Path(tmp)/"c.sqlite3")
   self.assertTrue(state["required"])
   self.assertFalse(state["current"])
if __name__=="__main__": unittest.main()
