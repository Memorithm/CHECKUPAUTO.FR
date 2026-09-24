import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import analytics_store as analytics
import payment_test_lab as lab


class PaymentTestLabTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.previous_db=analytics.DB
        analytics.DB=Path(self.tmp.name)/"analytics.sqlite3"
        self.addCleanup(setattr,analytics,"DB",self.previous_db)

    def test_disabled_by_default(self):
        with patch.dict(os.environ,{"CYBERCHECK_PAYMENT_TEST_ENABLED":"0"},clear=False):
            with self.assertRaises(PermissionError):
                lab.create_session()

    def test_create_reservation_binds_synthetic_mercure_to_local_payment(self):
        fake_store=MagicMock()
        fake_store.bind_provider.return_value=None
        with patch.dict(os.environ,{"CYBERCHECK_PAYMENT_TEST_ENABLED":"1"},clear=False), \
             patch.object(lab.booking_test,"status",return_value={"ok":True,"status":"ready"}), \
             patch.object(lab.booking_test,"create_appointment",return_value={
                 "appointmentId":"RDV-TEST-123","appointmentAt":"2026-10-03T09:00",
                 "price":80.0,"providerVerified":True,
             }), \
             patch.object(lab.booking,"create_intent",return_value={"token":"ccid-test"}), \
             patch.object(lab.booking,"browser_token",return_value="cct-test"), \
             patch.object(lab.compliance,"published_document",return_value={
                 "version":"2026-09","contentHash":"a"*64,
             }), \
             patch.object(lab.booking,"record_terms_acceptance",return_value={"ok":True}), \
             patch.object(lab.booking,"apply_conversion",return_value={
                 "ok":True,"contractAcceptanceBound":True,
             }), \
             patch.object(lab.checkout,"create_sandbox_intent",return_value={
                 "paymentId":"b"*32,"provider":"payline","environment":"sandbox",
                 "state":"created","amountCents":8000,"currency":"EUR",
             }), \
             patch.object(lab,"SandboxJournal",return_value=fake_store):
            result=lab.create_reservation(
                "session-token","technical","2026-10-03","09:00",
                accept_terms=True,immediate_performance=True,
            )
        self.assertEqual(result["appointment"]["id"],"RDV-TEST-123")
        self.assertEqual(result["payment"]["amountCents"],8000)
        self.assertIn("/payment/test/provider#token=session-token",result["providerUrl"])
        fake_store.bind_provider.assert_called_once_with("b"*32,"TESTPAY_"+"b"*32)
        with analytics.connect() as db:
            row=db.execute("SELECT state,payment_id FROM payment_test_runs").fetchone()
        self.assertEqual(row["state"],"payment-ready")
        self.assertEqual(row["payment_id"],"b"*32)

    def test_create_failure_removes_synthetic_appointment(self):
        with patch.dict(os.environ,{"CYBERCHECK_PAYMENT_TEST_ENABLED":"1"},clear=False), \
             patch.object(lab.booking_test,"status",return_value={"ok":True,"status":"ready"}), \
             patch.object(lab.booking_test,"create_appointment",return_value={
                 "appointmentId":"RDV-TEST-123","appointmentAt":"2026-10-03T09:00",
                 "price":80.0,"providerVerified":True,
             }), \
             patch.object(lab.booking,"create_intent",side_effect=RuntimeError("boom")), \
             patch.object(lab.booking_test,"remove_appointment") as remove:
            with self.assertRaisesRegex(lab.PaymentTestError,"^payment_test_booking_intent_failed$"):
                lab.create_reservation(
                    "session-token","technical","2026-10-03","09:00",
                    accept_terms=True,immediate_performance=True,
                )
        remove.assert_called_once_with("session-token")

    def test_result_requires_session_bound_payment(self):
        with patch.dict(os.environ,{"CYBERCHECK_PAYMENT_TEST_ENABLED":"1"},clear=False), \
             patch.object(lab.booking_test,"status",return_value={"ok":True,"status":"ready"}):
            lab.init_db()
            with self.assertRaises(PermissionError):
                lab.apply_result("session-token","c"*32,"captured")


if __name__=="__main__":
    unittest.main()
