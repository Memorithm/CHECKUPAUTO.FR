import unittest
from mercure_vl_appointment_slot_proof import verify

class Tests(unittest.TestCase):
    def test_exact_local_slot(self):
        self.assertTrue(verify(row={"date_rdv":"2026-10-14T09:00:00"},
                               expected_date="2026-10-14",expected_time="09:00"))

    def test_wrong_time_rejected(self):
        with self.assertRaisesRegex(ValueError,"slot_mismatch"):
            verify(row={"date_rdv":"2026-10-14T09:30:00"},
                   expected_date="2026-10-14",expected_time="09:00")

    def test_missing_provider_datetime_rejected(self):
        with self.assertRaisesRegex(ValueError,"datetime_missing"):
            verify(row={},expected_date="2026-10-14",expected_time="09:00")

    def test_timezone_normalization(self):
        self.assertTrue(verify(row={"date_rdv":"2026-10-14T07:00:00Z"},
                               expected_date="2026-10-14",expected_time="09:00"))
