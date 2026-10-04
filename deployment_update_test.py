import base64
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import deployment_center as center
import deployment_transport as transport
import deployment_update as updates


SHA_OLD = "1" * 40
SHA_NEW = "2" * 40
SHA_OTHER = "3" * 40


class DeploymentUpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.known_hosts = root / "known_hosts"
        self.known_hosts.write_text("ssh.example.net ssh-ed25519 AAAATEST\n", encoding="utf-8")
        self.key = root / "id_ed25519"
        self.key.write_text("private-placeholder\n", encoding="utf-8")
        self.key.chmod(0o600)
        self.target = center.validate_target({
            "provider": "planethoster-n0c",
            "host": "ssh.example.net",
            "username": "checkup",
            "domain": "www.checkupauto.fr",
        })

    def tearDown(self):
        self.tmp.cleanup()

    def encoded_state(self, *, installed=True, deployed=SHA_OLD, releases=None):
        rows = releases if releases is not None else [
            {"sha": deployed, "mtime": 200},
            {"sha": SHA_OTHER, "mtime": 100},
        ]
        payload = {
            "schemaVersion": 1,
            "installed": installed,
            "deployedSha": deployed if installed else "",
            "releases": rows,
        }
        encoded = base64.b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        ).decode()
        return "CHECKUPAUTO_UPDATE_STATE_B64=" + encoded

    def test_remote_script_is_private_root_scoped_and_read_only(self):
        script = updates.remote_state_script(self.target)
        self.assertIn(".checkupauto", script)
        self.assertIn(".checkupauto-release.json", script)
        self.assertIn("current.resolve", script)
        self.assertIn("command -v python3", script)
        self.assertIn("/opt/alt/python312/bin/python3", script)
        self.assertIn('"$checkupauto_python" -', script)
        self.assertNotIn("rmtree(", script)
        self.assertNotIn("unlink(", script)
        self.assertNotIn("write_text(", script)

    def test_parse_remote_state_validates_active_release(self):
        state = updates._parse_remote_state(self.encoded_state())
        self.assertTrue(state.installed)
        self.assertEqual(state.deployed_sha, SHA_OLD)
        self.assertEqual([row.sha for row in state.releases], [SHA_OLD, SHA_OTHER])

    def test_parse_remote_state_rejects_missing_active_release(self):
        with self.assertRaisesRegex(RuntimeError, "absente"):
            updates._parse_remote_state(
                self.encoded_state(
                    releases=[{"sha": SHA_OTHER, "mtime": 100}],
                )
            )

    @mock.patch("deployment_update._git_is_ancestor")
    def test_classify_update_available(self, ancestor):
        ancestor.side_effect = lambda _root, older, newer: older == SHA_OLD and newer == SHA_NEW
        remote = updates.RemoteDeploymentState(
            installed=True,
            deployed_sha=SHA_OLD,
            releases=(
                updates.RemoteRelease(SHA_OLD, 200),
                updates.RemoteRelease(SHA_OTHER, 100),
            ),
        )
        result = updates.classify_update(remote, SHA_NEW, self.tmp.name)
        self.assertEqual(result["state"], "update_available")
        self.assertTrue(result["updateAvailable"])
        self.assertEqual(result["rollbackCandidates"], [SHA_OTHER])

    @mock.patch("deployment_update._git_is_ancestor")
    def test_classify_remote_ahead(self, ancestor):
        ancestor.side_effect = lambda _root, older, newer: older == SHA_NEW and newer == SHA_OLD
        remote = updates.RemoteDeploymentState(
            installed=True,
            deployed_sha=SHA_OLD,
            releases=(updates.RemoteRelease(SHA_OLD, 200),),
        )
        result = updates.classify_update(remote, SHA_NEW, self.tmp.name)
        self.assertEqual(result["state"], "remote_ahead")
        self.assertFalse(result["updateAvailable"])

    def test_classify_not_installed(self):
        remote = updates.RemoteDeploymentState(
            installed=False,
            deployed_sha="",
            releases=(),
        )
        result = updates.classify_update(remote, SHA_NEW, self.tmp.name)
        self.assertEqual(result["state"], "not_installed")
        self.assertFalse(result["updateAvailable"])

    @mock.patch("deployment_update.subprocess.run")
    def test_read_remote_state_uses_strict_ssh_transport(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=self.encoded_state(),
            stderr="",
        )
        result = updates.read_remote_state(
            self.target,
            self.known_hosts,
            transport.SSHCredential(identity_file=str(self.key)),
        )
        self.assertEqual(result.deployed_sha, SHA_OLD)
        command = run.call_args.args[0]
        joined = " ".join(command)
        self.assertIn("StrictHostKeyChecking=yes", joined)
        self.assertEqual(command[-2:], ["sh", "-s"])

    @mock.patch.object(updates.github_source, "is_ancestor", return_value=True)
    @mock.patch.object(updates.github_source, "token_configured", return_value=True)
    def test_ancestry_uses_github_when_local_git_is_absent(self, configured, is_ancestor):
        packaged = Path(self.tmp.name) / "packaged"
        packaged.mkdir()
        self.assertTrue(
            updates._git_is_ancestor(packaged, SHA_OLD, SHA_NEW)
        )
        is_ancestor.assert_called_once_with(SHA_OLD, SHA_NEW)

    @mock.patch.object(updates.github_source, "token_configured", return_value=False)
    def test_ancestry_fails_closed_without_git_or_remote_source(self, configured):
        packaged = Path(self.tmp.name) / "packaged"
        packaged.mkdir()
        self.assertFalse(
            updates._git_is_ancestor(packaged, SHA_OLD, SHA_NEW)
        )

    def test_invalid_payload_is_rejected(self):
        encoded = base64.b64encode(b'{"schemaVersion":1,"installed":true,"deployedSha":"bad","releases":[]}').decode()
        with self.assertRaisesRegex(RuntimeError, "invalide"):
            updates._parse_remote_state("CHECKUPAUTO_UPDATE_STATE_B64=" + encoded)


if __name__ == "__main__":
    unittest.main()
