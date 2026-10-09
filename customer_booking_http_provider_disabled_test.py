import inspect
import unittest
import customer_http

class Tests(unittest.TestCase):
    def test_unqualified_provider_has_stable_error(self):
        source=inspect.getsource(customer_http.handle)
        block=source.split('if path=="/api/customer/booking/create":',1)[1].split(
            'if path=="/api/customer/booking/preflight":',1)[0]
        self.assertIn("BookingHttpContextError",block)
        self.assertIn('"booking_provider_not_qualified"',block)
        self.assertIn('customer_auth_required',block)
        self.assertIn('customer_csrf_invalid',block)

if __name__=="__main__":
    unittest.main()
