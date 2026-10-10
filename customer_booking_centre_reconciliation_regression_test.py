"""Offline booking-centre acceptance tests; never contact real Mercure."""
import datetime as dt
import os
import tempfile
import unittest
from unittest.mock import patch

import customer_booking_creation as creation
import customer_booking_journal as journal
import customer_booking_confirmation_view as confirmation
from mercure_booking_write_contract import BookingWriteRequest, BookingWriteReceipt
from mercure_booking_identity_evidence import VerifiedBookingIdentity


class FakeMercure:
    def __init__(self, *, fail=False):
        self.writes = 0
        self.fail = fail

    def create_once(self, request):
        self.writes += 1
        if self.fail:
            raise TimeoutError('ambiguous response')
        return BookingWriteReceipt(provider_reference='mercure-123', accepted=True)

    def read_identity(self, request, provider_reference):
        return VerifiedBookingIdentity(provider_reference, request.account_id,
                                       request.vehicle_id, request.service, True)


class CentreBookingRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'CYBERCHECK_DATA_DIR': self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.request = BookingWriteRequest(
            request_key='booking-centre-acceptance-00001', account_id='account1',
            vehicle_id='vehicle1', service='technical',
            date=(dt.date.today() + dt.timedelta(days=2)).isoformat(),
            time='09:00', price_cents=8000)

    def test_confirmed_appointment_replay_does_not_write_twice(self):
        provider = FakeMercure()
        with patch.object(creation.reconciliation.evidence, 'verify_appointment', return_value=True):
            first = creation.create_and_verify(request=self.request, provider=provider)
            second = creation.create_and_verify(request=self.request, provider=provider)
        self.assertTrue(first['confirmed'])
        self.assertTrue(second['confirmed'])
        self.assertEqual(provider.writes, 1)
        with patch.object(confirmation, 'status', return_value={'confirmed': True}):
            shown = confirmation.view(account_id='account1', request_key=self.request.request_key,
                payment_status={'service': 'technical', 'providerVerified': True,
                                'paymentMode': 'centre', 'paymentRequired': False})
        self.assertTrue(shown['confirmed'])
        self.assertFalse(shown['paymentConfirmed'])
        self.assertIn('au centre', shown['paymentMessage'])

    def test_timeout_never_retries_external_write(self):
        provider = FakeMercure(fail=True)
        with self.assertRaises(creation.BookingCreationError):
            creation.create_and_verify(request=self.request, provider=provider)
        replay = creation.create_and_verify(request=self.request, provider=provider)
        self.assertFalse(replay['confirmed'])
        self.assertEqual(replay['state'], 'reconciliation_required')
        self.assertEqual(provider.writes, 1)

    def test_unverified_calendar_never_confirms_booking(self):
        provider = FakeMercure()
        with patch.object(creation.reconciliation.evidence, 'verify_appointment', return_value=False):
            result = creation.create_and_verify(request=self.request, provider=provider)
        self.assertFalse(result['confirmed'])
        self.assertEqual(provider.writes, 1)

    def test_second_account_cannot_reuse_idempotency_key(self):
        provider = FakeMercure()
        with patch.object(creation.reconciliation.evidence, 'verify_appointment', return_value=True):
            creation.create_and_verify(request=self.request, provider=provider)
        other = BookingWriteRequest(request_key=self.request.request_key,
            account_id='account2', vehicle_id='vehicle1', service='technical',
            date=self.request.date, time=self.request.time, price_cents=8000)
        with self.assertRaises(journal.BookingJournalError):
            creation.create_and_verify(request=other, provider=provider)
        self.assertEqual(provider.writes, 1)


if __name__ == '__main__':
    unittest.main()
