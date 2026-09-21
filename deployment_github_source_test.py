from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

import deployment_github_source as github


SHA = "a" * 40
NEW_SHA = "b" * 40


class FakeResponse:
    def __init__(self, status=200, *, payload=None, content=b"", headers=None):
        self.status_code = status
        self._payload = payload
        self.content = content
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected request")
        return self.responses.pop(0)


class DeploymentGitHubSourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.private = self.root / "private"
        self.private.mkdir()
        self.token = self.private / "github-update-token"
        self.token.write_text("github_pat_" + "A" * 40 + "\n", encoding="ascii")
        self.token.chmod(0o600)
        self.env = mock.patch.dict(
            os.environ,
            {
                "CYBERCHECK_PRIVATE_DIR": str(self.private),
                "CYBERCHECK_UPDATE_GITHUB_REPOSITORY": "Memorithm/CHECKUPAUTO.FR",
                "CYBERCHECK_UPDATE_GITHUB_BRANCH": "main",
                "CYBERCHECK_UPDATE_GITHUB_TOKEN_FILE": str(self.token),
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def tarball(self, *, symlink=False):
        root = f"Memorithm-CHECKUPAUTO.FR-{SHA[:7]}"
        out = BytesIO()
        with tarfile.open(fileobj=out, mode="w:gz") as archive:
            for name, data, mode in (
                ("requirements.txt", b"requests==2.34.2\n", 0o644),
                ("passenger_wsgi.py", b"application = object()\n", 0o644),
                ("scripts/checkupauto-shared-tick.py", b"print('tick')\n", 0o755),
                ("scripts/checkupauto-update-safety.py", b"print('safe')\n", 0o755),
                ("app.py", b"VALUE = 1\n", 0o644),
            ):
                info = tarfile.TarInfo(f"{root}/{name}")
                info.size = len(data)
                info.mode = mode
                archive.addfile(info, BytesIO(data))
            if symlink:
                info = tarfile.TarInfo(f"{root}/linked.py")
                info.type = tarfile.SYMTYPE
                info.linkname = "app.py"
                archive.addfile(info)
        return out.getvalue()

    def test_public_status_never_exposes_token_or_path(self):
        status = github.public_status()
        self.assertEqual(status["provider"], "github")
        self.assertEqual(status["repository"], "Memorithm/CHECKUPAUTO.FR")
        self.assertEqual(status["branch"], "main")
        self.assertTrue(status["tokenConfigured"])
        text = str(status)
        self.assertNotIn("github_pat_", text)
        self.assertNotIn(str(self.token), text)

    def test_token_requires_private_permissions(self):
        self.token.chmod(0o644)
        self.assertFalse(github.token_configured())
        with self.assertRaisesRegex(RuntimeError, "permissions"):
            github.latest_sha(session=FakeSession([]))

    def test_save_token_is_private_and_atomic(self):
        target = self.private / "new-token"
        value = "github_pat_" + "B" * 40
        result = github.save_token(value, target)
        self.assertTrue(result["configured"])
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.read_text().strip(), value)

    def test_latest_sha_uses_exact_repository_and_no_redirects(self):
        session = FakeSession([
            FakeResponse(payload={"sha": NEW_SHA}),
        ])
        self.assertEqual(github.latest_sha(session=session), NEW_SHA)
        url, kwargs = session.calls[0]
        self.assertEqual(
            url,
            "https://api.github.com/repos/Memorithm/CHECKUPAUTO.FR/commits/main",
        )
        self.assertFalse(kwargs["allow_redirects"])
        self.assertTrue(kwargs["headers"]["Authorization"].startswith("Bearer "))

    def test_is_ancestor_uses_github_compare(self):
        session = FakeSession([
            FakeResponse(payload={"status": "ahead"}),
        ])
        self.assertTrue(github.is_ancestor(SHA, NEW_SHA, session=session))
        self.assertIn(f"/compare/{SHA}...{NEW_SHA}", session.calls[0][0])

    def test_build_bundle_strips_github_root_and_drops_auth_on_codeload(self):
        location = (
            "https://codeload.github.com/Memorithm/CHECKUPAUTO.FR/"
            f"legacy.tar.gz/{SHA}"
        )
        session = FakeSession([
            FakeResponse(payload={"sha": SHA}),
            FakeResponse(status=302, headers={"Location": location}),
            FakeResponse(status=200, content=self.tarball()),
        ])
        bundle = github.build_bundle(SHA, session=session)
        self.assertEqual(bundle.sha, SHA)
        self.assertEqual(bundle.file_count, 5)
        self.assertEqual(len(bundle.sha256), 64)

        with tarfile.open(fileobj=BytesIO(bundle.archive), mode="r:") as archive:
            names = {
                member.name
                for member in archive.getmembers()
                if member.isfile()
            }
        self.assertEqual(
            names,
            {
                "requirements.txt",
                "passenger_wsgi.py",
                "scripts/checkupauto-shared-tick.py",
                "scripts/checkupauto-update-safety.py",
                "app.py",
            },
        )
        codeload_headers = session.calls[2][1]["headers"]
        self.assertNotIn("Authorization", codeload_headers)

    def test_archive_redirect_is_restricted_to_codeload(self):
        session = FakeSession([
            FakeResponse(payload={"sha": SHA}),
            FakeResponse(
                status=302,
                headers={"Location": "https://evil.example/archive.tar.gz"},
            ),
        ])
        with self.assertRaisesRegex(RuntimeError, "non autorisée"):
            github.build_bundle(SHA, session=session)

    def test_symlink_in_github_archive_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "membre interdit"):
            github._normalize_tarball(self.tarball(symlink=True))

    def test_archive_requires_single_root_directory(self):
        out = BytesIO()
        with tarfile.open(fileobj=out, mode="w:gz") as archive:
            for root in ("one", "two"):
                data = b"x"
                info = tarfile.TarInfo(f"{root}/file.txt")
                info.size = 1
                archive.addfile(info, BytesIO(data))
        with self.assertRaisesRegex(RuntimeError, "racine unique"):
            github._normalize_tarball(out.getvalue())


if __name__ == "__main__":
    unittest.main()
