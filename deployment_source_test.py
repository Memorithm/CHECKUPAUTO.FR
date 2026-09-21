from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import deployment_source as source


SHA = "a" * 40


class DeploymentSourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_git_checkout_is_build_capable(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "file.txt").write_text("x\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(
            [
                "git", "-C", str(self.root),
                "-c", "user.name=CheckupAuto Test",
                "-c", "user.email=test@example.invalid",
                "commit", "-q", "-m", "fixture",
            ],
            check=True,
        )
        expected = subprocess.check_output(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            text=True,
        ).strip()
        state = source.detect_source(self.root)
        self.assertEqual(state.mode, "git_checkout")
        self.assertEqual(state.sha, expected)
        self.assertTrue(state.build_capable)

    def test_packaged_release_reads_verified_marker_but_is_not_build_capable(self):
        (self.root / ".checkupauto-release.json").write_text(
            json.dumps({
                "schemaVersion": 1,
                "sha": SHA,
                "archiveSha256": "b" * 64,
                "verified": True,
            }) + "\n",
            encoding="utf-8",
        )
        with mock.patch.object(source.github_source, "token_configured", return_value=False):
            state = source.detect_source(self.root)
        self.assertEqual(state.mode, "packaged_release")
        self.assertEqual(state.sha, SHA)
        self.assertFalse(state.build_capable)

    def test_packaged_release_with_private_github_source_is_build_capable(self):
        (self.root / ".checkupauto-release.json").write_text(
            json.dumps({
                "schemaVersion": 1,
                "sha": SHA,
                "archiveSha256": "b" * 64,
                "verified": True,
            }) + "\n",
            encoding="utf-8",
        )
        with mock.patch.object(source.github_source, "token_configured", return_value=True):
            state = source.detect_source(self.root)
        self.assertEqual(state.mode, "github_remote")
        self.assertEqual(state.sha, SHA)
        self.assertTrue(state.build_capable)

    def test_desired_sha_uses_remote_branch_for_github_source(self):
        (self.root / ".checkupauto-release.json").write_text(
            json.dumps({
                "schemaVersion": 1,
                "sha": SHA,
                "archiveSha256": "b" * 64,
                "verified": True,
            }) + "\n",
            encoding="utf-8",
        )
        with mock.patch.object(source.github_source, "token_configured", return_value=True), \
             mock.patch.object(source.github_source, "latest_sha", return_value="b" * 40):
            self.assertEqual(source.desired_sha(self.root), "b" * 40)

    def test_invalid_marker_fails_closed(self):
        (self.root / ".checkupauto-release.json").write_text(
            json.dumps({
                "sha": SHA,
                "archiveSha256": "bad",
                "verified": True,
            }),
            encoding="utf-8",
        )
        state = source.detect_source(self.root)
        self.assertEqual(state.mode, "unavailable")
        self.assertEqual(state.sha, "")
        self.assertFalse(state.build_capable)

    def test_symlink_marker_is_refused(self):
        real = self.root / "real-marker.json"
        real.write_text(
            json.dumps({
                "sha": SHA,
                "archiveSha256": "c" * 64,
                "verified": True,
            }),
            encoding="utf-8",
        )
        (self.root / ".checkupauto-release.json").symlink_to(real)
        state = source.detect_source(self.root)
        self.assertEqual(state.mode, "unavailable")
        self.assertFalse(state.build_capable)


if __name__ == "__main__":
    unittest.main()
