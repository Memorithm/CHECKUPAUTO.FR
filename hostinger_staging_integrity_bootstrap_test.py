from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
DEPLOY = ROOT / "deploy" / "hostinger" / "deploy-staging.sh"


class HostingerStagingIntegrityBootstrapTest(unittest.TestCase):
    def setUp(self):
        self.script = DEPLOY.read_text(encoding="utf-8")

    def test_integrity_baseline_is_provisioned_before_runtime_start(self):
        build = self.script.index("docker compose build --pull web")
        baseline = self.script.index("security_integrity.create_baseline(True)")
        start = self.script.index("docker compose up -d --remove-orphans")
        self.assertLess(build, baseline)
        self.assertLess(baseline, start)

    def test_baseline_provisioning_is_explicitly_root_controlled_then_runtime_owned(self):
        self.assertIn("docker compose run --rm --no-deps --user 0:0 web", self.script)
        self.assertIn('test -s "$STATE/integrity/integrity-baseline.json"', self.script)
        self.assertIn('chown 10001:10001 "$STATE/integrity/integrity-baseline.json"', self.script)
        self.assertIn('chmod 0640 "$STATE/integrity/integrity-baseline.json"', self.script)

    def test_no_secret_material_is_embedded_in_bootstrap_command(self):
        baseline_line = next(
            line for line in self.script.splitlines()
            if "security_integrity.create_baseline(True)" in line
        )
        self.assertNotIn("password", baseline_line.lower())
        self.assertNotIn("token", baseline_line.lower())
        self.assertNotIn("secret", baseline_line.lower())


if __name__ == "__main__":
    unittest.main()
