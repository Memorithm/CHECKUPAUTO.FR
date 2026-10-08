import unittest
from mercure_invoice_contact_contract import validate,MercureInvoiceContactError

class Tests(unittest.TestCase):
    def setUp(self):
        self.data=dict(surname="Test",givenName="Client",address="1 rue Test",postalCode="69000",city="Lyon",phone="0102030405",email="test@example.invalid")
    def test_valid(self):
        self.assertEqual(validate(self.data)["city"],"Lyon")
    def test_missing(self):
        for field in self.data:
            with self.subTest(field=field),self.assertRaises(MercureInvoiceContactError):
                validate({**self.data,field:""})
    def test_bad_email(self):
        with self.assertRaises(MercureInvoiceContactError):
            validate({**self.data,"email":"invalid"})
if __name__=="__main__": unittest.main()
