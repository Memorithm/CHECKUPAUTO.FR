from pathlib import Path
import unittest


class AdminComplianceRetentionUIContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = Path("admin/compliance.js").read_text(encoding="utf-8")
        cls.retention = Path("retention_enforcement.py").read_text(encoding="utf-8")

    def test_duration_renderer_preserves_backend_units(self):
        self.assertIn("function retentionDurationLabel(row)", self.js)
        self.assertIn("row.activeHours", self.js)
        self.assertIn("String(row.activeHours)+' h'", self.js)
        self.assertIn("row.activeDays", self.js)
        self.assertIn("String(row.activeDays)+' j'", self.js)
        self.assertIn("row.mode==='event'", self.js)
        self.assertIn("return 'Événement'", self.js)

    def test_retention_table_uses_unit_aware_duration(self):
        self.assertIn("const duration=retentionDurationLabel(row);", self.js)
        self.assertIn("<td>'+esc(duration)+'</td>", self.js)
        self.assertNotIn("const days=row.activeDays===undefined", self.js)

    def test_booking_browser_token_ttl_has_one_backend_source(self):
        self.assertIn(
            '"activeHours": booking_bridge.BOOKING_BROWSER_TOKEN_TTL_HOURS',
            self.retention,
        )
        self.assertNotIn("booking_browser_tokens\": {\n        \"activeDays\"", self.retention)


if __name__ == "__main__":
    unittest.main()
