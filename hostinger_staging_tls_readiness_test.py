from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
DEPLOY = ROOT / "deploy" / "hostinger" / "deploy-staging.sh"


class HostingerStagingTlsReadinessTest(unittest.TestCase):
    def setUp(self):
        self.script = DEPLOY.read_text(encoding="utf-8")

    def test_verified_https_is_retried_without_insecure_bypass(self):
        self.assertIn("for _ in $(seq 1 30); do", self.script)
        self.assertIn("curl -fsS", self.script)
        self.assertIn('"https://$HOST/"', self.script)
        self.assertIn("STAGING_TRUSTED_HTTPS_NOT_READY=$HOST", self.script)
        self.assertIn("exit 32", self.script)
        self.assertNotIn("--insecure", self.script)
        self.assertNotIn("curl -k", self.script)

    def test_tls_gate_runs_only_after_container_health_and_dns(self):
        health = self.script.index('if [ "$healthy" -ne 1 ]')
        dns = self.script.index("getent ahostsv4")
        tls_retry = self.script.index("for _ in $(seq 1 30); do")
        success = self.script.index("CHECKUPAUTO_STAGING_DEPLOY_OK")
        self.assertLess(health, dns)
        self.assertLess(dns, tls_retry)
        self.assertLess(tls_retry, success)

    def test_success_requires_http_200_and_expected_site_content(self):
        self.assertIn('if [ "$code" = 200 ] && grep -qi \'checkup\' "$body"; then', self.script)
        self.assertIn("verified=1", self.script)
        self.assertIn('if [ "$verified" -ne 1 ]; then', self.script)


if __name__ == "__main__":
    unittest.main()
