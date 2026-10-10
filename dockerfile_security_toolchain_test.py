from pathlib import Path
import unittest

DOCKERFILE=Path(__file__).resolve().parent/"Dockerfile"

class DockerfileSecurityToolchainTest(unittest.TestCase):
    def test_runtime_pip_is_pinned_to_current_security_baseline(self):
        text=DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("pip==26.2.1",text)
        self.assertNotIn("pip==25.0.1",text)

    def test_pip_upgrade_happens_before_runtime_requirements(self):
        text=DOCKERFILE.read_text(encoding="utf-8")
        upgrade=text.index("pip==26.2.1")
        requirements=text.index("--require-hashes -r requirements.lock")
        self.assertLess(upgrade,requirements)

if __name__=="__main__":
    unittest.main()
