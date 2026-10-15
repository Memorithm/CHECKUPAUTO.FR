import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import mercure_refund as refund

ENV = {refund.ENABLE_ENV: "true"}
HEADERS = {"Authorization": "Basic YWRtaW46eA==", "Cookie": "cc_admin_mfa=abc"}
TOKEN = "PAYLINE-SECRET-TOKEN-0123456789AB"


def event(**ext):
    base = {"rendezVousId": 6100654, "prestationId": [1763], "nom": "DUPONT Alex",
            "email": "client@example.test", "tokenPayline": TOKEN, "tarifTotal": "80.00",
            "rendezVousFacturation": [{"optModeReglement": "CARTE BLEUE", "montantPresta": "80.00"}]}
    base.update(ext)
    return {"id": "6100654", "start": "2026-10-21 18:20:00", "extendedProps": base}


class FakeMercure:
    def __init__(self, events, refund_answer=None, remove_answer="ok"):
        self.events = events
        self.refund_answer = refund_answer if refund_answer is not None else {"result": "OK", "Msg": "Transaction approved"}
        self.remove_answer = remove_answer
        self.posts = []

    def factory(self):
        return self

    def post(self, url, data=None, **_):
        self.posts.append((url.rsplit("/", 1)[-1], dict(data)))
        if url.endswith("/rendez_vous_remboursement"):
            if isinstance(self.refund_answer, Exception):
                raise self.refund_answer
            for e in (self.events if self.refund_answer.get("result") == "OK" else []):
                e["extendedProps"].update(tokenPayline="", tarifTotal="", rendezVousFacturation=[])
            return Mock(status_code=200, text=json.dumps(self.refund_answer), headers={},
                        json=lambda: self.refund_answer)
        if url.endswith("/rendez_vous_remove"):
            self.events.clear()
            return Mock(status_code=200, text=self.remove_answer, headers={})
        raise AssertionError(url)


class RefundTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, {"CYBERCHECK_PRIVATE_DIR": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.mercure = FakeMercure([event()])
        cal = patch.object(refund.mercure, "_calendar_events", side_effect=lambda s, a, b: list(s.events))
        cal.start()
        self.addCleanup(cal.stop)

    def lookup(self, **extra):
        body = {"appointmentId": "6100654", "date": "2026-10-21", **extra}
        return refund.lookup(body, headers=HEADERS, environ=ENV, session_factory=self.mercure.factory)

    def execute(self, confirmation, *, rid="6100654", amount="80", code_ok=True, headers=HEADERS, now=None):
        verify = Mock(return_value=code_ok)
        result = refund.execute({"confirmation": confirmation, "appointmentId": rid, "amount": amount,
                                 "code": "123456"}, headers=headers, verify_code=verify, environ=ENV,
                                session_factory=self.mercure.factory, now=now)
        return result, verify

    def files_text(self):
        root = Path(self.tmp.name) / "mercure-refunds"
        return "".join(p.read_text(errors="ignore") for p in root.iterdir() if p.is_file())

    def test_disabled_by_default_and_reads_nothing(self):
        factory = Mock()
        with self.assertRaises(refund.RefundError) as caught:
            refund.lookup({"appointmentId": "1", "date": "2026-10-21"}, headers=HEADERS,
                          environ={}, session_factory=factory)
        self.assertEqual(caught.exception.code, "refund_disabled")
        factory.assert_not_called()

    def test_lookup_is_read_only_masks_customer_and_never_returns_token(self):
        result = self.lookup()
        a = result["appointment"]
        self.assertEqual((a["appointmentId"], a["paidCents"], a["refundable"]), ("6100654", 8000, True))
        self.assertEqual((a["customer"], a["email"]), ("D. A.", "c•••@example.test"))
        self.assertEqual(a["start"], "2026-10-21T18:20")
        self.assertEqual(result["amountCents"], 8000)
        self.assertNotIn(TOKEN, json.dumps(result))
        self.assertNotIn(TOKEN, base64.urlsafe_b64decode(result["confirmation"].split(".")[0] + "==").decode())
        self.assertEqual(self.mercure.posts, [])

    def test_full_refund_then_cancel_once_and_journal_has_no_secret(self):
        result, verify = self.execute(self.lookup()["confirmation"])
        self.assertEqual(result, {"ok": True, "appointmentId": "6100654", "refundedCents": 8000,
                                  "cancelRequested": True, "cancelled": True})
        verify.assert_called_once_with("123456")
        self.assertEqual(self.mercure.posts[0], ("rendez_vous_remboursement", {"token": TOKEN, "montant": "80"}))
        self.assertEqual(self.mercure.posts[1], ("rendez_vous_remove", {"rendezvous_id": "6100654"}))
        self.assertEqual(refund.history()[0]["state"], "refunded")
        text = self.files_text()
        self.assertNotIn(TOKEN, text)
        self.assertNotIn("client@example.test", text)
        for path in (Path(self.tmp.name) / "mercure-refunds").iterdir():
            self.assertEqual(path.stat().st_mode & 0o077, 0, path)

    def test_a_booking_is_never_refunded_twice(self):
        confirmation = self.lookup(cancelAfter=False)["confirmation"]
        self.execute(confirmation)
        with self.assertRaises(refund.RefundError) as caught:
            self.execute(confirmation)
        self.assertEqual(caught.exception.code, "refund_confirmation_used")
        again = self.lookup()
        self.assertIsNone(again["confirmation"])
        self.assertEqual(again["appointment"]["previousRefund"]["state"], "refunded")
        self.assertEqual([p[0] for p in self.mercure.posts], ["rendez_vous_remboursement"])

    def test_bad_second_factor_or_retype_calls_nothing(self):
        confirmation = self.lookup()["confirmation"]
        for kwargs, code in (({"code_ok": False}, "refund_second_factor_invalid"),
                             ({"rid": "6100655"}, "refund_retype_mismatch"),
                             ({"amount": "79"}, "refund_retype_mismatch")):
            with self.subTest(code=code), self.assertRaises(refund.RefundError) as caught:
                self.execute(confirmation, **kwargs)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.mercure.posts, [])

    def test_confirmation_is_bound_to_session_expiry_and_signature(self):
        confirmation = self.lookup()["confirmation"]
        cases = [({"headers": {**HEADERS, "Cookie": "other"}}, "refund_confirmation_invalid"),
                 ({"now": 4102444800}, "refund_confirmation_expired")]
        body, mac = confirmation.split(".")
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        claims["cents"] = 1
        forged = base64.urlsafe_b64encode(json.dumps(claims, sort_keys=True).encode()).decode().rstrip("=") + "." + mac
        cases.append(({"amount": "0.01", "confirmation": forged}, "refund_confirmation_invalid"))
        for kwargs, code in cases:
            with self.subTest(code=code), self.assertRaises(refund.RefundError) as caught:
                self.execute(kwargs.pop("confirmation", confirmation), **kwargs)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.mercure.posts, [])

    def test_amount_limits_and_partial_refund_format(self):
        with self.assertRaises(refund.RefundError) as caught:
            self.lookup(amount="80,01")
        self.assertEqual(caught.exception.code, "refund_amount_exceeds_paid")
        for bad in ("0", "-5", "8e1", "abc"):
            with self.subTest(bad=bad), self.assertRaises(refund.RefundError):
                self.lookup(amount=bad)
        confirmation = self.lookup(amount="12,50", cancelAfter=False)["confirmation"]
        self.execute(confirmation, amount="12.5")
        self.assertEqual(self.mercure.posts, [("rendez_vous_remboursement", {"token": TOKEN, "montant": "12.50"})])

    def test_unpaid_booking_gets_no_confirmation(self):
        self.mercure.events[:] = [event(rendezVousFacturation=[])]
        result = self.lookup()
        self.assertFalse(result["appointment"]["refundable"])
        self.assertIsNone(result["confirmation"])

    def test_payment_gone_between_lookup_and_execute_is_refused(self):
        confirmation = self.lookup()["confirmation"]
        self.mercure.events[0]["extendedProps"]["rendezVousFacturation"] = []
        with self.assertRaises(refund.RefundError) as caught:
            self.execute(confirmation)
        self.assertEqual(caught.exception.code, "refund_not_refundable")
        self.assertEqual(self.mercure.posts, [])

    def test_timeout_blocks_retries_until_checked_in_the_planning(self):
        self.mercure.refund_answer = TimeoutError("timeout")
        with self.assertRaises(refund.RefundError) as caught:
            self.execute(self.lookup()["confirmation"])
        self.assertEqual(caught.exception.code, "refund_outcome_uncertain")
        self.assertEqual(refund.history()[0]["state"], "uncertain")
        self.assertIsNone(self.lookup()["confirmation"])
        # Mercure did refund: token and billing are gone from the planning.
        self.mercure.events[0]["extendedProps"].update(tokenPayline="", tarifTotal="", rendezVousFacturation=[])
        settled = refund.verify_uncertain({"appointmentId": "6100654"}, environ=ENV,
                                          session_factory=self.mercure.factory)
        self.assertEqual(settled["state"], "refunded")

    def test_uncertain_refund_that_did_not_happen_can_be_retried(self):
        self.mercure.refund_answer = TimeoutError("timeout")
        with self.assertRaises(refund.RefundError):
            self.execute(self.lookup()["confirmation"])
        self.mercure.events[:] = [event()]
        settled = refund.verify_uncertain({"appointmentId": "6100654"}, environ=ENV,
                                          session_factory=self.mercure.factory)
        self.assertEqual(settled["state"], "refused")
        self.assertIsNotNone(self.lookup()["confirmation"])

    def test_mercure_refusal_is_recorded_and_retry_allowed(self):
        self.mercure.refund_answer = {"Msg": "Transaction refused"}
        with self.assertRaises(refund.RefundError) as caught:
            self.execute(self.lookup()["confirmation"])
        self.assertEqual(caught.exception.code, "refund_refused_by_mercure")
        self.assertEqual(refund.history()[0]["state"], "refused")
        self.assertIsNotNone(self.lookup()["confirmation"])

    def test_http_error_from_mercure_is_uncertain_not_refused(self):
        self.mercure.post = lambda url, data=None, **_: Mock(status_code=502, text="", headers={})
        with self.assertRaises(refund.RefundError) as caught:
            self.execute(self.lookup()["confirmation"])
        self.assertEqual(caught.exception.code, "refund_outcome_uncertain")
        self.assertIsNone(self.lookup()["confirmation"])

    def test_pending_left_by_a_killed_worker_can_be_settled_once_stale(self):
        root = Path(self.tmp.name) / "mercure-refunds"
        root.mkdir(mode=0o700, exist_ok=True)
        now = 1_800_000_000
        (root / "journal.json").write_text(json.dumps({"6100654": {
            "state": "pending", "amountCents": 8000, "day": "2026-10-21", "bookingDay": "2026-10-21",
            "at": now, "cancelled": False}}))
        self.assertIsNone(self.lookup()["confirmation"])
        with self.assertRaises(refund.RefundError) as caught:
            refund.verify_uncertain({"appointmentId": "6100654"}, environ=ENV,
                                    session_factory=self.mercure.factory, now=now + 30)
        self.assertEqual(caught.exception.code, "refund_not_uncertain")
        settled = refund.verify_uncertain({"appointmentId": "6100654"}, environ=ENV,
                                          session_factory=self.mercure.factory, now=now + 600)
        self.assertEqual(settled["state"], "refused")
        self.assertIsNotNone(self.lookup()["confirmation"])

    def test_daily_cap(self):
        env = {**ENV, refund.DAILY_CAP_ENV: "100"}
        refund.execute({"confirmation": self.lookup(cancelAfter=False)["confirmation"], "appointmentId": "6100654",
                        "amount": "80", "code": "1"}, headers=HEADERS, verify_code=lambda c: True,
                       environ=env, session_factory=self.mercure.factory)
        other = event(rendezVousId=6100700)
        other["id"] = "6100700"
        self.mercure.events[:] = [other]
        confirmation = refund.lookup({"appointmentId": "6100700", "date": "2026-10-21"}, headers=HEADERS,
                                     environ=env, session_factory=self.mercure.factory)["confirmation"]
        with self.assertRaises(refund.RefundError) as caught:
            refund.execute({"confirmation": confirmation, "appointmentId": "6100700", "amount": "80",
                            "code": "1"}, headers=HEADERS, verify_code=lambda c: True, environ=env,
                           session_factory=self.mercure.factory)
        self.assertEqual(caught.exception.code, "refund_daily_cap_reached")

    def test_rejects_unknown_fields_and_bad_ids(self):
        for body in ({"appointmentId": "6100654", "date": "2026-10-21", "token": "x"},
                     {"appointmentId": "61-00", "date": "2026-10-21"},
                     {"appointmentId": "6100654", "date": "21/10/2026"}):
            with self.subTest(body=body), self.assertRaises(refund.RefundError):
                refund.lookup(body, headers=HEADERS, environ=ENV, session_factory=self.mercure.factory)


if __name__ == "__main__":
    unittest.main()
