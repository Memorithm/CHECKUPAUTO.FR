import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import deployment_center as center
import deployment_transport as transport


class DeploymentTransportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.known_hosts = root / "known_hosts"
        self.known_hosts.write_text("example.net ssh-ed25519 AAAATEST\n", encoding="utf-8")
        self.key = root / "id_ed25519"
        self.key.write_text("private-placeholder", encoding="utf-8")
        self.key.chmod(0o600)

    def tearDown(self):
        self.tmp.cleanup()

    def target(self, **changes):
        payload = {
            "provider": "planethoster-n0c",
            "host": "ssh.example.net",
            "username": "checkup",
            "domain": "www.checkupauto.fr",
            "rootPath": "public_html",
            "authMode": "key",
        }
        payload.update(changes)
        return center.validate_target(payload)

    def test_key_auth_uses_strict_host_verification(self):
        args = transport.ssh_arguments(
            self.target(),
            self.known_hosts,
            transport.SSHCredential(identity_file=str(self.key)),
        )
        joined = " ".join(args)
        self.assertIn("StrictHostKeyChecking=yes", joined)
        self.assertIn(f"UserKnownHostsFile={self.known_hosts}", joined)
        self.assertIn("BatchMode=yes", joined)
        self.assertIn(str(self.key), args)
        self.assertEqual(args[-1], "checkup@ssh.example.net")

    def test_password_never_appears_in_ssh_arguments(self):
        password = "correct horse battery staple"
        args = transport.ssh_arguments(
            self.target(authMode="password"),
            self.known_hosts,
            transport.SSHCredential(password=password),
        )
        self.assertNotIn(password, " ".join(args))
        self.assertIn("PubkeyAuthentication=no", " ".join(args))

    def test_known_hosts_and_key_are_required(self):
        missing = Path(self.tmp.name) / "missing"
        with self.assertRaisesRegex(ValueError, "known_hosts"):
            transport.ssh_arguments(
                self.target(),
                missing,
                transport.SSHCredential(identity_file=str(self.key)),
            )
        with self.assertRaisesRegex(ValueError, "clé SSH"):
            transport.ssh_arguments(
                self.target(),
                self.known_hosts,
                transport.SSHCredential(identity_file=str(missing)),
            )

    def test_probe_script_is_non_secret_and_target_scoped(self):
        script = transport.remote_probe_script(self.target(rootPath="public_html/checkupauto"))
        self.assertIn("CHECKUPAUTO_PROBE_V1", script)
        self.assertIn("public_html/checkupauto", script)
        self.assertIn("ln -s", script)
        self.assertNotIn("password", script.lower())
        self.assertNotIn("admin-password", script)

    def test_parse_probe_returns_typed_capabilities(self):
        report = transport.parse_probe(
            """CHECKUPAUTO_PROBE_V1
python=Python 3.12.8
node=v22.22.3
passenger=1
systemd=0
cron=1
symlink=1
writable_root=1
free_disk_mb=4096
""",
            passenger_wsgi_adapter=True,
            shared_host_tick=True,
        )
        self.assertEqual(report.python_version, "Python 3.12.8")
        self.assertTrue(report.passenger)
        self.assertFalse(report.systemd)
        self.assertTrue(report.cron)
        self.assertEqual(report.free_disk_mb, 4096)
        self.assertTrue(report.passenger_wsgi_adapter)
        self.assertTrue(report.shared_host_tick)

    def test_parse_probe_rejects_incomplete_or_untrusted_output(self):
        with self.assertRaisesRegex(ValueError, "invalide"):
            transport.parse_probe("python=Python 3.12")
        with self.assertRaisesRegex(ValueError, "incomplet"):
            transport.parse_probe("CHECKUPAUTO_PROBE_V1\npython=Python 3.12\n")

    @mock.patch("deployment_transport.subprocess.run")
    def test_key_probe_executes_shell_over_ssh_without_shell_true(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="""CHECKUPAUTO_PROBE_V1
python=Python 3.12.8
node=
passenger=1
systemd=0
cron=1
symlink=1
writable_root=1
free_disk_mb=2048
""",
            stderr="",
        )
        result = transport.probe_target(
            self.target(),
            self.known_hosts,
            transport.SSHCredential(identity_file=str(self.key)),
            passenger_wsgi_adapter=False,
        )
        self.assertTrue(result.passenger)
        kwargs = run.call_args.kwargs
        self.assertFalse(kwargs["check"])
        self.assertTrue(kwargs["text"])
        self.assertNotIn("shell", kwargs)
        command = run.call_args.args[0]
        self.assertEqual(command[-2:], ["sh", "-s"])

    @mock.patch("deployment_transport._run_password_ssh")
    def test_password_probe_keeps_secret_out_of_public_connection(self, password_ssh):
        password_ssh.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="""CHECKUPAUTO_PROBE_V1
python=Python 3.12
node=
passenger=1
systemd=0
cron=1
symlink=1
writable_root=1
free_disk_mb=2048
""",
            stderr="",
        )
        target = self.target(authMode="password")
        result = transport.probe_target(
            target,
            self.known_hosts,
            transport.SSHCredential(password="secret-value"),
        )
        self.assertTrue(result.passenger)
        self.assertNotIn("secret-value", str(transport.sanitized_connection(target)))
        self.assertEqual(
            transport.sanitized_connection(target)["authMode"],
            "password",
        )


if __name__ == "__main__":
    unittest.main()
