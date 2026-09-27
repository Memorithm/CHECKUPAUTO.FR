import subprocess
import unittest
from pathlib import Path


class TestFlightInternalDistributionTest(unittest.TestCase):
    def test_node_self_test(self):
        script = Path("scripts/appstore-testflight.mjs")
        self.assertTrue(script.is_file())
        result = subprocess.run(
            ["node", str(script), "--self-test"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertIn("APPSTORE_TESTFLIGHT_SELF_TEST_OK", result.stdout)

    def test_script_uses_only_app_store_connect_https_api(self):
        text = Path("scripts/appstore-testflight.mjs").read_text()
        self.assertIn("https://api.appstoreconnect.apple.com", text)
        self.assertIn("/v1/betaGroups", text)
        self.assertIn("/v1/builds", text)
        self.assertNotIn("console.log(privateKey", text)
        self.assertNotIn("CHECKUPAUTO_ASC_KEY_P8", text)


if __name__ == "__main__":
    unittest.main()
