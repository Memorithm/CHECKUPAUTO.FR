from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parent
class KeychainSessionContractTest(unittest.TestCase):
 def test_customer_session_is_device_only_keychain(self):
  text=(ROOT/"ios/CheckupAutoReminder/Sources/CustomerSessionKeychain.swift").read_text()
  self.assertIn("kSecClassGenericPassword",text)
  self.assertIn("kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly",text)
  self.assertNotIn("UserDefaults",text)
 def test_both_providers_end_in_keychain(self):
  apple=(ROOT/"ios/CheckupAutoReminder/Sources/AppleSignIn.swift").read_text()
  google=(ROOT/"ios/CheckupAutoReminder/Sources/GoogleCustomerSignIn.swift").read_text()
  self.assertIn("CustomerSessionKeychain.save",apple)
  self.assertIn("CustomerSessionKeychain.save",google)
if __name__=="__main__": unittest.main()
