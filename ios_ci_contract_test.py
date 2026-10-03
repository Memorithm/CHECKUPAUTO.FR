from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parent
WORKFLOW=ROOT/".github"/"workflows"/"ios-core-ci.yml"

class IOSCIContractTest(unittest.TestCase):
    def test_native_mac_runner_labels_are_required(self):
        text=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("runs-on: [self-hosted, macOS, ARM64, checkupauto, ios, ios-light]",text)
        self.assertIn("runs-on: [self-hosted, macOS, ARM64, checkupauto, ios, ios-heavy]",text)
        self.assertIn("needs: swift",text)

    def test_ci_no_longer_relays_through_ssh(self):
        text=WORKFLOW.read_text(encoding="utf-8")
        for legacy in ("CHECKUPAUTO_MAC_SSH_KEY","CHECKUPAUTO_MAC_HOST","ssh_args","remoteops_thor_ed25519","tar -czf - ios/CheckupAutoReminder"):
            self.assertNotIn(legacy,text)

    def test_apple_toolchain_runs_locally(self):
        text=WORKFLOW.read_text(encoding="utf-8")
        for command in ("sw_vers","xcodebuild -version","xcodegen --version","swift --version"):
            self.assertIn(command,text)

    def test_swift_tests_and_xcode_simulator_are_gated(self):
        text=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("swift test --parallel",text)
        self.assertIn("xcodegen generate",text)
        self.assertIn("xcodebuild test",text)
        self.assertIn("platform=iOS Simulator",text)
        self.assertIn("CODE_SIGNING_ALLOWED=NO",text)

    def test_live_preproduction_probe_uses_planethoster(self):
        text=WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("CHECKUPAUTO_API_BASE_URL='https://test.checkupauto.fr'",text)
        self.assertNotIn("sslip.io",text)

    def test_client_preproduction_does_not_open_admin_payment_lab(self):
        source=(ROOT/"ios/CheckupAutoReminder/Sources/MobileAPI.swift").read_text()
        self.assertIn('preproductionBaseURL = URL(string: "https://test.checkupauto.fr")!',source)
        self.assertIn('productionBaseURL = URL(string: "https://www.checkupauto.fr")!',source)
        self.assertNotIn("/payment/test",source)

    def test_documented_provider_callbacks_use_test_origin(self):
        text=(ROOT/"docs/customer-access-and-domain-migration.md").read_text()
        for provider in ("google","microsoft","apple"):
            self.assertIn(f"https://test.checkupauto.fr/auth/customer/{provider}/callback",text)

if __name__=="__main__":
    unittest.main()
