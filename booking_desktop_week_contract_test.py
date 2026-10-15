"""Desktop seven-day booking and native calendar picker regression contract."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent


@unittest.skipUnless(shutil.which("node"), "Node.js required for browser VM checks")
class BookingDesktopWeekContractTest(unittest.TestCase):
    def test_node_week_layout_and_date_picker_contract(self):
        result = subprocess.run(
            ["node", "--test", str(ROOT / "assets/booking-week-desktop.test.mjs")],
            cwd=ROOT, capture_output=True, text=True, timeout=35,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)

    def test_desktop_script_and_css_are_explicitly_versioned(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('/assets/booking-week-desktop.css?v=20261015-2', html)
        self.assertIn('/app.js?v=desktop-week-picker-20261015-2', html)
        self.assertIn('id="bookingDateTrigger"', html)
        self.assertIn('tabindex="-1" aria-label="Choisir la date de départ', html)


if __name__ == "__main__":
    unittest.main()
