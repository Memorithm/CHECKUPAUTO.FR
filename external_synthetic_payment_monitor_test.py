from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
WORKFLOW = ROOT / ".github" / "workflows" / "external-synthetic-monitor.yml"


class ExternalSyntheticPaymentMonitorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_payline_callback_monitor_is_fail_closed(self):
        self.assertIn("Check payment callback surface fails closed", self.text)
        self.assertIn("cancel_code", self.text)
        self.assertIn("return_code", self.text)
        self.assertIn("notify_code", self.text)
        self.assertIn("PAYLINE_CALLBACK_FAIL_CLOSED_MONITOR_OK", self.text)
        self.assertGreaterEqual(self.text.count("400"), 2)
        self.assertIn("404", self.text)

    def test_payment_pages_remain_noindex(self):
        self.assertIn("Paiement non vérifiable", self.text)
        self.assertGreaterEqual(self.text.count("noindex"), 2)

    def test_monitor_uses_ephemeral_files(self):
        self.assertGreaterEqual(self.text.count("mktemp"), 2)
        self.assertNotIn("/tmp/payline-", self.text)


if __name__ == "__main__":
    unittest.main()
