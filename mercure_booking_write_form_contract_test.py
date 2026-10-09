import unittest

from mercure_booking_write_form_contract import (
    REQUIRED_FIELDS,audit,MercureWriteFormContractError,
)


class MercureWriteFormContractTests(unittest.TestCase):
    def test_complete_observed_form_is_not_customer_write_authorization(self):
        result=audit(REQUIRED_FIELDS)
        self.assertTrue(result.contract_observed)
        self.assertFalse(result.customer_write_qualified)
        self.assertEqual(result.missing_fields,())

    def test_missing_required_field(self):
        result=audit(REQUIRED_FIELDS-{"prestation"})
        self.assertEqual(result.missing_fields,("prestation",))
        self.assertFalse(result.contract_observed)

    def test_malformed_input(self):
        for value in (None,{},[42],[""],["x"*81]):
            with self.subTest(value=value),self.assertRaises(MercureWriteFormContractError):
                audit(value)


if __name__=="__main__":
    unittest.main()
