import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ios_release_preflight as preflight


CONFIG = {"seo": {"canonicalUrl": "https://www.checkupauto.fr/"}}


class IOSReleasePreflightTest(unittest.TestCase):
    def test_repository_project_is_release_consistent(self):
        with mock.patch.dict(os.environ, {
            "CYBERCHECK_IOS_APP_IDENTIFIER_PREFIX": "ABCDEFGHIJ",
            "CYBERCHECK_IOS_TESTFLIGHT_URL": "https://testflight.apple.com/join/AbC123xy",
            "CYBERCHECK_IOS_APP_URL": "",
        }, clear=False):
            result = preflight.status(CONFIG)
        self.assertTrue(result["projectReady"])
        self.assertTrue(result["associationReady"])
        self.assertTrue(result["publicationReady"])
        self.assertEqual(result["state"], "ready")
        self.assertEqual(result["bundleId"], "fr.checkupauto.reminder")

    def test_missing_apple_prefix_is_configuration_required(self):
        with mock.patch.dict(os.environ, {
            "CYBERCHECK_IOS_APP_IDENTIFIER_PREFIX": "",
            "CYBERCHECK_IOS_TESTFLIGHT_URL": "https://testflight.apple.com/join/AbC123xy",
            "CYBERCHECK_IOS_APP_URL": "",
        }, clear=False):
            result = preflight.status(CONFIG)
        self.assertTrue(result["projectReady"])
        self.assertFalse(result["associationReady"])
        self.assertEqual(result["state"], "configuration_required")

    def test_unpublished_build_is_blocked_external(self):
        with mock.patch.dict(os.environ, {
            "CYBERCHECK_IOS_APP_IDENTIFIER_PREFIX": "ABCDEFGHIJ",
            "CYBERCHECK_IOS_TESTFLIGHT_URL": "",
            "CYBERCHECK_IOS_APP_URL": "",
        }, clear=False):
            result = preflight.status(CONFIG)
        self.assertTrue(result["projectReady"])
        self.assertTrue(result["associationReady"])
        self.assertFalse(result["publicationReady"])
        self.assertEqual(result["state"], "blocked_external")

    def test_missing_release_runner_degrades_project_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing-runner.py"
            with mock.patch.object(preflight, "RELEASE_RUNNER", missing), mock.patch.dict(os.environ, {
                "CYBERCHECK_IOS_APP_IDENTIFIER_PREFIX": "ABCDEFGHIJ",
                "CYBERCHECK_IOS_TESTFLIGHT_URL": "https://testflight.apple.com/join/AbC123xy",
                "CYBERCHECK_IOS_APP_URL": "",
            }, clear=False):
                result = preflight.status(CONFIG)
        self.assertFalse(result["projectReady"])
        failures = {item["code"] for item in result["checks"] if not item["ok"]}
        self.assertIn("release_automation", failures)

    def test_invalid_release_manifest_is_degraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project.yml"
            project.write_text("configs:\n  Debug: debug\nPRODUCT_BUNDLE_IDENTIFIER: fr.invalid.app\n")
            with mock.patch.object(preflight, "PROJECT", project), mock.patch.dict(os.environ, {
                "CYBERCHECK_IOS_APP_IDENTIFIER_PREFIX": "ABCDEFGHIJ",
                "CYBERCHECK_IOS_TESTFLIGHT_URL": "https://testflight.apple.com/join/AbC123xy",
                "CYBERCHECK_IOS_APP_URL": "",
            }, clear=False):
                result = preflight.status(CONFIG)
        self.assertFalse(result["projectReady"])
        self.assertEqual(result["state"], "degraded")
        failures = {item["code"] for item in result["checks"] if not item["ok"]}
        self.assertIn("bundle_identifier", failures)
        self.assertIn("release_configuration", failures)
        self.assertIn("release_apns_environment", failures)


if __name__ == "__main__":
    unittest.main()
