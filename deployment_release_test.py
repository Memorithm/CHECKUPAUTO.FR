import hashlib
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

import deployment_center as center
import deployment_release as release
import deployment_transport as transport


class DeploymentReleaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / "scripts").mkdir()
        (self.repo / "requirements.txt").write_text("\n", encoding="utf-8")
        (self.repo / "passenger_wsgi.py").write_text("application = object()\n", encoding="utf-8")
        (self.repo / "scripts" / "checkupauto-shared-tick.py").write_text("print('tick')\n", encoding="utf-8")
        (self.repo / "scripts" / "checkupauto-update-safety.py").write_text("print('safe')\n", encoding="utf-8")
        (self.repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(
            [
                "git", "-C", str(self.repo),
                "-c", "user.name=CheckupAuto Test",
                "-c", "user.email=test@example.invalid",
                "commit", "-q", "-m", "fixture",
            ],
            check=True,
        )
        self.sha = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            text=True,
        ).strip()

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

    def test_bundle_comes_from_exact_git_commit(self):
        bundle = release.build_release_bundle(self.repo, self.sha)
        self.assertEqual(bundle.sha, self.sha)
        self.assertEqual(bundle.sha256, hashlib.sha256(bundle.archive).hexdigest())
        self.assertEqual(bundle.file_count, 5)
        with tarfile.open(fileobj=io.BytesIO(bundle.archive), mode="r:") as archive:
            names = {member.name for member in archive.getmembers() if member.isfile()}
        self.assertEqual(
            names,
            {"app.py", "passenger_wsgi.py", "requirements.txt", "scripts/checkupauto-shared-tick.py", "scripts/checkupauto-update-safety.py"},
        )

    @mock.patch("deployment_release._validate_archive", return_value=1)
    @mock.patch("deployment_release.subprocess.run")
    def test_bundle_git_calls_pin_safe_directory(self, run, validate_archive):
        run.side_effect = [
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=self.sha + "\n",
                stderr="",
            ),
            subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=b"fixture-archive",
                stderr=b"",
            ),
        ]
        bundle = release.build_release_bundle(self.repo, self.sha)
        self.assertEqual(bundle.sha, self.sha)
        validate_archive.assert_called_once_with(b"fixture-archive")
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            command = call.args[0]
            self.assertIn("-c", command)
            self.assertIn("safe.directory=" + str(self.repo.resolve()), command)
            self.assertLess(command.index("-c"), command.index("-C"))

    def test_bundle_is_reproducible_for_same_commit(self):
        first = release.build_release_bundle(self.repo, self.sha)
        (self.repo / "untracked.txt").write_text("ignored\n", encoding="utf-8")
        second = release.build_release_bundle(self.repo, self.sha)
        self.assertEqual(first.archive, second.archive)
        self.assertEqual(first.sha256, second.sha256)

    def test_bundle_rejects_invalid_or_unknown_commit(self):
        with self.assertRaisesRegex(ValueError, "SHA"):
            release.build_release_bundle(self.repo, "main")
        with self.assertRaisesRegex(ValueError, "commit"):
            release.build_release_bundle(self.repo, "f" * 40)

    def test_bundle_rejects_git_symlink_entries(self):
        target = self.repo / "linked.py"
        target.symlink_to("app.py")
        subprocess.run(["git", "-C", str(self.repo), "add", "linked.py"], check=True)
        subprocess.run(
            [
                "git", "-C", str(self.repo),
                "-c", "user.name=CheckupAuto Test",
                "-c", "user.email=test@example.invalid",
                "commit", "-q", "-m", "symlink fixture",
            ],
            check=True,
        )
        sha = subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            text=True,
        ).strip()
        with self.assertRaisesRegex(ValueError, "type de fichier"):
            release.build_release_bundle(self.repo, sha)

    def test_remote_stage_is_private_atomic_and_digest_bound(self):
        bundle = release.build_release_bundle(self.repo, self.sha)
        script = release.remote_stage_script(self.target(), bundle)
        self.assertIn('private_root="$HOME/$root"', script)
        self.assertIn('releases="$private_root/releases"', script)
        self.assertIn(".incoming-$sha-$$", script)
        self.assertIn(bundle.sha256, script)
        self.assertIn("base64.b64decode", script)
        self.assertIn("digest mismatch", script)
        self.assertIn("unsupported archive member", script)
        self.assertIn("python3 -m venv", script)
        self.assertIn("compileall -q", script)
        self.assertIn("checkupauto-update-safety.py", script)
        self.assertIn("mv \"$candidate\" \"$release\"", script)
        self.assertNotIn("public_html/shared", script)
        self.assertNotIn("sudo ", script)

    def test_parse_stage_output_requires_exact_sha(self):
        bundle = release.build_release_bundle(self.repo, self.sha)
        result = release._parse_stage_output(
            f"noise\nCHECKUPAUTO_STAGE_OK={self.sha}\nCHECKUPAUTO_STAGE_PATH=/home/checkup/.checkupauto/releases/{self.sha}\n",
            bundle,
        )
        self.assertEqual(result.sha, self.sha)
        self.assertEqual(result.archive_sha256, bundle.sha256)
        with self.assertRaisesRegex(RuntimeError, "invalide"):
            release._parse_stage_output(
                "CHECKUPAUTO_STAGE_OK=" + ("0" * 40) + "\nCHECKUPAUTO_STAGE_PATH=/tmp/x\n",
                bundle,
            )

    def test_stage_refuses_unready_target_before_git_or_ssh(self):
        with self.assertRaisesRegex(RuntimeError, "non prête"):
            release.stage_release(
                self.target(),
                center.CapabilityReport(python_version="Python 3.12"),
                self.root / "missing-known-hosts",
                transport.SSHCredential(identity_file=str(self.root / "missing-key")),
                self.root / "missing-repo",
                self.sha,
            )

    @mock.patch("deployment_release.subprocess.run")
    @mock.patch("deployment_release.build_release_bundle")
    def test_stage_uses_strict_transport_and_redacted_failure(self, build, run):
        known_hosts = self.root / "known_hosts"
        known_hosts.write_text("ssh.example.net ssh-ed25519 AAAATEST\n", encoding="utf-8")
        key = self.root / "id_ed25519"
        key.write_text("placeholder\n", encoding="utf-8")
        key.chmod(0o600)
        bundle = release.ReleaseBundle(
            sha=self.sha,
            archive=b"fixture",
            sha256=hashlib.sha256(b"fixture").hexdigest(),
            file_count=1,
        )
        build.return_value = bundle
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=f"CHECKUPAUTO_STAGE_OK={self.sha}\nCHECKUPAUTO_STAGE_PATH=/home/checkup/.checkupauto/releases/{self.sha}\n",
            stderr="",
        )
        result = release.stage_release(
            self.target(),
            self.ready_capabilities(),
            known_hosts,
            transport.SSHCredential(identity_file=str(key)),
            self.repo,
            self.sha,
        )
        self.assertEqual(result.sha, self.sha)
        command = run.call_args.args[0]
        joined = " ".join(command)
        self.assertIn("StrictHostKeyChecking=yes", joined)
        self.assertIn("BatchMode=yes", joined)
        self.assertEqual(command[-2:], ["sh", "-s"])


if __name__ == "__main__":
    unittest.main()
