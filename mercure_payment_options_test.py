import unittest
from unittest.mock import Mock, patch

import mercure_public_client as mercure


def _session(payload, status=200):
    response = Mock(status_code=status)
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    browser = Mock()
    browser.post.return_value = response
    return browser


class MercurePaymentOptionsTest(unittest.TestCase):
    def setUp(self):
        mercure._PAYMENT_OPTIONS_CACHE.clear()

    def tearDown(self):
        mercure._PAYMENT_OPTIONS_CACHE.clear()
        mercure._breaker_success()

    def test_reads_mercure_web_and_centre_flags_for_the_service(self):
        browser = _session({"paiementWeb": True, "paiementCentre": False,
                            "energies": [{"id": 1, "libelle": "Diesel"}, {"id": "2", "libelle": "Essence"}, "x"]})
        with patch.object(mercure, "_provider_session", return_value=browser):
            result = mercure.payment_options("technical")
        url, = browser.post.call_args.args
        self.assertEqual(url, mercure.BASE + "/get_energie_prestation")
        self.assertEqual(browser.post.call_args.kwargs["data"]["prestation"], "1763")
        self.assertEqual((result["service"], result["online"], result["centre"]),
                         ("technical", True, False))
        self.assertEqual(result["energyIds"], ["1", "2"])
        browser.close.assert_called_once_with()

    def test_result_is_cached(self):
        browser = _session({"paiementWeb": False, "paiementCentre": True})
        with patch.object(mercure, "_provider_session", return_value=browser) as opened:
            mercure.payment_options("fitted")
            mercure.payment_options("fitted")
        self.assertEqual(opened.call_count, 1)

    def test_ambiguous_provider_answer_is_refused(self):
        browser = _session({"paiementWeb": "1", "paiementCentre": True})
        with patch.object(mercure, "_provider_session", return_value=browser):
            with self.assertRaises(RuntimeError):
                mercure.payment_options("technical")
        self.assertEqual(mercure._PAYMENT_OPTIONS_CACHE, {})

    def test_unknown_service_never_reaches_mercure(self):
        with patch.object(mercure, "_provider_session") as opened:
            with self.assertRaises(ValueError):
                mercure.payment_options("unknown")
        opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
