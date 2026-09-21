import datetime
import unittest
from unittest import mock

import mercure_admin_client as mercure
import reminder_dispatch as dispatch


class BusinessClockBoundaryTest(unittest.TestCase):
    def test_business_today_uses_paris_civil_day_in_winter(self):
        instant = datetime.datetime(2026, 1, 15, 23, 30, tzinfo=datetime.timezone.utc)
        self.assertEqual(mercure.business_today(instant), datetime.date(2026, 1, 16))

    def test_business_today_uses_paris_civil_day_in_summer(self):
        instant = datetime.datetime(2026, 9, 20, 22, 30, tzinfo=datetime.timezone.utc)
        self.assertEqual(mercure.business_today(instant), datetime.date(2026, 9, 21))

    def test_period_uses_business_day(self):
        with mock.patch.object(mercure, "business_today", return_value=datetime.date(2026, 9, 21)):
            days, start, end = mercure._period(2)
        self.assertEqual(days, 2)
        self.assertEqual(start, "2026-09-20")
        self.assertEqual(end, "2026-09-22")

    def test_review_followup_window_uses_business_day(self):
        session = object()
        with mock.patch.object(mercure, "business_today", return_value=datetime.date(2026, 9, 21)), \
             mock.patch.object(mercure, "_session", return_value=session), \
             mock.patch.object(mercure, "_appointments", return_value=[]) as appointments, \
             mock.patch.object(mercure, "_calendar_events", return_value=[]) as events:
            rows = mercure.review_followup_rows(2)
        self.assertEqual(rows, [])
        appointments.assert_called_once_with(session, "2026-09-20", "2026-09-22")
        events.assert_called_once_with(session, "2026-09-20", "2026-09-22")

    def test_reminder_sync_defaults_to_mercure_business_day(self):
        today = datetime.date(2026, 9, 21)
        floor = today - datetime.timedelta(days=dispatch.BACKFILL_DAYS)
        with mock.patch.object(dispatch, "init_db"), \
             mock.patch.object(mercure, "business_today", return_value=today), \
             mock.patch.object(mercure, "session_status", return_value={"connected": True}), \
             mock.patch.object(mercure, "reminder_source_rows", return_value=[]) as source_rows, \
             mock.patch.object(dispatch, "_meta", return_value=floor.isoformat()), \
             mock.patch.object(dispatch, "_set_meta"), \
             mock.patch.object(dispatch, "_quarantined_count", return_value=0):
            result = dispatch.sync_once()
        self.assertTrue(result["ok"])
        source_rows.assert_called_once_with("2026-09-07", "2026-09-22")


if __name__ == "__main__":
    unittest.main()
