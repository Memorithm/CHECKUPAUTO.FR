from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

mercure_path = ROOT / "mercure_admin_client.py"
mercure = mercure_path.read_text()
old_import = "from collections import Counter, defaultdict\n"
if old_import not in mercure:
    raise SystemExit("mercure import anchor missing")
mercure = mercure.replace(old_import, old_import + "from zoneinfo import ZoneInfo\n", 1)
old_base = "BASE = 'https://rdv.checkupauto.fr'\n\n"
helper = """BASE = 'https://rdv.checkupauto.fr'\nMERCURE_TIMEZONE = ZoneInfo('Europe/Paris')\n\ndef business_today(now=None):\n    current = now if now is not None else datetime.datetime.now(datetime.timezone.utc)\n    if not isinstance(current, datetime.datetime):\n        raise TypeError('datetime attendu')\n    if current.tzinfo is None:\n        current = current.replace(tzinfo=datetime.timezone.utc)\n    return current.astimezone(MERCURE_TIMEZONE).date()\n\n"""
if old_base not in mercure:
    raise SystemExit("mercure base anchor missing")
mercure = mercure.replace(old_base, helper, 1)
count = mercure.count("datetime.date.today()")
if count != 3:
    raise SystemExit(f"expected 3 date.today() calls in mercure client, got {count}")
mercure = mercure.replace("datetime.date.today()", "business_today()")
mercure_path.write_text(mercure)

reminder_path = ROOT / "reminder_dispatch.py"
reminder = reminder_path.read_text()
old_today = "    today = today or datetime.date.today()\n"
if reminder.count(old_today) != 1:
    raise SystemExit("reminder sync today anchor missing or duplicated")
reminder = reminder.replace(old_today, "    today = today or mercure.business_today()\n", 1)
reminder_path.write_text(reminder)

test_path = ROOT / "business_clock_boundary_test.py"
test_path.write_text('''import datetime\nimport unittest\nfrom unittest import mock\n\nimport mercure_admin_client as mercure\nimport reminder_dispatch as dispatch\n\n\nclass BusinessClockBoundaryTest(unittest.TestCase):\n    def test_business_today_uses_paris_civil_day_in_winter(self):\n        instant = datetime.datetime(2026, 1, 15, 23, 30, tzinfo=datetime.timezone.utc)\n        self.assertEqual(mercure.business_today(instant), datetime.date(2026, 1, 16))\n\n    def test_business_today_uses_paris_civil_day_in_summer(self):\n        instant = datetime.datetime(2026, 9, 20, 22, 30, tzinfo=datetime.timezone.utc)\n        self.assertEqual(mercure.business_today(instant), datetime.date(2026, 9, 21))\n\n    def test_period_uses_business_day(self):\n        with mock.patch.object(mercure, "business_today", return_value=datetime.date(2026, 9, 21)):\n            days, start, end = mercure._period(2)\n        self.assertEqual(days, 2)\n        self.assertEqual(start, "2026-09-20")\n        self.assertEqual(end, "2026-09-22")\n\n    def test_review_followup_window_uses_business_day(self):\n        session = object()\n        with mock.patch.object(mercure, "business_today", return_value=datetime.date(2026, 9, 21)), \\\n             mock.patch.object(mercure, "_session", return_value=session), \\\n             mock.patch.object(mercure, "_appointments", return_value=[]) as appointments, \\\n             mock.patch.object(mercure, "_calendar_events", return_value=[]) as events:\n            rows = mercure.review_followup_rows(2)\n        self.assertEqual(rows, [])\n        appointments.assert_called_once_with(session, "2026-09-20", "2026-09-22")\n        events.assert_called_once_with(session, "2026-09-20", "2026-09-22")\n\n    def test_reminder_sync_defaults_to_mercure_business_day(self):\n        today = datetime.date(2026, 9, 21)\n        floor = today - datetime.timedelta(days=dispatch.BACKFILL_DAYS)\n        with mock.patch.object(dispatch, "init_db"), \\\n             mock.patch.object(mercure, "business_today", return_value=today), \\\n             mock.patch.object(mercure, "session_status", return_value={"connected": True}), \\\n             mock.patch.object(mercure, "reminder_source_rows", return_value=[]) as source_rows, \\\n             mock.patch.object(dispatch, "_meta", return_value=floor.isoformat()), \\\n             mock.patch.object(dispatch, "_set_meta"), \\\n             mock.patch.object(dispatch, "_quarantined_count", return_value=0):\n            result = dispatch.sync_once()\n        self.assertTrue(result["ok"])\n        source_rows.assert_called_once_with("2026-09-07", "2026-09-22")\n\n\nif __name__ == "__main__":\n    unittest.main()\n''')
