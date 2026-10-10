from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parent
class GoogleMobileHandoffContractTest(unittest.TestCase):
 def test_server_and_ios_use_single_use_ticket(self):
  http=(ROOT/"customer_http.py").read_text()
  ios=(ROOT/"ios/CheckupAutoReminder/Sources/GoogleCustomerSignIn.swift").read_text()
  self.assertIn('mobile_auth_ticket.issue(result["account"]["accountId"],code_challenge=result.get("mobileChallenge",""))',http)
  self.assertIn('"code_verifier": verifier',ios)
  self.assertIn('"checkupauto://auth/google?ticket="',http)
  self.assertIn('MobileAPI.endpoint("/api/mobile/auth/exchange")',ios)
  self.assertNotIn("sessionToken=",http)
if __name__=="__main__": unittest.main()
