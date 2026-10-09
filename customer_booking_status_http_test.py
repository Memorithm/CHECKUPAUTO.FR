import inspect
import unittest
import customer_http

class Tests(unittest.TestCase):
    def test_status_route_requires_auth_and_account_binding(self):
        source=inspect.getsource(customer_http.handle)
        segment=source.split('if path=="/api/customer/booking/status":',1)[1].split(
            'if path=="/api/customer/booking/readiness":',1)[0]
        self.assertIn('customer_auth_required',segment)
        self.assertIn('account_id=account["accountId"]',segment)
        self.assertIn('customer_booking_confirmation_view.view(',segment)
        self.assertNotIn('accountId"]',segment.split('query=parse_qs',1)[1].split('account_id=',1)[0])
    def test_read_only(self):
        source=inspect.getsource(customer_http.handle)
        segment=source.split('if path=="/api/customer/booking/status":',1)[1].split(
            'if path=="/api/customer/booking/readiness":',1)[0]
        self.assertIn('if command!="GET":',segment)
        self.assertNotIn('create_and_verify(',segment)

if __name__=="__main__":
    unittest.main()
