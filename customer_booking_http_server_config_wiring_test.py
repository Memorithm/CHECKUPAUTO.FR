import inspect
import unittest
import customer_http

class Tests(unittest.TestCase):
    def test_route_uses_server_config_not_browser_ids(self):
        source=inspect.getsource(customer_http.handle)
        block=source.split('if path=="/api/customer/booking/create":',1)[1].split(
            'if path=="/api/customer/booking/preflight":',1)[0]
        self.assertIn('customer_booking_server_config_source.load()',block)
        self.assertNotIn('request_body["lineId"]',block)
        self.assertIn('customer_auth_required',block)
        self.assertIn('customer_csrf_invalid',block)
