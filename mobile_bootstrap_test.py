import os
import unittest
from unittest.mock import patch

import mobile_bootstrap as mobile


class MobileBootstrapTest(unittest.TestCase):
    def config(self):
        return {
            "business": {"bookingUrl": "https://rdv.checkupauto.fr/"},
            "seo": {"canonicalUrl": "https://www.checkupauto.fr/"},
        }

    @patch.dict(os.environ, {"CYBERCHECK_REFERRAL_REWARD_CENTS": "500", "CYBERCHECK_MOBILE_PUSH_ENABLED": "0"}, clear=False)
    @patch.object(mobile.apns_gateway, "status", return_value={"configured": True})
    @patch.object(mobile.app_download, "status")
    def test_exposes_shared_public_mobile_policy(self, app_status, apns_status):
        app_status.return_value = {
            "landingUrl": "https://www.checkupauto.fr/app",
            "ios": {"available": False, "downloadPath": "/go/app"},
        }
        result = mobile.status(self.config())
        self.assertEqual(result["schemaVersion"], 1)
        self.assertEqual(result["reminders"]["leadDays"], [60, 30, 15, 7, 1])
        self.assertEqual(result["reminders"]["hour"], 9)
        self.assertEqual(result["reminders"]["timezone"], "Europe/Paris")
        self.assertEqual(result["booking"]["url"], "https://rdv.checkupauto.fr/")
        self.assertEqual(result["notifications"], {"remotePushActive": False, "localFallback": True})
        self.assertEqual(result["referral"], {"rewardCents": 500, "currency": "EUR"})
        self.assertFalse(result["app"]["available"])


    @patch.dict(os.environ, {"CYBERCHECK_MOBILE_PUSH_ENABLED": "1"}, clear=False)
    @patch.object(mobile.apns_gateway, "status", return_value={"configured": True})
    @patch.object(mobile.app_download, "status", return_value={
        "landingUrl": "https://www.checkupauto.fr/app",
        "ios": {"available": False, "downloadPath": "/go/app"},
    })
    def test_remote_push_activates_only_with_explicit_gate_and_credentials(self, app_status, apns_status):
        result = mobile.status(self.config())
        self.assertEqual(result["notifications"], {"remotePushActive": True, "localFallback": False})

    def test_rejects_non_https_booking_url(self):
        config = self.config()
        config["business"]["bookingUrl"] = "http://example.test/"
        with self.assertRaises(ValueError):
            mobile.status(config)


if __name__ == "__main__":
    unittest.main()
