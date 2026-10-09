import unittest
from unittest.mock import Mock, patch

import mercure_vl_payment_policy_source as source


class PaymentPolicySourceTests(unittest.TestCase):
    def test_online_policy_requires_a_future_verified_receipt(self):
        policy = source.qualify(service="technical", response={"paiementCentre": True, "paiementWeb": True})
        self.assertTrue(policy["providerVerified"])
        self.assertTrue(policy["paymentRequired"])
        self.assertNotIn("paid", policy)

    def test_centre_payment_is_explicitly_unpaid(self):
        policy=source.qualify(service="technical", response={"paiementCentre": True, "paiementWeb": False})
        self.assertEqual(policy["paymentMode"], "centre")
        self.assertFalse(policy["paymentRequired"])

    def test_ambiguous_flags_are_not_provider_authority(self):
        for value in ({}, {"paiementCentre": True}, {"paiementCentre": True, "paiementWeb": 1},
                      {"paiementCentre": True, "paiementWeb": "true"}, []):
            with self.subTest(value=value), self.assertRaises(source.MercurePaymentPolicyError):
                source.qualify(service="technical", response=value)

    def test_service_is_selected_server_side_and_session_is_closed(self):
        session = Mock()
        response = session.post.return_value
        response.status_code = 200
        response.json.return_value = {"paiementCentre": True, "paiementWeb": True}
        with patch.object(source.public, "_provider_session", return_value=session):
            policy = source.load(service="fitted")
        self.assertEqual(policy["service"], "fitted")
        args = session.post.call_args
        self.assertEqual(args.args[0], source.public.BASE + "/get_energie_prestation")
        self.assertEqual(args.kwargs["data"]["prestation"], "1771")
        self.assertFalse(args.kwargs["allow_redirects"])
        session.close.assert_called_once()

    def test_redirects_or_provider_failures_never_yield_a_policy(self):
        for status in (302, 403, 500):
            session = Mock()
            session.post.return_value.status_code = status
            with patch.object(source.public, "_provider_session", return_value=session):
                with self.assertRaises(source.MercurePaymentPolicyError):
                    source.load(service="technical")
            session.close.assert_called_once()
