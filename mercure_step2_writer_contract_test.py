import unittest
from mercure_step2_writer_contract import verify_writer
class Writer:
 def create_once(self,request):pass
 def read_identity(self,request,reference):pass
class Tests(unittest.TestCase):
 def test_default_fails_closed(self):
  with self.assertRaises(ValueError):verify_writer(Writer())
 def test_both_methods_required(self):
  with self.assertRaises(ValueError):verify_writer(object(),qualified=True)
 def test_explicit_contract(self):
  w=Writer();self.assertIs(verify_writer(w,qualified=True),w)
