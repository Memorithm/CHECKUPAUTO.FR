import unittest
from unittest import mock

import retention_enforcement as retention


class RetentionBackgroundWorkerTest(unittest.TestCase):
    def setUp(self):
        self.original_thread = retention._THREAD
        retention._THREAD = None
        retention._STOP.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        retention._STOP.set()
        retention._THREAD = self.original_thread

    def test_background_cycle_refuses_writes_while_migration_is_frozen(self):
        with mock.patch.object(
            retention.migration_write_freeze,
            "active",
            return_value=True,
        ), mock.patch.object(retention, "process_once") as process:
            result = retention.background_once("compliance.sqlite3")

        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "write_frozen")
        self.assertFalse(result["policyComplete"])
        process.assert_not_called()

    def test_background_cycle_fails_closed_when_freeze_state_is_unreadable(self):
        with mock.patch.object(
            retention.migration_write_freeze,
            "active",
            side_effect=RuntimeError("unreadable marker"),
        ), mock.patch.object(retention, "process_once") as process:
            result = retention.background_once("compliance.sqlite3")

        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "write_frozen_unverified")
        self.assertFalse(result["policyComplete"])
        process.assert_not_called()
        self.assertNotIn("unreadable", repr(result))

    def test_background_cycle_executes_ready_retention_when_unfrozen(self):
        expected = {
            "ok": True,
            "state": "partial_policy",
            "policyComplete": False,
            "blockerCount": 7,
        }
        with mock.patch.object(
            retention.migration_write_freeze,
            "active",
            return_value=False,
        ), mock.patch.object(
            retention,
            "process_once",
            return_value=expected,
        ) as process:
            result = retention.background_once("compliance.sqlite3")

        self.assertEqual(result, expected)
        process.assert_called_once_with("compliance.sqlite3")

    def test_start_is_idempotent_and_enforces_minimum_interval(self):
        thread = mock.Mock()
        thread.is_alive.return_value = True
        with mock.patch.object(retention, "init_db") as init_db, mock.patch.object(
            retention.threading,
            "Thread",
            return_value=thread,
        ) as thread_cls:
            retention.start(1)
            retention.start(1)

        self.assertEqual(init_db.call_count, 2)
        thread_cls.assert_called_once_with(
            target=retention._background_loop,
            args=(300,),
            daemon=True,
            name="CyberCheckRetention",
        )
        thread.start.assert_called_once()

    def test_run_once_serializes_through_private_implementation(self):
        expected = {"ok": True, "rules": []}
        with mock.patch.object(
            retention,
            "_run_once_unlocked",
            return_value=expected,
        ) as inner:
            result = retention.run_once(
                dry_run=True,
                db_path="compliance.sqlite3",
            )

        self.assertEqual(result, expected)
        inner.assert_called_once_with(
            dry_run=True,
            db_path="compliance.sqlite3",
        )


if __name__ == "__main__":
    unittest.main()
