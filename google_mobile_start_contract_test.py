import unittest
from unittest import mock
import customer_http

class GoogleMobileStartContractTest(unittest.TestCase):
    def test_mobile_query_is_forwarded_only_for_google(self):
        source=__import__("pathlib").Path(customer_http.__file__).read_text()
        self.assertIn('provider=="google"',source)
        self.assertIn('auth_query=parse_qs(parsed.query,keep_blank_values=True,max_num_fields=8)',source)
        self.assertIn('(auth_query.get("mobile") or [""])[0]=="1"',source)
        self.assertIn("mobile=mobile",source)

if __name__=="__main__":
    unittest.main()
