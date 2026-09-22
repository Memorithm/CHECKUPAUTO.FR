import unittest
from unittest.mock import patch

import payment_contract_http as http
from payment_contract_test import FakeHandler


class ContractCSRFBoundaryTest(unittest.TestCase):
    def test_malformed_tokens_are_rejected_before_storage_without_reflection(self):
        for token in ('é' * 64, 'Z' * 64, 'a' * 63, 'a' * 65, None, 123):
            with self.subTest(token_type=type(token).__name__):
                handler = FakeHandler('POST', {'revision': 0, 'mode': 'manual', 'fields': {}})
                handler.headers['X-CheckupAuto-Payments-CSRF'] = token
                with patch.object(http, 'ContractStore') as storage:
                    self.assertTrue(http.handle(handler, secret='synthetic-secret'))
                self.assertEqual(handler.response, (403, {'ok': False, 'error': 'payments_csrf_invalid'}))
                storage.assert_not_called()


if __name__ == '__main__':
    unittest.main()
