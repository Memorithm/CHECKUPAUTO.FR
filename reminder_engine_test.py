import datetime
import unittest
from zoneinfo import ZoneInfo

import reminder_engine as reminders


class ReminderEngineTest(unittest.TestCase):
    def test_default_plan_matches_ios_policy(self):
        now = datetime.datetime(2026, 9, 19, 8, 0, tzinfo=ZoneInfo("Europe/Paris"))
        events = reminders.plan("2027-01-18", now=now)
        self.assertEqual([event.days_before for event in events], [60, 30, 15, 7, 1])
        self.assertTrue(all(event.send_at.hour == 9 for event in events))

    def test_past_reminders_are_removed_from_plan(self):
        now = datetime.datetime(2027, 1, 5, 10, 0, tzinfo=ZoneInfo("Europe/Paris"))
        events = reminders.plan("2027-01-18", now=now)
        self.assertEqual([event.days_before for event in events], [7, 1])

    def test_next_reminder_is_chronological(self):
        now = datetime.datetime(2026, 10, 1, 8, 0, tzinfo=ZoneInfo("Europe/Paris"))
        result = reminders.next_reminder("2026-12-31", now=now)
        self.assertEqual(result["daysBefore"], 60)
        self.assertEqual(result["sendAt"], "2026-11-01T09:00:00+01:00")

    def test_timezone_and_dst_are_explicit(self):
        now = datetime.datetime(2026, 9, 19, 8, 0, tzinfo=datetime.timezone.utc)
        events = reminders.plan("2026-11-01", now=now, lead_days=[7])
        self.assertEqual(events[0].send_at.tzinfo, ZoneInfo("Europe/Paris"))
        self.assertEqual(events[0].send_at.hour, 9)

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            reminders.plan("not-a-date")
        with self.assertRaises(ValueError):
            reminders.plan("2027-01-01", timezone="Mars/Paris")
        with self.assertRaises(ValueError):
            reminders.plan("2027-01-01", hour=29)


if __name__ == "__main__":
    unittest.main()
