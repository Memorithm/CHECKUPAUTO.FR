from __future__ import annotations

import plistlib
import unittest
from pathlib import Path


MANIFEST = Path("ios/CheckupAutoReminder/Sources/PrivacyInfo.xcprivacy")


class IOSPrivacyManifestTest(unittest.TestCase):
    def _manifest(self) -> dict:
        self.assertTrue(MANIFEST.is_file(), "PrivacyInfo.xcprivacy is required")
        return plistlib.loads(MANIFEST.read_bytes())

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

    def test_no_required_reason_api_is_declared_without_current_code_evidence(self):
        manifest = self._manifest()
        self.assertEqual(manifest.get("NSPrivacyAccessedAPITypes"), [])

    def test_current_swift_sources_do_not_use_known_required_reason_api_wrappers(self):
        source_root = Path("ios/CheckupAutoReminder/Sources")
        swift = "\n".join(
            path.read_text(encoding="utf-8") for path in sorted(source_root.glob("*.swift"))
        )
        for token in (
            "UserDefaults",
            "systemUptime",
            "volumeAvailableCapacity",
            "volumeAvailableCapacityForImportantUsage",
            "volumeAvailableCapacityForOpportunisticUsage",
        ):
            self.assertNotIn(token, swift)


if __name__ == "__main__":
    unittest.main()
