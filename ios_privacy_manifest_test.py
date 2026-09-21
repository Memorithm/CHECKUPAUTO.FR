from __future__ import annotations

import plistlib
import unittest
from pathlib import Path


MANIFEST = Path("ios/CheckupAutoReminder/Sources/PrivacyInfo.xcprivacy")


class IOSPrivacyManifestTest(unittest.TestCase):
    def _manifest(self) -> dict:
        self.assertTrue(MANIFEST.is_file(), "PrivacyInfo.xcprivacy is required")
        return plistlib.loads(MANIFEST.read_bytes())

    def _swift_source(self) -> str:
        source_root = Path("ios/CheckupAutoReminder/Sources")
        return "\n".join(
            path.read_text(encoding="utf-8") for path in sorted(source_root.glob("*.swift"))
        )

    def test_tracking_is_explicitly_disabled(self):
        manifest = self._manifest()
        self.assertIs(manifest.get("NSPrivacyTracking"), False)
        self.assertEqual(manifest.get("NSPrivacyTrackingDomains"), [])

    def test_collection_matches_current_mobile_data_boundary(self):
        manifest = self._manifest()
        rows = manifest.get("NSPrivacyCollectedDataTypes")
        self.assertIsInstance(rows, list)
        by_type = {row["NSPrivacyCollectedDataType"]: row for row in rows}
        self.assertEqual(
            set(by_type),
            {
                "NSPrivacyCollectedDataTypeDeviceID",
                "NSPrivacyCollectedDataTypeOtherDataTypes",
            },
        )
        for row in by_type.values():
            self.assertIs(row.get("NSPrivacyCollectedDataTypeLinked"), True)
            self.assertIs(row.get("NSPrivacyCollectedDataTypeTracking"), False)
            self.assertEqual(
                row.get("NSPrivacyCollectedDataTypePurposes"),
                ["NSPrivacyCollectedDataTypePurposeAppFunctionality"],
            )

    def test_userdefaults_required_reason_is_declared(self):
        manifest = self._manifest()
        self.assertEqual(
            manifest.get("NSPrivacyAccessedAPITypes"),
            [
                {
                    "NSPrivacyAccessedAPIType": "NSPrivacyAccessedAPICategoryUserDefaults",
                    "NSPrivacyAccessedAPITypeReasons": ["CA92.1"],
                }
            ],
        )
        swift = self._swift_source()
        self.assertIn("UserDefaults", swift)
        self.assertNotIn("UserDefaults(suiteName:", swift)

    def test_no_other_known_required_reason_api_wrapper_is_present(self):
        swift = self._swift_source()
        for token in (
            "systemUptime",
            "volumeAvailableCapacity",
            "volumeAvailableCapacityForImportantUsage",
            "volumeAvailableCapacityForOpportunisticUsage",
        ):
            self.assertNotIn(token, swift)


if __name__ == "__main__":
    unittest.main()
