import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import deployment_admin as admin
import deployment_center as center
import deployment_executor as executor


SHA = "a" * 40


class DeploymentAdminTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.private = self.root / "private"
        self.env = mock.patch.dict(os.environ, {
            "CYBERCHECK_PRIVATE_DIR": str(self.private),
            "CYBERCHECK_DEPLOYMENT_VAULT": str(self.private / "vault"),
            "CYBERCHECK_DEPLOYMENT_KNOWN_HOSTS": str(self.private / "known_hosts"),
            "CYBERCHECK_DEPLOYMENT_JOBS_DIR": str(self.private / "jobs"),
        }, clear=False)
        self.env.start()
        self.private.mkdir(parents=True, exist_ok=True)
        (self.private / "admin-password").write_text(
            "local-admin-secret-value\n",
            encoding="utf-8",
        )
        (self.private / "admin-password").chmod(0o600)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    @staticmethod
    def payload(password="secret-value"):
        return {
            "name": "production",
            "target": {
                "provider": "planethoster-n0c",
                "host": "ssh.example.net",
                "username": "checkup",
                "domain": "www.checkupauto.fr",
                "authMode": "password",
            },
            "credential": {"password": password},
        }

    def test_default_deployment_state_stays_inside_dedicated_private_subdirectory(self):
        with mock.patch.dict(
            os.environ,
            {"CYBERCHECK_PRIVATE_DIR": str(self.private)},
            clear=True,
        ):
            self.assertEqual(
                admin._deployment_state_dir(),
                self.private / "deployment",
            )
            self.assertEqual(
                admin._vault_root(),
                self.private / "deployment" / "vault",
            )
            self.assertEqual(
                admin._known_hosts_path(),
                self.private / "deployment" / "known_hosts",
            )
            self.assertEqual(
                admin._jobs_dir(),
                self.private / "deployment" / "jobs",
            )

    def test_save_target_redacts_secret_and_preserves_it_on_edit(self):
        first = admin.save_target(self.payload())
        self.assertTrue(first["ok"])
        self.assertNotIn("secret-value", str(first))
        self.assertEqual(first["target"]["webRootPath"], "public_html")

        edited = self.payload(password="")
        edited["target"]["domain"] = "app.checkupauto.fr"
        second = admin.save_target(edited)
        self.assertEqual(second["target"]["domain"], "app.checkupauto.fr")
        record = admin._vault().load("production")
        self.assertEqual(record["credential"]["password"], "secret-value")

    def test_status_never_exposes_credentials(self):
        admin.save_target(self.payload())
        with mock.patch.object(admin, "_current_sha", return_value=SHA):
            state = admin.status()
        self.assertEqual(state["currentSha"], SHA)
        self.assertNotIn("secret-value", str(state))
        self.assertTrue(state["targets"][0]["credentialStored"])

    @mock.patch.object(admin, "_fingerprint")
    @mock.patch.object(admin, "_scan_lines")
    def test_host_key_requires_rescan_of_exact_confirmed_fingerprint(self, scan, fingerprint):
        admin.save_target(self.payload())
        line = "[ssh.example.net]:5022 ssh-ed25519 AAAATEST"
        scan.return_value = [line]
        fingerprint.return_value = "SHA256:abcdefghijklmnopqrstuvwx1234567890ABCD"

        scanned = admin.scan_host_keys("production")
        self.assertEqual(len(scanned["keys"]), 1)
        trusted = admin.trust_host_key(
            "production",
            scanned["keys"][0]["fingerprint"],
        )
        self.assertEqual(
            trusted["trusted"]["fingerprint"],
            scanned["keys"][0]["fingerprint"],
        )
        raw = admin._known_hosts_path().read_text()
        self.assertIn("ssh-ed25519 AAAATEST", raw)
        self.assertNotIn("secret-value", raw)
        self.assertEqual(scan.call_count, 2)

    def test_trust_rejects_changed_host_key(self):
        admin.save_target(self.payload())
        with mock.patch.object(
            admin,
            "_scan_lines",
            return_value=["[ssh.example.net]:5022 ssh-ed25519 AAAAOTHER"],
        ), mock.patch.object(
            admin,
            "_fingerprint",
            return_value="SHA256:ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ",
        ):
            with self.assertRaisesRegex(RuntimeError, "changé"):
                admin.trust_host_key(
                    "production",
                    "SHA256:abcdefghijklmnopqrstuvwx1234567890ABCD",
                )

    @mock.patch.object(admin.transport, "probe_target")
    def test_probe_returns_bounded_capabilities_and_assessment(self, probe):
        admin.save_target(self.payload())
        admin._known_hosts_path().parent.mkdir(parents=True, exist_ok=True)
        admin._known_hosts_path().write_text(
            "[ssh.example.net]:5022 ssh-ed25519 AAAATEST\n",
            encoding="utf-8",
        )
        probe.return_value = center.CapabilityReport(
            python_version="Python 3.12.8",
            passenger=True,
            cron=True,
            symlink=True,
            writable_root=True,
            writable_web_root=True,
            free_disk_mb=4096,
            passenger_wsgi_adapter=True,
            shared_host_tick=True,
        )
        result = admin.probe("production")
        self.assertTrue(result["assessment"]["ok"])
        self.assertTrue(result["capabilities"]["passenger"])
        self.assertNotIn("secret-value", str(result))

    @mock.patch.object(admin.executor, "execute_deployment")
    @mock.patch.object(admin, "_current_sha", return_value=SHA)
    def test_start_job_is_async_and_persists_sanitized_result(self, current_sha, execute):
        admin.save_target(self.payload())
        admin._known_hosts_path().parent.mkdir(parents=True, exist_ok=True)
        admin._known_hosts_path().write_text(
            "[ssh.example.net]:5022 ssh-ed25519 AAAATEST\n",
            encoding="utf-8",
        )
        execute.return_value = executor.DeploymentExecutionResult(
            action="install",
            sha=SHA,
            previous_sha="",
            staged=True,
            release_path="/home/checkup/.checkupauto/releases/" + SHA,
            archive_sha256="b" * 64,
            file_count=123,
            readiness_state="configuration_required",
            activation_allowed=False,
            blocker_count=1,
        )
        started = admin.start_job("production", "install")
        self.assertEqual(started["state"], "queued")

        deadline = time.time() + 2
        state = started
        while time.time() < deadline:
            state = admin.job(started["id"])
            if state["state"] in {"succeeded", "failed"}:
                break
            time.sleep(0.01)
        self.assertEqual(state["state"], "succeeded")
        self.assertEqual(state["result"]["sha"], SHA)
        self.assertNotIn("releasePath", state["result"])
        self.assertNotIn("secret-value", str(state))
        self.assertNotIn("local-admin-secret-value", str(state))
        execute.assert_called_once()
        self.assertEqual(
            execute.call_args.kwargs["admin_password"],
            "local-admin-secret-value",
        )

    @mock.patch.object(admin.executor, "execute_deployment")
    @mock.patch.object(admin, "_current_sha", return_value=SHA)
    def test_job_waits_for_external_cutover_without_becoming_failed(
        self, current_sha, execute
    ):
        admin.save_target(self.payload())
        admin._known_hosts_path().parent.mkdir(parents=True, exist_ok=True)
        admin._known_hosts_path().write_text(
            "[ssh.example.net]:5022 ssh-ed25519 AAAATEST\n",
            encoding="utf-8",
        )
        execute.return_value = executor.DeploymentExecutionResult(
            action="install",
            sha=SHA,
            previous_sha="",
            staged=True,
            release_path="/home/checkup/.checkupauto/releases/" + SHA,
            archive_sha256="b" * 64,
            file_count=123,
            readiness_state="blocked_external",
            activation_allowed=False,
            blocker_count=1,
            activated=False,
            public_verified=False,
        )
        started = admin.start_job("production", "install")
        deadline = time.time() + 2
        state = started
        while time.time() < deadline:
            state = admin.job(started["id"])
            if state["state"] not in {"queued", "running"}:
                break
            time.sleep(0.01)
        self.assertEqual(state["state"], "waiting_external")
        self.assertFalse(state["result"]["activated"])
        self.assertFalse(state["result"]["publicVerified"])
        self.assertTrue(state["result"]["staged"])

    def test_local_admin_credential_must_be_private_and_valid(self):
        path = self.private / "admin-password"
        self.assertEqual(admin._local_admin_password(), "local-admin-secret-value")
        path.write_text("short\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "credential admin local invalide"):
            admin._local_admin_password()
        path.unlink()
        with self.assertRaisesRegex(RuntimeError, "credential admin local indisponible"):
            admin._local_admin_password()

    def test_execution_lock_rejects_parallel_job(self):
        admin.save_target(self.payload())
        handle = admin._execution_lock()
        try:
            with mock.patch.object(admin, "_current_sha", return_value=SHA):
                with self.assertRaisesRegex(RuntimeError, "déjà en cours"):
                    admin.start_job("production", "install")
        finally:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def test_key_path_from_admin_must_stay_inside_private_dir(self):
        payload = self.payload()
        payload["target"]["authMode"] = "key"
        payload["credential"] = {"identityFile": "/tmp/outside-key"}
        with self.assertRaisesRegex(ValueError, "espace privé"):
            admin.save_target(payload)


if __name__ == "__main__":
    unittest.main()
