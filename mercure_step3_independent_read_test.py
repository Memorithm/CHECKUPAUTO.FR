import unittest
from mercure_booking_identity_evidence import VerifiedBookingIdentity
from mercure_step3_independent_read import verify
class Tests(unittest.TestCase):
 def test_requires_calendar(self):
  proof=VerifiedBookingIdentity("ref","account","vehicle","technical",True)
  with self.assertRaises(ValueError):
   verify(reference="ref",account_id="account",vehicle_id="vehicle",service="technical",provider_evidence=proof,calendar_verified=False)
 def test_identity_match(self):
  proof=VerifiedBookingIdentity("ref","account","vehicle","technical",True)
  self.assertTrue(verify(reference="ref",account_id="account",vehicle_id="vehicle",service="technical",provider_evidence=proof,calendar_verified=True)["confirmed"])
