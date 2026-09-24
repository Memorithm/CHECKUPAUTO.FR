import contextlib
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "scripts" / "checkupauto-shared-tick.py"


class SharedHostTickTest(unittest.TestCase):
    def load_module(self, root: Path):
        private = root / "private"
        private.mkdir(parents=True, exist_ok=True)
        (private / "admin-password").write_text("test-password\n", encoding="utf-8")
        env = {
            "CYBERCHECK_PRIVATE_DIR": str(private),
            "CYBERCHECK_DATA_DIR": str(root / "data"),
            "CYBERCHECK_SECURITY_DIR": str(root / "security"),
            "CYBERCHECK_INTEGRITY_DIR": str(root / "integrity"),
            "CYBERCHECK_GSC_CREDENTIALS_PATH": str(private / "gsc.json"),
            "CYBERCHECK_SITE_CONFIG_PATH": str(root / "data" / "site-config.json"),
        }
        spec = importlib.util.spec_from_file_location("checkupauto_shared_tick_test_module", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, env, clear=False):
            spec.loader.exec_module(module)
        return module, env

    def test_tick_runs_one_iteration_without_background_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            module, env = self.load_module(Path(tmp))
            module.admin_server.initialize_runtime = mock.Mock(
                return_value={"coreReady": True, "backgroundReady": False}
            )
            functions = [
                (module.booking_test, "purge_expired"),
                (module.booking_conversion_reconciliation, "process_once"),
                (module.reminder_dispatch, "process_once"),
                (module.mobile_authoritative_sync, "sync_once"),
                (module.mobile_reminder_dispatch, "process_once"),
                (module.review_followup, "process_once"),
                (module.withdrawal_service, "dispatch_pending"),
                (module.retention_enforcement, "process_once"),
                (module.referral_wallet_final_purge_runner, "process_once"),
                (module.security_alerts, "retry_pending"),
            ]
            for owner, name in functions:
                patcher = mock.patch.object(owner, name, return_value={"ok": True})
                patcher.start()
                self.addCleanup(patcher.stop)

            with mock.patch.dict(os.environ, env, clear=False):
                result = module.tick()

            self.assertTrue(result["ok"])
            self.assertEqual(len(result["tasks"]), 10)
            self.assertEqual(result["tasks"][1]["name"], "booking_conversion_reconciliation")
            self.assertEqual(result["tasks"][2]["name"], "reminder_dispatch")
            self.assertEqual(result["tasks"][7]["name"], "retention_enforcement")
            self.assertEqual(result["tasks"][8]["name"], "referral_wallet_final_purge")
            module.admin_server.initialize_runtime.assert_called_once_with(background=False)
            for owner, name in functions:
                getattr(owner, name).assert_called_once_with()

    def test_tick_sanitizes_task_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            module, env = self.load_module(Path(tmp))
            module.admin_server.initialize_runtime = mock.Mock()
            patches = [
                mock.patch.object(
                    module.booking_test, "purge_expired",
                    side_effect=RuntimeError("secret-token-should-not-leak"),
                ),
                mock.patch.object(module.booking_conversion_reconciliation, "process_once", return_value={"ok": True}),
                mock.patch.object(module.reminder_dispatch, "process_once", return_value={"ok": True}),
                mock.patch.object(module.mobile_authoritative_sync, "sync_once", return_value={"ok": True}),
                mock.patch.object(module.mobile_reminder_dispatch, "process_once", return_value={"ok": True}),
                mock.patch.object(module.review_followup, "process_once", return_value={"ok": True}),
                mock.patch.object(module.withdrawal_service, "dispatch_pending", return_value={"ok": True}),
                mock.patch.object(module.retention_enforcement, "process_once", return_value={"ok": True}),
                mock.patch.object(
                    module.referral_wallet_final_purge_runner,
                    "process_once",
                    return_value={"ok": True},
                ),
                mock.patch.object(module.security_alerts, "retry_pending", return_value={"ok": True}),
            ]
            for patcher in patches:
                patcher.start()
                self.addCleanup(patcher.stop)

            with mock.patch.dict(os.environ, env, clear=False):
                result = module.tick()

            self.assertFalse(result["ok"])
            failed = result["tasks"][0]
            self.assertEqual(failed["error"], "RuntimeError")
            self.assertNotIn("secret-token", json.dumps(result))

    def test_main_refuses_overlapping_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module, env = self.load_module(root)
            data = Path(env["CYBERCHECK_DATA_DIR"])
            data.mkdir(parents=True, exist_ok=True)
            lock_path = data / ".shared-host-tick.lock"
            with lock_path.open("a+") as held:
                fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                output = io.StringIO()
                with mock.patch.dict(os.environ, env, clear=False), \
                     mock.patch.object(module, "tick", side_effect=AssertionError("must not run")), \
                     contextlib.redirect_stdout(output):
                    code = module.main()

            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["state"], "already_running")
            self.assertTrue(payload["ok"])


if __name__ == "__main__":
    unittest.main()
