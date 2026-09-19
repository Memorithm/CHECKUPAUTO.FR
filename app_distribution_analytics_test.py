from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import analytics_store as analytics


class AppDistributionAnalyticsTest(unittest.TestCase):
    def test_testflight_click_is_counted_without_being_mislabeled_as_app_store(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "analytics.sqlite3"
            with patch.object(analytics, "DB", db):
                analytics.init_db()
                analytics.record_event({
                    "event": "app_landing_view",
                    "path": "/app",
                    "device": "mobile",
                    "utmSource": "app:qr-centre",
                    "utmCampaign": "ios-reminder-app",
                })
                analytics.record_event({
                    "event": "app_testflight_click",
                    "path": "/app",
                    "device": "unknown",
                    "utmSource": "app:qr-centre",
                    "utmCampaign": "ios-reminder-app",
                    "service": "testflight",
                })
                result = analytics.summary(30)
        self.assertEqual(result["appLandingViews"], 1)
        self.assertEqual(result["appStoreClicks"], 0)
        self.assertEqual(result["appTestFlightClicks"], 1)
        self.assertEqual(result["appDistributionClicks"], 1)
        self.assertEqual(result["appDistributionClickRate"], 100.0)
        self.assertEqual(result["campaignFunnels"][0]["appTestFlightClicks"], 1)


if __name__ == "__main__":
    unittest.main()
