import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import mercure_admin_client
import mercure_hosted_checkout as checkout

ENV = {checkout.ENABLE_ENV: "true"}
KEY = "cle-reservation-0123456789abcdef"
PAYLOAD = {"service": "technical", "date": "2026-10-20", "time": "09:00",
           "vehicleId": "veh-1", "requestKey": KEY}
ACCOUNT = {"accountId": "acc-1", "email": "client@example.test",
           "vehicles": [{"vehicleId": "veh-1"}]}
APPOINTMENT = {"nom": "Dupont", "prenom": "Alex", "email": "client@example.test",
               "telephone": "+33 6 12 34 56 78", "marque": "132", "modele": "1",
               "energie": "2", "immatriculation": "AB-123-CD", "date": "2026-10-20T09:00"}
PREFLIGHT = {"ok": True, "service": "technical", "date": "2026-10-20", "time": "09:00",
             "vehicleId": "veh-1", "priceCents": 8000}


def _session(text="https://webpayment.payline.com/v2/?token=abc", status=200):
    session = Mock()
    session.post.return_value = Mock(status_code=status, text=text)
    return session


class HostedCheckoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"CYBERCHECK_DATA_DIR": self.tmp.name})
        self.env.start()
        self.patches = [
            patch.object(checkout.customer_booking_api, "preflight", return_value=dict(PREFLIGHT)),
            patch.object(checkout.mercure_customer_booking_assembly, "assemble",
                         return_value={"appointment": dict(APPOINTMENT)}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.env.stop()
        self.tmp.cleanup()

    def _start(self, session, online=True, environ=ENV):
        return checkout.start(dict(PAYLOAD), account=ACCOUNT, environ=environ,
                              session_factory=lambda: session,
                              payment_options=lambda service: {"online": online})

    def test_disabled_by_default_and_never_calls_mercure(self):
        session = _session()
        with self.assertRaises(checkout.HostedCheckoutError) as caught:
            self._start(session, environ={})
        self.assertEqual(str(caught.exception), "mercure_hosted_payment_disabled")
        session.post.assert_not_called()

    def test_online_payment_selected_and_redirect_returned(self):
        session = _session()
        result = self._start(session)
        url, = session.post.call_args.args
        form = session.post.call_args.kwargs["data"]
        self.assertTrue(url.endswith("/add_rendezvous_client_libre"))
        self.assertEqual(form["p_centre"], "1")
        self.assertEqual(form["prestation_vl"], "1763")
        self.assertEqual(form["telephone"], "0612345678")
        self.assertEqual((form["date_rdv"], form["heure_rdv"]), ("2026-10-20", "09:00"))
        self.assertEqual(result["redirectUrl"], "https://webpayment.payline.com/v2/?token=abc")
        self.assertEqual(result["state"], "payment_pending")
        self.assertTrue(result["openInNewTab"])
        session.close.assert_called_once_with()

    def test_same_key_is_never_sent_twice(self):
        self._start(_session())
        second = _session()
        with self.assertRaises(checkout.HostedCheckoutError) as caught:
            self._start(second)
        self.assertEqual(str(caught.exception), "booking_reconciliation_required")
        second.post.assert_not_called()

    def test_service_without_mercure_online_payment_is_refused(self):
        session = _session()
        with self.assertRaises(checkout.HostedCheckoutError) as caught:
            self._start(session, online=False)
        self.assertEqual(str(caught.exception), "mercure_online_payment_unavailable")
        session.post.assert_not_called()

    def test_mercure_error_and_unexpected_answers(self):
        cases = {"error": "mercure_checkout_refused",
                 "https://evil.example/pay": "mercure_checkout_response_uncertain",
                 "<html>": "mercure_checkout_response_uncertain"}
        for text, code in cases.items():
            with self.subTest(text=text), tempfile.TemporaryDirectory() as data, \
                 patch.dict(os.environ, {"CYBERCHECK_DATA_DIR": data}):
                with self.assertRaises(checkout.HostedCheckoutError) as caught:
                    self._start(_session(text))
                self.assertEqual(str(caught.exception), code)

    def test_network_failure_after_send_is_uncertain(self):
        session = Mock()
        session.post.side_effect = TimeoutError("timeout")
        with self.assertRaises(checkout.HostedCheckoutError) as caught:
            self._start(session)
        self.assertEqual(str(caught.exception), "mercure_checkout_response_uncertain")

    def test_session_failure_sends_nothing_and_keeps_the_key_usable(self):
        def broken():
            raise ConnectionError("down")
        with self.assertRaises(ConnectionError):
            checkout.start(dict(PAYLOAD), account=ACCOUNT, environ=ENV, session_factory=broken,
                           payment_options=lambda service: {"online": True})
        session = _session()
        self.assertEqual(self._start(session)["state"], "payment_pending")
        session.post.assert_called_once()

    def test_checkout_url_accepts_mercure_relative_and_payline_hosts(self):
        self.assertEqual(checkout.checkout_url("/paiement/1"), "https://rdv.checkupauto.fr/paiement/1")
        self.assertTrue(checkout.checkout_url("https://webpayment.payline.com/v2/?token=x"))
        for bad in ("http://rdv.checkupauto.fr/x", "https://user:pw@rdv.checkupauto.fr/",
                    "https://rdv.checkupauto.fr.evil.test/", "javascript:alert(1)",
                    "https://homologation.payline.com.evil.test/"):
            with self.subTest(bad=bad), self.assertRaises(checkout.HostedCheckoutError):
                checkout.checkout_url(bad)

    def test_reconcile_confirms_only_a_paid_booking(self):
        self._start(_session())
        unpaid = checkout.reconcile(dict(PAYLOAD), account=ACCOUNT,
                                    finder=lambda **_: {"found": True, "appointmentId": "991", "paidOnline": False})
        self.assertEqual(unpaid["state"], "payment_pending")
        finder = Mock(return_value={"found": True, "appointmentId": "991", "paidOnline": True})
        paid = checkout.reconcile(dict(PAYLOAD), account=ACCOUNT, finder=finder)
        self.assertEqual((paid["state"], paid["providerReference"]), ("confirmed", "991"))
        self.assertEqual(finder.call_args.kwargs["email"], "client@example.test")
        again = checkout.reconcile(dict(PAYLOAD), account=ACCOUNT, finder=Mock(side_effect=AssertionError))
        self.assertTrue(again["confirmed"])

    def test_reconcile_refuses_a_slot_other_than_the_one_started(self):
        self._start(_session())
        other = {**PAYLOAD, "time": "10:00"}
        finder = Mock()
        with self.assertRaises(checkout.HostedCheckoutInvalid):
            checkout.reconcile(other, account=ACCOUNT, finder=finder)
        with self.assertRaises(checkout.HostedCheckoutInvalid):
            checkout.reconcile(dict(PAYLOAD), account={**ACCOUNT, "accountId": "acc-2"}, finder=finder)
        finder.assert_not_called()


class FindOnlineBookingTest(unittest.TestCase):
    def _events(self, **ext):
        base = {"rendezVousId": "991", "prestationId": "1763", "email": "Client@Example.test",
                "tokenPayline": "SECRET-TOKEN", "rendezVousFacturation": [{"montantPresta": 80}],
                "tarifTotal": "80,00"}
        base.update(ext)
        return [{"id": "991", "start": "2026-10-20T09:00:00", "extendedProps": base},
                {"id": "x", "start": "2026-10-20T09:00:00", "extendedProps": {"rdvDispo": True}}]

    def test_paid_booking_found_without_exposing_token(self):
        with patch.object(mercure_admin_client, "_calendar_events", return_value=self._events()):
            result = mercure_admin_client.find_online_booking(
                date="2026-10-20", time="09:00", email="client@example.test",
                service_id="1763", session=Mock())
        self.assertEqual(result, {"found": True, "appointmentId": "991", "paidOnline": True, "amountPaid": 80.0})
        self.assertNotIn("SECRET-TOKEN", repr(result))

    def test_unpaid_and_missing(self):
        with patch.object(mercure_admin_client, "_calendar_events",
                          return_value=self._events(tokenPayline="", rendezVousFacturation=[])):
            unpaid = mercure_admin_client.find_online_booking(
                date="2026-10-20", time="09:00", email="client@example.test",
                service_id="1763", session=Mock())
            missing = mercure_admin_client.find_online_booking(
                date="2026-10-20", time="09:00", email="autre@example.test",
                service_id="1763", session=Mock())
        self.assertFalse(unpaid["paidOnline"])
        self.assertEqual(missing, {"found": False})


if __name__ == "__main__":
    unittest.main()
