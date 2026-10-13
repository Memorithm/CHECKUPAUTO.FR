"""Security controls for native customer email and owned-account routes."""
import unittest
import security_guard
import customer_http


class MobileEmailSecurityContractTests(unittest.TestCase):
    def test_native_email_routes_have_strict_limits(self):
        limits = security_guard._ENDPOINT_LIMITS
        self.assertEqual(limits[customer_http.MOBILE_EMAIL_SIGNIN_ROUTE], 10)
        self.assertEqual(limits[customer_http.MOBILE_EMAIL_REGISTER_ROUTE], 4)
        self.assertLess(limits[customer_http.MOBILE_EMAIL_REGISTER_ROUTE],
                        limits[customer_http.MOBILE_EMAIL_SIGNIN_ROUTE])

    def test_private_native_account_endpoints_are_rate_limited(self):
        limits = security_guard._ENDPOINT_LIMITS
        self.assertLessEqual(limits[customer_http.MOBILE_AUTH_SESSION_ROUTE], 30)
        self.assertLessEqual(limits[customer_http.MOBILE_ACCOUNT_VEHICLES_ROUTE], 30)

    def test_mobile_account_session_is_bearer_only(self):
        class Handler:
            headers = {}
        with self.assertRaises(PermissionError):
            customer_http._mobile_bearer_account(Handler())


if __name__ == "__main__":
    unittest.main()
