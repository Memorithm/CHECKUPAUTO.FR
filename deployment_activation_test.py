from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import deployment_activation as activation
import deployment_center as center
import deployment_transport as transport


SHA = "a" * 40
PREVIOUS_SHA = "b" * 40


class DeploymentActivationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.known_hosts = self.root / "known_hosts"
        self.known_hosts.write_text("ssh.example.net ssh-ed25519 AAAATEST\n", encoding="utf-8")
        self.key = self.root / "id_ed25519"
        self.key.write_text("private-placeholder\n", encoding="utf-8")
        self.key.chmod(0o600)

    def tearDown(self):
        self.tmp.cleanup()

    def target(self):
        return center.validate_target({
            "provider": "planethoster-n0c",
            "host": "ssh.example.net",
            "username": "checkup",
            "domain": "www.checkupauto.fr",
        })

    def ready_capabilities(self):
        return center.CapabilityReport(
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

    def test_remote_program_compiles(self):
        compile(
            activation.remote_activation_program(),
            "<checkupauto-remote-activation>",
            "exec",
        )

    def test_activation_script_binds_private_current_and_shared_state(self):
        script = activation.remote_activation_script(self.target(), SHA)
        self.assertIn("PassengerAppRoot", script)
        self.assertIn("PassengerStartupFile passenger_wsgi.py", script)
        self.assertIn("PassengerPython", script)
        self.assertIn("SetEnv CYBERCHECK_PRIVATE_DIR", script)
        self.assertIn("CYBERCHECK_GSC_CREDENTIALS_PATH", script)
        self.assertIn("*/5 * * * *", script)
        self.assertIn("checkupauto-shared-tick.py", script)
        self.assertIn("tmp/restart.txt", script)
        self.assertIn("/api/admin/readiness", script)
        self.assertIn("launch_ready is not gate", script)
        self.assertIn("rollback completed", script)
        self.assertIn("O_NOFOLLOW", script)
        self.assertIn("shared state escapes private root", script)
        self.assertIn("admin credential symlink refused", script)
        self.assertNotIn("correct horse", script)
        self.assertNotIn("sudo ", script)

    def test_parse_activation_output_is_bounded(self):
        result = activation._parse_activation_output(
            "\n".join([
                f"CHECKUPAUTO_ACTIVATE_OK={SHA}",
                f"CHECKUPAUTO_PREVIOUS_SHA={PREVIOUS_SHA}",
                "CHECKUPAUTO_READINESS_STATE=degraded",
                "CHECKUPAUTO_ACTIVATION_ALLOWED=0",
                "CHECKUPAUTO_BLOCKER_COUNT=2",
            ]),
            SHA,
        )
        self.assertEqual(result.sha, SHA)
        self.assertEqual(result.previous_sha, PREVIOUS_SHA)
        self.assertEqual(result.readiness_state, "degraded")
        self.assertFalse(result.activation_allowed)
        self.assertEqual(result.blocker_count, 2)

        invalid_rows = [
            f"CHECKUPAUTO_ACTIVATE_OK={'0' * 40}\nCHECKUPAUTO_PREVIOUS_SHA=none\nCHECKUPAUTO_READINESS_STATE=ready\nCHECKUPAUTO_ACTIVATION_ALLOWED=1\nCHECKUPAUTO_BLOCKER_COUNT=0",
            f"CHECKUPAUTO_ACTIVATE_OK={SHA}\nCHECKUPAUTO_PREVIOUS_SHA=none\nCHECKUPAUTO_READINESS_STATE=unknown\nCHECKUPAUTO_ACTIVATION_ALLOWED=1\nCHECKUPAUTO_BLOCKER_COUNT=0",
            f"CHECKUPAUTO_ACTIVATE_OK={SHA}\nCHECKUPAUTO_PREVIOUS_SHA=none\nCHECKUPAUTO_READINESS_STATE=ready\nCHECKUPAUTO_ACTIVATION_ALLOWED=yes\nCHECKUPAUTO_BLOCKER_COUNT=0",
            f"CHECKUPAUTO_ACTIVATE_OK={SHA}\nCHECKUPAUTO_PREVIOUS_SHA=none\nCHECKUPAUTO_READINESS_STATE=ready\nCHECKUPAUTO_ACTIVATION_ALLOWED=1\nCHECKUPAUTO_BLOCKER_COUNT=-1",
        ]
        for row in invalid_rows:
            with self.subTest(row=row), self.assertRaisesRegex(RuntimeError, "invalide"):
                activation._parse_activation_output(row, SHA)

    def test_activation_refuses_unready_target_before_transport(self):
        with self.assertRaisesRegex(RuntimeError, "non prête"):
            activation.activate_release(
                self.target(),
                center.CapabilityReport(python_version="Python 3.12"),
                self.known_hosts,
                transport.SSHCredential(identity_file=str(self.key)),
                SHA,
            )

    @mock.patch("deployment_activation.subprocess.run")
    def test_key_activation_uses_strict_ssh_transport(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="\n".join([
                f"CHECKUPAUTO_ACTIVATE_OK={SHA}",
                "CHECKUPAUTO_PREVIOUS_SHA=none",
                "CHECKUPAUTO_READINESS_STATE=configuration_required",
                "CHECKUPAUTO_ACTIVATION_ALLOWED=0",
                "CHECKUPAUTO_BLOCKER_COUNT=1",
            ]),
            stderr="",
        )
        result = activation.activate_release(
            self.target(),
            self.ready_capabilities(),
            self.known_hosts,
            transport.SSHCredential(identity_file=str(self.key)),
            SHA,
        )
        self.assertEqual(result.sha, SHA)
        command = run.call_args.args[0]
        joined = " ".join(command)
        self.assertIn("StrictHostKeyChecking=yes", joined)
        self.assertIn("BatchMode=yes", joined)
        self.assertEqual(command[-2:], ["sh", "-s"])
        self.assertNotIn("password", joined.lower())

    @mock.patch("deployment_activation.activate_release")
    def test_explicit_rollback_reuses_verified_activation_path(self, activate):
        expected = activation.ActivationResult(
            sha=PREVIOUS_SHA,
            previous_sha=SHA,
            readiness_state="ready",
            activation_allowed=True,
            blocker_count=0,
        )
        activate.return_value = expected
        result = activation.rollback_release(
            self.target(),
            self.ready_capabilities(),
            self.known_hosts,
            transport.SSHCredential(identity_file=str(self.key)),
            PREVIOUS_SHA,
        )
        self.assertEqual(result, expected)
        self.assertEqual(activate.call_args.args[4], PREVIOUS_SHA)

    def test_invalid_release_sha_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "SHA"):
            activation.remote_activation_script(self.target(), "main")


if __name__ == "__main__":
    unittest.main()
