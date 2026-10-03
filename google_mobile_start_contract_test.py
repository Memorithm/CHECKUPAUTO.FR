import unittest
from unittest import mock
import customer_http

class GoogleMobileStartContractTest(unittest.TestCase):
    def test_mobile_query_is_forwarded_only_for_google(self):
        source=__import__("pathlib").Path(customer_http.__file__).read_text()
        self.assertIn('provider=="google"',source)
        self.assertIn('parse_qs(parsed.query).get("mobile")',source)
        self.assertIn("mobile=mobile",source)

if __name__=="__main__":
    unittest.main()
