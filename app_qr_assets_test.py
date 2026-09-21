import unittest

import app_qr_assets as qr_assets


class AppQRAssetsTest(unittest.TestCase):
    def test_distribution_payloads_stay_on_checkupauto(self):
        self.assertEqual(
            qr_assets.payload("qr-site"),
            "https://www.checkupauto.fr/app?src=qr-site",
        )
        self.assertEqual(
            qr_assets.payload("qr-centre"),
            "https://www.checkupauto.fr/app?src=qr-centre",
        )
        for target in qr_assets.QR_TARGETS.values():
            self.assertTrue(target.startswith("https://www.checkupauto.fr/app?src="))
            self.assertNotIn("apple.com", target)

    def test_committed_qr_assets_are_reproducible_from_canonical_payloads(self):
        state = qr_assets.check_assets()
        self.assertEqual(state, {"qr-site": True, "qr-centre": True})

    def test_unknown_distribution_qr_is_rejected(self):
        with self.assertRaises(ValueError):
            qr_assets.payload("unknown")
        with self.assertRaises(ValueError):
            qr_assets.asset_path("unknown")


if __name__ == "__main__":
    unittest.main()
