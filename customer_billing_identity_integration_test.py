import unittest
from unittest.mock import patch
import customer_accounts as accounts
import customer_http as http
import mercure_invoice_contact_contract as invoice
import customer_accounts_test as fixtures
from customer_http_test import Handler

class BillingIdentityIntegrationTests(unittest.TestCase):
    setUp=fixtures.CustomerAccountsTest.setUp
    create=fixtures.CustomerAccountsTest.create
    def contact_fixture(self):
        return dict(kind='individual',display_name='Alias distinct',phone='0102030405',address_line1='1 rue Essai',postal_code='78130',city='Les Mureaux')
    def test_explicit_names_are_encrypted_and_never_guessed(self):
        account=self.create();aid=account['accountId']
        self.assertEqual(account['surname'],'');self.assertFalse(account['billingContactComplete'])
        with self.assertRaises(invoice.MercureInvoiceContactError):accounts.billing_contact(aid)
        result=accounts.update_profile(aid,**self.contact_fixture(),surname='  Famille Essai ',given_name='Prénom Essai')
        self.assertEqual(result['surname'],'Famille Essai');self.assertTrue(result['billingContactComplete'])
        self.assertNotIn('Famille Essai'.encode(),accounts.data_path().read_bytes())
        projected=accounts.billing_contact(aid)
        self.assertEqual(projected['email'],'client@example.test');self.assertEqual(projected['surname'],'Famille Essai')
        self.assertNotIn('vehicleId',projected)
        accounts.update_profile(aid,**self.contact_fixture())
        self.assertEqual(accounts.profile(aid)['givenName'],'Prénom Essai')
    def test_invalid_or_partial_name_update_is_atomic(self):
        aid=self.create()['accountId']
        for name,given in (('', 'X'),('X',None),(1,'X'),('X\x00Y','X')):
            with self.subTest(name=name),self.assertRaises(accounts.CustomerAccountError):
                accounts.update_profile(aid,**self.contact_fixture(),surname=name,given_name=given)
        self.assertEqual(accounts.profile(aid)['displayName'],'Client Test')
    def test_http_profile_reads_the_verified_email(self):
        account=self.create();payload={'kind':'individual','displayName':'Alias','companyName':'','siret':'','phone':'0102030405','addressLine1':'1 rue Essai','addressLine2':'','postalCode':'78130','city':'Les Mureaux','surname':'Famille','givenName':'Prénom'}
        handler=Handler('/api/customer/profile','POST',payload=payload)
        with patch.object(http,'_account',return_value=('synthetic',account)),patch.object(http,'_same_origin',return_value=True),patch.object(accounts,'verify_csrf',return_value=True):
            self.assertTrue(http.handle(handler))
        self.assertEqual(handler.response['status'],200);self.assertTrue(handler.response['json']['billingContactComplete'])
        self.assertEqual(handler.response['json']['email'],account['email'])
