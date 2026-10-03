import os,unittest
from unittest import mock
import mercure_provider_coverage as m
class MercureEvidenceContractTest(unittest.TestCase):
 def test_no_evidence_never_attests_provider_boundary(self):
  keys=[m.HISTORY_START_ENV,m.FUTURE_DAYS_ENV,m.EVIDENCE_SHA256_ENV,m.APPOINTMENT_SOURCE_ENV,m.APPOINTMENT_EVIDENCE_SHA256_ENV,m.VEHICLE_SOURCE_ENV,m.VEHICLE_EVIDENCE_SHA256_ENV]
  with mock.patch.dict(os.environ,{k:"" for k in keys},clear=False):
   state=m.boundary()
  self.assertFalse(state["attested"])
  self.assertEqual(state["state"],"unconfigured")
if __name__=="__main__": unittest.main()
