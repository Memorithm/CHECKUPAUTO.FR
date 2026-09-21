import datetime
import unittest

import review_followup as followup


class ReviewFollowupTimezoneTest(unittest.TestCase):
    def test_naive_summer_timestamp_uses_paris_dst(self):
        parsed = followup._parse_dt("2026-07-15 10:00:00")
        self.assertEqual(
            parsed,
            datetime.datetime(2026, 7, 15, 8, 0, tzinfo=datetime.timezone.utc),
        )

    def test_naive_winter_timestamp_uses_paris_standard_time(self):
        parsed = followup._parse_dt("2026-01-15 10:00:00")
        self.assertEqual(
            parsed,
            datetime.datetime(2026, 1, 15, 9, 0, tzinfo=datetime.timezone.utc),
        )

    def test_explicit_offset_is_preserved(self):
        parsed = followup._parse_dt("2026-07-15T10:00:00+02:00")
        self.assertEqual(
            parsed,
            datetime.datetime(2026, 7, 15, 8, 0, tzinfo=datetime.timezone.utc),
        )


if __name__ == "__main__":
    unittest.main()
