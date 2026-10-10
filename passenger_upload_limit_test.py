import io
import unittest

import customer_ct_reports
import passenger_wsgi as wsgi


class PassengerUploadLimitTest(unittest.TestCase):
    """Q-02: the Passenger bridge must accept CT report uploads up to the backend limit."""

    def environ(self, method, path, length):
        return {"REQUEST_METHOD": method, "PATH_INFO": path, "CONTENT_LENGTH": str(length), "wsgi.input": io.BytesIO(b"x" * length)}

    def test_report_upload_limit_matches_backend(self):
        self.assertEqual(wsgi.UPLOAD_BODY_LIMITS[("POST", "/api/customer/reports")], customer_ct_reports.MAX_UPLOAD_BYTES)

    def test_large_report_upload_is_forwarded(self):
        size = 2 * 1024 * 1024
        body = wsgi._request_body(self.environ("POST", "/api/customer/reports", size))
        self.assertEqual(len(body), size)

    def test_other_routes_keep_small_limit(self):
        with self.assertRaisesRegex(ValueError, "volumineux"):
            wsgi._request_body(self.environ("POST", "/api/customer/profile", wsgi.DEFAULT_BODY_LIMIT + 1))
        with self.assertRaisesRegex(ValueError, "volumineux"):
            wsgi._request_body(self.environ("PUT", "/api/customer/reports", wsgi.DEFAULT_BODY_LIMIT + 1))

    def test_report_upload_above_backend_limit_is_rejected(self):
        env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/customer/reports", "CONTENT_LENGTH": str(customer_ct_reports.MAX_UPLOAD_BYTES + 1), "wsgi.input": io.BytesIO(b"")}
        with self.assertRaisesRegex(ValueError, "volumineux"):
            wsgi._request_body(env)


if __name__ == "__main__":
    unittest.main()
