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

    def test_dynamic_island_selection_excludes_se_and_16e(self):
        payload = {
            "devices": {
                "com.apple.CoreSimulator.SimRuntime.iOS-26-0": [
                    {"name": "iPhone SE (3rd generation)", "udid": "SE", "isAvailable": True},
                    {"name": "iPhone 16e", "udid": "16E", "isAvailable": True},
                    {"name": "iPhone 16 Pro", "udid": "ISLAND", "isAvailable": True},
                ],
            }
        }
        selected = runner.select_simulator(payload, require_dynamic_island=True)
        self.assertEqual(selected["udid"], "ISLAND")

    def test_dynamic_island_selection_fails_closed_without_capable_device(self):
        payload = {
            "devices": {
                "com.apple.CoreSimulator.SimRuntime.iOS-26-0": [
                    {"name": "iPhone SE (3rd generation)", "udid": "SE", "isAvailable": True},
                    {"name": "iPhone 16e", "udid": "16E", "isAvailable": True},
                ],
            }
        }
        with self.assertRaisesRegex(runner.ReleaseError, "no_available_dynamic_island_simulator"):
            runner.select_simulator(payload, require_dynamic_island=True)

    def test_dynamic_island_selection_accepts_two_digit_model_numbers(self):
        for name in ("iPhone 20", "iPhone 20 Pro"):
            with self.subTest(name=name):
                payload = {"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-30-0": [
                    {"name": name, "udid": "TWODIGIT", "isAvailable": True},
                ]}}
                selected = runner.select_simulator(payload, require_dynamic_island=True)
                self.assertEqual(selected["udid"], "TWODIGIT")

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


    def test_testflight_build_number_must_be_numeric(self):
        with mock.patch.object(runner.sys, "platform", "darwin"), \
             mock.patch.object(runner, "release_guard", return_value={"branch":"main","head":"a"*40,"originMain":"a"*40}), \
             mock.patch.object(runner, "_require_tool", return_value="/usr/bin/true"), \
             mock.patch.object(runner, "_stage_project"), \
             mock.patch.object(runner, "_show_release_settings", return_value={}), \
             mock.patch.dict(runner.os.environ, {"CHECKUPAUTO_BUILD_NUMBER":"bad-build"}, clear=False):
            with self.assertRaisesRegex(runner.ReleaseError, "build_number_invalid"):
                runner.run_release(stage="archive")

    def test_linux_refuses_real_release(self):
        with mock.patch.object(runner.sys, "platform", "linux"):
            with self.assertRaisesRegex(runner.ReleaseError, "macos_required"):
                runner.run_release(stage="preflight")


if __name__ == "__main__":
    unittest.main()
