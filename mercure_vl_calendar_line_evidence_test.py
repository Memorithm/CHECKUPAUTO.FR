import unittest
from mercure_vl_calendar_line_evidence import verify,MercureVlLineEvidenceError

class Tests(unittest.TestCase):
    def test_matching_vl_resource(self):
        result=verify({"resourceId":"454","extendedProps":{"ligneId":454,"centreTypeId":1}})
        self.assertEqual(result["lineId"],"454")
        self.assertFalse(result["slotAvailabilityVerified"])

    def test_mismatch_rejected(self):
        with self.assertRaisesRegex(MercureVlLineEvidenceError,"mismatch"):
            verify({"resourceId":"454","extendedProps":{"ligneId":455,"centreTypeId":1}})

    def test_heavy_vehicle_rejected(self):
        with self.assertRaisesRegex(MercureVlLineEvidenceError,"not_vl"):
            verify({"resourceId":"454","extendedProps":{"ligneId":454,"centreTypeId":2}})
