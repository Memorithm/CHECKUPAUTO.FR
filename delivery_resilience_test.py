import datetime
import unittest

import delivery_resilience as resilience


class DeliveryResilienceTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime.datetime(2026, 9, 19, 16, 0, tzinfo=datetime.timezone.utc)

    def test_retry_after_delta_seconds_is_bounded(self):
        self.assertEqual(resilience.retry_after_seconds("60", now=self.now), 60)
        self.assertEqual(
            resilience.retry_after_seconds("999999", now=self.now),
            resilience.MAX_BACKOFF_SECONDS,
        )

    def test_retry_after_http_date_is_supported(self):
        value = "Sat, 19 Sep 2026 16:02:00 GMT"
        self.assertEqual(resilience.retry_after_seconds(value, now=self.now), 120)

    def test_http_date_rounds_up_to_avoid_early_retry(self):
        now = self.now + datetime.timedelta(microseconds=200_000)
        value = "Sat, 19 Sep 2026 16:02:00 GMT"
        self.assertEqual(resilience.retry_after_seconds(value, now=now), 120)

    def test_invalid_retry_after_is_ignored(self):
        self.assertIsNone(resilience.retry_after_seconds("not-a-date", now=self.now))

    def test_backoff_is_deterministic_jittered_and_bounded(self):
        first = resilience.backoff_seconds("push:apns:sandbox", 1, now=self.now)
        again = resilience.backoff_seconds("push:apns:sandbox", 1, now=self.now)
        late = resilience.backoff_seconds("push:apns:sandbox", 99, now=self.now)
        self.assertEqual(first, again)
        self.assertGreaterEqual(first, 1)
        self.assertLessEqual(first, resilience.MAX_BACKOFF_SECONDS)
        self.assertLessEqual(late, resilience.MAX_BACKOFF_SECONDS)

    def test_retry_after_is_a_minimum_when_present(self):
        delay = resilience.backoff_seconds(
            "push:apns:production", 1, retry_after="120", now=self.now
        )
        self.assertGreaterEqual(delay, 120)


if __name__ == "__main__":
    unittest.main()
