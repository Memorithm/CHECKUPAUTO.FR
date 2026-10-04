import unittest

import payment_mode


class PaymentModeTest(unittest.TestCase):
    def test_exact_mercureweb_origin_is_delegated(self):
        state=payment_mode.status({
            "business":{
                "bookingMode":"mercureweb-delegated",
                "bookingUrl":"https://rdv.checkupauto.fr/",
            }
        })
        self.assertTrue(state["valid"])
        self.assertTrue(state["delegated"])
        self.assertEqual(state["bookingUrl"],"https://rdv.checkupauto.fr/")

    def test_delegation_rejects_lookalike_or_insecure_origin(self):
        for url in (
            "http://rdv.checkupauto.fr/",
            "https://rdv.checkupauto.fr.evil.test/",
            "https://user@rdv.checkupauto.fr/",
            "https://rdv.checkupauto.fr/?x=1",
        ):
            with self.subTest(url=url):
                state=payment_mode.status({
                    "business":{"bookingMode":"mercureweb-delegated","bookingUrl":url}
                })
                self.assertFalse(state["valid"])
                self.assertFalse(state["delegated"])

    def test_payline_mode_is_not_delegated(self):
        state=payment_mode.status({"business":{"bookingMode":"payline","bookingUrl":""}})
        self.assertTrue(state["valid"])
        self.assertFalse(state["delegated"])


if __name__=="__main__":
    unittest.main()
