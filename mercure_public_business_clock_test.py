import datetime
import unittest
from unittest import mock

import mercure_public_client as mercure_public


class MercurePublicBusinessClockTest(unittest.TestCase):
    def test_current_paris_business_day_is_accepted(self):
        today = datetime.date(2026, 9, 21)
        with mock.patch.object(mercure_public.mercure_admin, "business_today", return_value=today) as clock:
            self.assertEqual(mercure_public._date("2026-09-21"), "2026-09-21")
        clock.assert_called_once_with()

    def test_previous_paris_business_day_is_rejected(self):
        today = datetime.date(2026, 9, 21)
        with mock.patch.object(mercure_public.mercure_admin, "business_today", return_value=today):
            with self.assertRaisesRegex(ValueError, "passée"):
                mercure_public._date("2026-09-20")

    def test_provider_safety_horizon_uses_same_business_day(self):
        today = datetime.date(2026, 9, 21)
        with mock.patch.object(mercure_public.mercure_admin, "business_today", return_value=today):
            self.assertEqual(mercure_public._date("2027-03-20"), "2027-03-20")
            with self.assertRaisesRegex(ValueError, "éloignée"):
                mercure_public._date("2027-03-21")


if __name__ == "__main__":
    unittest.main()
