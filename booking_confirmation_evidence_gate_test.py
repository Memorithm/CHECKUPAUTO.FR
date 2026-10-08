import unittest
from mercure_booking_identity_evidence import VerifiedBookingIdentity
from booking_confirmation_evidence_gate import can_confirm

class Tests(unittest.TestCase):
    def setUp(self):
        self.kw=dict(reference="mercure-123",account_id="account-1",vehicle_id="vehicle-1",service="technical")
        self.proof=VerifiedBookingIdentity("mercure-123","account-1","vehicle-1","technical",True)
    def test_verified(self):
        self.assertTrue(can_confirm(**self.kw,evidence=self.proof,calendar_verified=True))
    def test_false_or_truthy(self):
        for flag in (False,"true",1,None):
            self.assertFalse(can_confirm(**self.kw,evidence=self.proof,calendar_verified=flag))
    def test_unverified(self):
        with self.assertRaises(ValueError):
            can_confirm(**self.kw,evidence=None,calendar_verified=True)
if __name__=="__main__": unittest.main()
