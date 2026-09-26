from __future__ import annotations

import unittest
from unittest import mock

import ios_release_runner as runner


class IOSReleaseRunnerTest(unittest.TestCase):
    def test_selects_newest_available_iphone_simulator(self):
        payload = {
            "devices": {
                "com.apple.CoreSimulator.SimRuntime.iOS-17-5": [
                    {"name": "iPhone 15", "udid": "OLD", "isAvailable": True},
                ],
                "com.apple.CoreSimulator.SimRuntime.iOS-18-2": [
                    {"name": "iPad Pro", "udid": "IPAD", "isAvailable": True},
                    {"name": "iPhone 16", "udid": "NEW", "isAvailable": True},
                    {"name": "iPhone 16 Pro", "udid": "OFF", "isAvailable": False},
                ],
            }
        }
        selected = runner.select_simulator(payload)
        self.assertEqual(selected["udid"], "NEW")
        self.assertEqual(selected["destination"], "platform=iOS Simulator,id=NEW")

    def test_no_iphone_simulator_is_rejected(self):
        with self.assertRaisesRegex(runner.ReleaseError, "no_available_iphone_simulator"):
            runner.select_simulator({"devices": {"runtime": [{"name": "iPad", "udid": "X"}]}})

    def test_release_settings_require_production_signing_contract(self):
        settings = {
            "PRODUCT_BUNDLE_IDENTIFIER": "fr.checkupauto.reminder",
            "APS_ENVIRONMENT": "production",
            "CODE_SIGN_STYLE": "Automatic",
            "CODE_SIGN_ENTITLEMENTS": "/tmp/CheckupAutoReminder.entitlements",
        }
        runner.validate_release_settings(settings)
        broken = dict(settings, APS_ENVIRONMENT="development")
        with self.assertRaisesRegex(runner.ReleaseError, "APS_ENVIRONMENT"):
            runner.validate_release_settings(broken)

    def test_signed_entitlements_require_apns_domain_and_bundle_suffix(self):
        runner.validate_signed_entitlements({
            "aps-environment": "production",
            "com.apple.developer.associated-domains": ["applinks:www.checkupauto.fr"],
            "application-identifier": "ABCDE12345.fr.checkupauto.reminder",
        })
        with self.assertRaisesRegex(runner.ReleaseError, "associated-domains"):
            runner.validate_signed_entitlements({
                "aps-environment": "production",
                "com.apple.developer.associated-domains": [],
                "application-identifier": "ABCDE12345.fr.checkupauto.reminder",
            })

    @mock.patch.object(runner, "_git")
    def test_release_guard_rejects_non_main_branch(self, git):
        git.side_effect = ["", "feature", "abc", "", "abc"]
        with self.assertRaisesRegex(runner.ReleaseError, "release_requires_main"):
            runner.release_guard(require_main=True)

    @mock.patch.object(runner, "_git")
    def test_release_guard_requires_exact_origin_main(self, git):
        git.side_effect = ["", "main", "abc", "", "def"]
        with self.assertRaisesRegex(runner.ReleaseError, "release_head_not_origin_main"):
            runner.release_guard(require_main=True)


    def test_app_store_connect_auth_requires_complete_key_triplet(self):
        with mock.patch.dict(runner.os.environ, {
            "CHECKUPAUTO_ASC_KEY_ID": "ABC1234567",
            "CHECKUPAUTO_ASC_ISSUER_ID": "",
            "CHECKUPAUTO_ASC_KEY_PATH": "",
        }, clear=False):
            with self.assertRaisesRegex(runner.ReleaseError, "issuer_id"):
                runner.app_store_connect_auth_args(required=True)

    def test_testflight_export_options_are_upload_only(self):
        import plistlib
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = runner._testflight_export_options("ABCDE12345", Path(tmp))
            payload = plistlib.loads(path.read_bytes())
        self.assertEqual(payload["method"], "app-store-connect")
        self.assertEqual(payload["destination"], "upload")
        self.assertEqual(payload["teamID"], "ABCDE12345")
        self.assertEqual(payload["signingStyle"], "automatic")

    def test_linux_refuses_real_release(self):
        with mock.patch.object(runner.sys, "platform", "linux"):
            with self.assertRaisesRegex(runner.ReleaseError, "macos_required"):
                runner.run_release(stage="preflight")


if __name__ == "__main__":
    unittest.main()
