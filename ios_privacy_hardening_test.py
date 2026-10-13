"""Contrats statiques du durcissement iOS (audit I-02, S-06).

Le code Swift n'est compilé que par la CI iOS ; ces tests vérifient, sans
Xcode, que les garde-fous ne disparaissent pas.
"""

import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent / "ios" / "CheckupAutoReminder"


def _read(relative: str) -> str:
    return (APP / relative).read_text(encoding="utf-8")


class IOSPrivacyHardeningTest(unittest.TestCase):
    def test_vehicle_plates_are_stored_in_the_keychain_with_migration(self):
        models = _read("Sources/Models.swift")
        store = models[models.index("enum VehicleDeadlineStore {"):models.index("enum LocalReminderPlan {")]
        self.assertIn("KeychainVehicleDeadlineStorage()", store)
        self.assertIn("kSecAttrAccessibleAfterFirstUnlock", models)
        self.assertIn("defaults.removeObject(forKey: storageKey)", store)
        tests = _read("Tests/ReminderPlanTests.swift")
        self.assertIn("testLegacyUserDefaultsDeadlinesMigrateToSecureStorage", tests)
        self.assertIn("testDeadlinesStayInDefaultsWhenSecureStorageFails", tests)

    def test_apple_sign_in_prefers_a_fresh_server_nonce(self):
        client = _read("Sources/AppleSignIn.swift")
        self.assertIn('"/api/mobile/auth/apple/nonce"', client)
        model = _read("Sources/AppModel.swift")
        self.assertIn("AppleSignInNonceClient.fetch()", model)
        self.assertIn("prefetchedAppleSignInNonce = nil", model)
        self.assertIn("< 480", model)
        # The premium introduction and account card use the shared Apple
        # authentication actions; nonce prefetch remains mandatory there.
        self.assertIn("prefetchAppleSignInNonce()", _read("Sources/CustomerAuthenticationOptions.swift"))


if __name__ == "__main__":
    unittest.main()
