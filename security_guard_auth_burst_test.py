import unittest
from unittest import mock

import security_guard as guard


class SecurityGuardAuthBurstTest(unittest.TestCase):
    def setUp(self):
        guard._AUTH_FAIL.clear()
        guard._AUTH_FAIL_BURST.clear()
        guard._BANNED.clear()
        guard._RISK.clear()
        guard._STATE_WRITE.clear()

    def test_parallel_basic_auth_failures_count_as_one_attempt_per_burst(self):
        with mock.patch.object(
            guard.time,
            "monotonic",
            side_effect=[100.0, 101.0, 104.9, 106.0],
        ), mock.patch.object(
            guard,
            "_add_risk",
            return_value=20.0,
        ) as add_risk, mock.patch.object(
            guard,
            "_record",
        ) as record, mock.patch.object(
            guard.alerts,
            "emit",
        ), mock.patch.object(
            guard,
            "_ban",
        ) as ban:
            for _ in range(4):
                guard.auth_failure("client-a", "/api/admin/config")

        self.assertEqual(add_risk.call_count, 2)
        self.assertEqual(record.call_count, 2)
        self.assertEqual(len(guard._AUTH_FAIL["client-a"]), 2)
        ban.assert_not_called()

    def test_six_separate_auth_bursts_still_trigger_bruteforce_quarantine(self):
        with mock.patch.object(
            guard.time,
            "monotonic",
            side_effect=[100.0, 106.0, 112.0, 118.0, 124.0, 130.0],
        ), mock.patch.object(
            guard,
            "_add_risk",
            return_value=20.0,
        ) as add_risk, mock.patch.object(
            guard,
            "_record",
        ), mock.patch.object(
            guard.alerts,
            "emit",
        ), mock.patch.object(
            guard,
            "_ban",
        ) as ban:
            for _ in range(6):
                guard.auth_failure("client-b", "/admin/")

        self.assertEqual(add_risk.call_count, 6)
        self.assertEqual(len(guard._AUTH_FAIL["client-b"]), 6)
        ban.assert_called_once_with("client-b", 1800, "admin_bruteforce")


if __name__ == "__main__":
    unittest.main()
