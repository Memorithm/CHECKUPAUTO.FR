import unittest
from unittest.mock import patch

import customer_loyalty as loyalty


class CustomerLoyaltyTest(unittest.TestCase):
    def test_issue_ios_claim_uses_existing_customer_wallet_and_returns_single_use_qr(self):
        with patch.object(loyalty.customer_accounts,"profile",return_value={
            "loyalty":{"referralCode":"OWNER-7K4P"}
        }), patch.object(loyalty.referral_wallet_claims,"issue",return_value={
            "claimToken":"rw_"+("A"*43),
            "claimType":"referral_wallet",
            "expiresAt":"2026-09-25T21:00:00+00:00",
            "singleUse":True,
            "rawTokenPersisted":False,
        }) as issue:
            result=loyalty.issue_ios_claim(
                "00000000-0000-4000-8000-000000000001",
                "https://stage.example",
            )
        issue.assert_called_once_with("OWNER-7K4P",1800)
        self.assertTrue(result["claimUrl"].startswith("https://stage.example/app/claim#token=rw_"))
        self.assertTrue(result["qrDataUrl"].startswith("data:image/svg+xml;base64,"))
        self.assertTrue(result["singleUse"])
        self.assertFalse(result["rawTokenPersisted"])

    def test_missing_wallet_and_non_https_origin_fail_closed(self):
        with patch.object(loyalty.customer_accounts,"profile",return_value={"loyalty":{}}):
            with self.assertRaisesRegex(loyalty.CustomerLoyaltyError,"^customer_loyalty_wallet_missing$"):
                loyalty.issue_ios_claim("id","https://stage.example")
        with self.assertRaisesRegex(loyalty.CustomerLoyaltyError,"^customer_loyalty_origin_invalid$"):
            loyalty.issue_ios_claim("id","http://stage.example")


if __name__=="__main__":
    unittest.main()
