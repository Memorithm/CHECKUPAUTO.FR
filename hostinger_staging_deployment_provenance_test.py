import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import public_surface_provenance as provenance


ROOT = Path(__file__).resolve().parent
DEPLOY = ROOT / "deploy" / "hostinger" / "deploy-staging.sh"
WRITER = ROOT / "deploy" / "hostinger" / "write-deployment-provenance.py"


def _load_writer():
    spec = importlib.util.spec_from_file_location("hostinger_provenance_writer", WRITER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class HostingerStagingDeploymentProvenanceTest(unittest.TestCase):
    def test_evidence_is_minimal_and_bound_to_exact_approved_sha(self):
        sha = "a" * 40
        evidence = provenance.deployment_artifact_evidence(sha)
        self.assertEqual(evidence, {
            "schemaVersion": 1,
            "surface": "checkupauto-cybercheck",
            "purpose": "public-deployment-provenance",
            "verified": True,
            "state": "verified",
            "gitSha": sha,
            "branch": "main",
            "clean": True,
            "source": "remoteops-approved-git-archive",
        })
        self.assertEqual(
            provenance.DEPLOYMENT_ARTIFACT_PATH,
            "/assets/cybercheck-deployment-provenance.bin",
        )

    def test_invalid_revision_never_claims_verified_or_clean(self):
        for value in ("", "main", "A" * 40, "a" * 39, "../" + "a" * 40):
            with self.subTest(value=value):
                evidence = provenance.deployment_artifact_evidence(value)
                self.assertFalse(evidence["verified"])
                self.assertEqual(evidence["state"], "invalid_git_sha")
                self.assertEqual(evidence["gitSha"], "")
                self.assertEqual(evidence["branch"], "")
                self.assertIsNone(evidence["clean"])
                self.assertEqual(evidence["source"], "")

    def test_writer_is_atomic_public_and_contains_no_runtime_path(self):
        writer = _load_writer()
        sha = "b" * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            writer.ROOT = root
            target = writer.write(root, sha)
            self.assertEqual(target, root / "assets" / "cybercheck-deployment-provenance.bin")
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(payload["gitSha"], sha)
            self.assertEqual(payload["source"], "remoteops-approved-git-archive")
            self.assertNotIn(str(root), target.read_text(encoding="utf-8"))
            self.assertEqual(target.stat().st_mode & 0o777, 0o644)
            self.assertLessEqual(target.stat().st_size, 4096)

    def test_writer_rejects_invalid_sha_and_wrong_root(self):
        writer = _load_writer()
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            root = Path(tmp).resolve()
            writer.ROOT = root
            with self.assertRaisesRegex(ValueError, "invalid approved sha"):
                writer.write(root, "not-a-sha")
            with self.assertRaisesRegex(ValueError, "release root mismatch"):
                writer.write(Path(other), "c" * 40)

    def test_deploy_verifies_public_artifact_after_trusted_https(self):
        script = DEPLOY.read_text(encoding="utf-8")
        sha_validation = script.index('[[ ! "$DEPLOY_SHA" =~ ^[0-9a-f]{40}$ ]]')
        generation = script.index("write-deployment-provenance.py")
        tls_gate = script.index('if [ "$verified" -ne 1 ]; then')
        artifact_fetch = script.index("cybercheck-deployment-provenance.bin")
        proof = script.index("STAGING_DEPLOYMENT_PROVENANCE_VERIFIED")
        success = script.index("CHECKUPAUTO_STAGING_DEPLOY_OK")
        self.assertLess(sha_validation, generation)
        self.assertLess(generation, tls_gate)
        self.assertLess(tls_gate, artifact_fetch)
        self.assertLess(artifact_fetch, proof)
        self.assertLess(proof, success)
        self.assertIn('"gitSha": expected', script)
        self.assertIn('"source": "remoteops-approved-git-archive"', script)
        self.assertNotIn("--insecure", script)
        self.assertNotIn("curl -k", script)


if __name__ == "__main__":
    unittest.main()
