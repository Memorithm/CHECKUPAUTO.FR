import unittest
import compliance_store
class LegalDocumentContractTest(unittest.TestCase):
 def test_all_public_legal_documents_are_required(self):
  self.assertEqual(set(compliance_store.DOCUMENT_TYPES),{"legal_notice","privacy","cookies","terms","withdrawal"})
  self.assertEqual(len(compliance_store.DOCUMENT_TYPES),5)
 def test_privacy_has_public_route(self):
  self.assertEqual(compliance_store.DOCUMENT_TYPES["privacy"]["slug"],"/confidentialite")
if __name__=="__main__": unittest.main()
