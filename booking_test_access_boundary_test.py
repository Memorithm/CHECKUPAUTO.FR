from pathlib import Path
import datetime
import tempfile
import unittest
from unittest import mock

import analytics_store as analytics
import booking_test


class BookingTestAccessBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous_db = analytics.DB
        analytics.DB = Path(self.tmp.name) / 'analytics.sqlite3'
        booking_test.init_db()

    def tearDown(self):
        analytics.DB = self.previous_db
        self.tmp.cleanup()

    def test_unknown_and_expired_sessions_share_bounded_error(self):
        now = datetime.datetime(2026, 9, 21, 5, 30, tzinfo=datetime.timezone.utc)
        with mock.patch.object(booking_test, '_now', return_value=now):
            session = booking_test.create_session()

        with self.assertRaises(PermissionError) as unknown:
            booking_test.status('unknown-token-that-must-not-leak-state')
        self.assertEqual(str(unknown.exception), booking_test.ACCESS_DENIED)

        expired_at = now + datetime.timedelta(minutes=booking_test.TTL_MINUTES + 1)
        with mock.patch.object(booking_test, '_now', return_value=expired_at):
            with self.assertRaises(PermissionError) as expired:
                booking_test.status(session['token'])
        self.assertEqual(str(expired.exception), booking_test.ACCESS_DENIED)
        self.assertEqual(str(unknown.exception), str(expired.exception))

    def test_valid_session_still_returns_status(self):
        now = datetime.datetime(2026, 9, 21, 5, 30, tzinfo=datetime.timezone.utc)
        with mock.patch.object(booking_test, '_now', return_value=now):
            session = booking_test.create_session()
            result = booking_test.status(session['token'])
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'ready')


if __name__ == '__main__':
    unittest.main()
