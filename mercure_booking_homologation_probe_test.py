import unittest
from unittest.mock import patch

import mercure_booking_homologation_probe as probe


class MercureHomologationProbeTests(unittest.TestCase):
    def test_readonly_calendar_report_contains_no_customer_data(self):
        event={"id":"private-appointment","nom":"PRIVATE NAME","email":"private@example.test"}
        with patch.object(probe.mercure,"_session",return_value=object()), \
             patch.object(probe.mercure,"_calendar_events",return_value=[event]) as calendar:
            result=probe.inspect("2026-10-10")
        calendar.assert_called_once()
        self.assertEqual(result["eventCount"],1)
        self.assertTrue(result["calendarReadable"])
        self.assertFalse(result["providerWritesPerformed"])
        self.assertFalse(result["bookingConfirmed"])
        self.assertNotIn("private-appointment",str(result))
        self.assertNotIn("private@example.test",str(result))

    def test_malformed_provider_calendar_is_rejected(self):
        with patch.object(probe.mercure,"_session",return_value=object()), \
             patch.object(probe.mercure,"_calendar_events",return_value={"events":[]}):
            with self.assertRaisesRegex(RuntimeError,"invalid_calendar"):
                probe.inspect("2026-10-10")


if __name__=="__main__":
    unittest.main()
