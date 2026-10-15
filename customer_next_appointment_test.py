import datetime
import unittest
from unittest.mock import Mock

import customer_next_appointment as nxt

NOW = datetime.datetime(2026, 10, 15, 12, 0, tzinfo=nxt.mercure.MERCURE_TIMEZONE).timestamp()
ACCOUNT = {"email": "Client@Example.test", "emailVerified": True}


def event(rid, start, **ext):
    base = {"rendezVousId": rid, "prestationId": [1763], "email": "client@example.test",
            "nom": "DUPONT Alex", "telephone": "0600000000", "tokenPayline": "SECRET",
            "rendezVousFacturation": [{"optModeReglement": "CARTE BLEUE"}], "tarifTotal": "80.00",
            "vehiculeNom": "RENAULT CLIO"}
    base.update(ext)
    return {"id": str(rid), "start": start, "end": start, "extendedProps": base}


class NextAppointmentTest(unittest.TestCase):
    def setUp(self):
        nxt._SNAPSHOT.update(at=0.0, day="", events=None)

    def run_with(self, events, account=ACCOUNT, now=NOW):
        return nxt.upcoming(account, now=now, fetch=lambda a, b: events)

    def test_next_paid_booking_without_private_fields(self):
        result = self.run_with([
            event(3, "2026-11-02 09:00:00"),
            event(1, "2026-10-14 10:00:00"),          # past
            event(2, "2026-10-21 18:20:00"),
            event(4, "2026-10-20 09:00:00", email="autre@example.test"),
            {"id": "x", "start": "2026-10-16 09:00:00", "extendedProps": {"rdvDispo": True}},
        ])
        self.assertTrue(result["available"])
        self.assertEqual(result["next"], {"appointmentId": "2", "start": "2026-10-21T18:20+02:00",
                                          "end": "2026-10-21T18:20+02:00", "service": "Contrôle technique",
                                          "vehicle": "RENAULT CLIO", "paidOnline": True, "amount": 80.0})
        self.assertEqual([o["appointmentId"] for o in result["others"]], ["3"])
        text = repr(result)
        for secret in ("SECRET", "DUPONT", "0600000000", "autre@"):
            self.assertNotIn(secret, text)

    def test_unpaid_online_checkout_is_not_validated_but_centre_payment_is(self):
        result = self.run_with([
            event(5, "2026-10-16 09:00:00", rendezVousFacturation=[]),
            event(6, "2026-10-17 09:00:00", tokenPayline="", rendezVousFacturation=[], prestationId=1758),
        ])
        self.assertEqual(result["next"]["appointmentId"], "6")
        self.assertFalse(result["next"]["paidOnline"])
        self.assertIsNone(result["next"]["amount"])
        self.assertEqual(result["next"]["service"], "Prestation au centre")

    def test_unverified_email_reads_nothing(self):
        fetch = Mock()
        result = nxt.upcoming({"email": "client@example.test", "emailVerified": False}, now=NOW, fetch=fetch)
        self.assertEqual(result["reason"], "email_not_verified")
        fetch.assert_not_called()

    def test_provider_failure_is_reported_softly(self):
        def broken(a, b):
            raise RuntimeError("session expired")
        result = nxt.upcoming(ACCOUNT, now=NOW, fetch=broken)
        self.assertEqual((result["available"], result["reason"]), (False, "provider_unavailable"))

    def test_snapshot_is_shared_for_a_short_time(self):
        fetch = Mock(return_value=[event(2, "2026-10-21 18:20:00")])
        nxt.upcoming(ACCOUNT, now=NOW, fetch=fetch)
        nxt.upcoming({"email": "x@example.test", "emailVerified": True}, now=NOW + 30, fetch=fetch)
        self.assertEqual(fetch.call_count, 1)
        nxt.upcoming(ACCOUNT, now=NOW + nxt.SNAPSHOT_TTL_SECONDS + 1, fetch=fetch)
        self.assertEqual(fetch.call_count, 2)
        start, end = fetch.call_args.args
        self.assertEqual(start, "2026-10-15")
        self.assertEqual(end, "2027-02-12")

    def test_no_upcoming(self):
        self.assertIsNone(self.run_with([])["next"])


if __name__ == "__main__":
    unittest.main()
