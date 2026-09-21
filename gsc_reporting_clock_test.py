import datetime
import unittest
from unittest.mock import patch

import gsc_client as gsc


class GSCReportingClockTest(unittest.TestCase):
    def test_reporting_day_uses_pacific_summer_boundary(self):
        before_midnight = datetime.datetime(
            2026, 7, 1, 6, 30, tzinfo=datetime.timezone.utc
        )
        after_midnight = datetime.datetime(
            2026, 7, 1, 7, 30, tzinfo=datetime.timezone.utc
        )
        self.assertEqual(
            gsc.reporting_today(before_midnight), datetime.date(2026, 6, 30)
        )
        self.assertEqual(
            gsc.reporting_today(after_midnight), datetime.date(2026, 7, 1)
        )

    def test_reporting_day_uses_pacific_winter_boundary(self):
        before_midnight = datetime.datetime(
            2026, 1, 1, 7, 30, tzinfo=datetime.timezone.utc
        )
        after_midnight = datetime.datetime(
            2026, 1, 1, 8, 30, tzinfo=datetime.timezone.utc
        )
        self.assertEqual(
            gsc.reporting_today(before_midnight), datetime.date(2025, 12, 31)
        )
        self.assertEqual(
            gsc.reporting_today(after_midnight), datetime.date(2026, 1, 1)
        )

    def test_performance_uses_complete_pacific_days(self):
        with patch(
            'gsc_client.reporting_today', return_value=datetime.date(2026, 9, 21)
        ):
            with patch('gsc_client._analytics_query', return_value={}) as query:
                report = gsc.performance('https://www.checkupauto.fr/', 28)
        self.assertEqual(report['startDate'], '2026-08-24')
        self.assertEqual(report['endDate'], '2026-09-20')
        self.assertEqual(query.call_count, 4)
        for call in query.call_args_list:
            self.assertEqual(call.args[1:3], ('2026-08-24', '2026-09-20'))


if __name__ == '__main__':
    unittest.main()
