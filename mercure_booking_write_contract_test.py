import unittest

import mercure_booking_write_contract as contract


class MercureBookingWriterContractTest(unittest.TestCase):
    def test_default_writer_never_creates_a_real_appointment(self):
        request=contract.BookingWriteRequest(
            request_key="booking-key-00000000001",account_id="customer-1",
            vehicle_id="vehicle-1",service="technical",
            date="2026-10-15",time="10:30",price_cents=8000)
        with self.assertRaisesRegex(contract.MercureBookingWriteError,
                                    "mercure_booking_writer_unqualified"):
            contract.writer().create_once(request)

    def test_contract_has_no_synthetic_writer_fallback(self):
        self.assertIsInstance(contract.writer(),contract.UnqualifiedMercureWriter)


if __name__=="__main__":
    unittest.main()
