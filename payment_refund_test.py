import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import payment_core as core
import payment_refund as refunds


class PaylineRefundLedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / "data"
        self.data.mkdir()
        self.env = patch.dict(os.environ, {"CYBERCHECK_DATA_DIR": str(self.data)}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = core.SandboxJournal(refunds.journal_path())
        quote = core.Quote("appointment-refund", "technical", 8000, "a" * 64)
        created = self.store.create(quote, "payline")
        bound = self.store.bind_provider(created.payment_id, "TOKEN_REFUND_FIXTURE")
        self.intent = self.store._apply_verified(core.VerifiedEvent(
            bound.payment_id,
            "payline",
            bound.provider_reference,
            "payline:TXN_REFUND_1:00000",
            "captured",
            8000,
            "TXN_REFUND_1",
        ))

    def execute(self, request_id, amount, refunder):
        with patch.object(refunds.payline_private, "load", return_value=object()):
            return refunds.execute(
                request_id,
                self.intent.payment_id,
                amount,
                "customer_request",
                refunder=refunder,
            )

    def test_success_is_persisted_idempotent_and_minimized(self):
        calls = []
        def provider(*args):
            calls.append(args)
            return object()

        first = self.execute("a" * 32, 3000, provider)
        second = self.execute("a" * 32, 3000, provider)

        self.assertEqual(first["state"], "completed")
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], "TXN_REFUND_1")
        self.assertEqual(calls[0][2], 3000)
        self.assertEqual(calls[0][4], "refund_" + "a" * 24)
        self.assertNotIn("TXN_REFUND_1", repr(first))
        self.assertRegex(first["evidenceHash"], r"^[0-9a-f]{64}$")

    def test_cumulative_refund_never_exceeds_verified_capture(self):
        self.execute("b" * 32, 5000, lambda *args: object())
        provider_calls = []
        with self.assertRaisesRegex(core.PaymentError, "^refund_amount_exceeds_remaining_capture$"):
            self.execute("c" * 32, 3001, lambda *args: provider_calls.append(args))
        self.assertEqual(provider_calls, [])

    def test_ambiguous_provider_failure_is_locked_for_reconciliation(self):
        calls = []
        def ambiguous(*args):
            calls.append(args)
            raise OSError("synthetic network interruption")

        with self.assertRaisesRegex(core.PaymentError, "^refund_reconciliation_required$"):
            self.execute("d" * 32, 1000, ambiguous)
        with self.assertRaisesRegex(core.PaymentError, "^refund_reconciliation_required$"):
            self.execute("d" * 32, 1000, lambda *args: self.fail("must not retry provider"))

        report = refunds.activity()
        self.assertEqual(report["summary"]["indeterminate"], 1)
        self.assertEqual(report["refunds"][0]["state"], "indeterminate")
        self.assertEqual(len(calls), 1)

    def test_activity_balances_are_authoritative_beyond_visible_history(self):
        self.execute("1" * 32, 3000, lambda *args: object())

        def refused(*args):
            raise core.PaymentError("payline_refund_refused")
        with self.assertRaisesRegex(core.PaymentError, "^payline_refund_refused$"):
            self.execute("2" * 32, 1000, refused)

        def ambiguous(*args):
            raise OSError("synthetic network interruption")
        with self.assertRaisesRegex(core.PaymentError, "^refund_reconciliation_required$"):
            self.execute("3" * 32, 500, ambiguous)

        report = refunds.activity(limit=1)
        self.assertEqual(len(report["refunds"]), 1)
        self.assertEqual(len(report["balances"]), 1)
        balance = report["balances"][0]
        self.assertEqual(balance["paymentId"], self.intent.payment_id)
        self.assertEqual(balance["capturedAmountCents"], 8000)
        self.assertEqual(balance["reservedAmountCents"], 3500)
        self.assertEqual(balance["remainingAmountCents"], 4500)
        self.assertTrue(balance["blocked"])

    def test_request_id_replay_cannot_change_amount_or_reason(self):
        self.execute("e" * 32, 1000, lambda *args: object())
        with patch.object(refunds.payline_private, "load", return_value=object()):
            with self.assertRaisesRegex(core.PaymentError, "^refund_request_replay_conflict$"):
                refunds.execute(
                    "e" * 32,
                    self.intent.payment_id,
                    999,
                    "customer_request",
                    refunder=lambda *args: self.fail("must not call provider"),
                )

    def test_definitive_provider_refusal_is_not_retried(self):
        calls = []
        def refused(*args):
            calls.append(args)
            raise core.PaymentError("payline_refund_refused")

        with self.assertRaisesRegex(core.PaymentError, "^payline_refund_refused$"):
            self.execute("f" * 32, 1000, refused)
        replay = self.execute("f" * 32, 1000, lambda *args: self.fail("must not retry provider"))
        self.assertEqual(replay["state"], "refused")
        self.assertTrue(replay["reused"])
        self.assertEqual(len(calls), 1)

    def test_capability_remains_sandbox_only(self):
        capability = refunds.capability()
        self.assertTrue(capability["operatorRefundLedger"])
        self.assertTrue(capability["cumulativeCaptureLimit"])
        self.assertTrue(capability["ambiguousRefundRetryBlocked"])
        self.assertTrue(capability["authoritativeRefundBalances"])
        self.assertFalse(capability["liveRefundsEnabled"])


if __name__ == "__main__":
    unittest.main()
