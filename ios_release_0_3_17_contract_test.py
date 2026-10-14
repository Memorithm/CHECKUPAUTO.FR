"""Qualify TestFlight 0.3.17 build20 after Apple VALID 0.3.16 build19."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IOS = ROOT / "ios/CheckupAutoReminder"
SRC = IOS / "Sources"


class IOSRelease017Contract(unittest.TestCase):
    def test_build20_version_and_release_notes(self):
        spec = (IOS / "project.yml").read_text(encoding="utf-8")
        import re
        build = re.search(r"CURRENT_PROJECT_VERSION: (\d+)", spec)
        version = re.search(r"MARKETING_VERSION: (\d+)\.(\d+)\.(\d+)", spec)
        self.assertIsNotNone(build)
        self.assertIsNotNone(version)
        self.assertGreaterEqual(int(build.group(1)), 20)
        self.assertGreaterEqual(tuple(map(int, version.groups())), (0, 3, 17))
        self.assertIn("CHECKUPAUTO_ENVIRONMENT: production", spec)
        notes = (IOS / "RELEASE_NOTES_0.3.17.md").read_text(encoding="utf-8")
        for expected in ("0.3.17 (20)", "Rendez-vous", "JJ/MM/AAAA",
                         "Parrainage", "test.checkupauto.fr", "RemoteOps"):
            self.assertIn(expected, notes)

    def test_website_matches_embedded_account_and_date_storage(self):
        website = (ROOT / "customer_http.py").read_text(encoding="utf-8")
        account = (ROOT / "customer_accounts.py").read_text(encoding="utf-8")
        webview = (SRC / "NativeCustomerAccountView.swift").read_text(encoding="utf-8")
        editor = (SRC / "AddVehicleView.swift").read_text(encoding="utf-8")
        mobile = (SRC / "CustomerAccountAPI.swift").read_text(encoding="utf-8")
        model = (SRC / "AppModel.swift").read_text(encoding="utf-8")
        home = (SRC / "ContentView.swift").read_text(encoding="utf-8")
        self.assertIn('AuthenticatedCustomerDashboardWebView(', webview)
        self.assertIn('<h2>Rendez-vous</h2>', website)
        self.assertNotIn('Consulter mes rendez-vous Mercure', website)
        self.assertNotIn('id="ct-report"', website)
        self.assertIn('vehicleNextControlDate', website)
        self.assertIn('next_control_date=payload["nextControlDate"]', website)
        self.assertIn('def _next_control_date(value:', account)
        self.assertIn('controlDateConfirmed &&', editor)
        self.assertIn('nextControlDate: nextControlDate', editor)
        self.assertIn('let nextControlDate: String', mobile)
        self.assertIn('accountDueDates', model)
        self.assertIn('formatter.dateFormat = withTime ? "dd/MM/yyyy', home)


if __name__ == "__main__":
    unittest.main()
