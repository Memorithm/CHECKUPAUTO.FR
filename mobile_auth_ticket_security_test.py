import os,tempfile,unittest
from unittest import mock
import mobile_auth_ticket
class MobileTicketSecurityTest(unittest.TestCase):
 def test_unknown_ticket_fails(self):
  with tempfile.TemporaryDirectory() as tmp,mock.patch.dict(os.environ,{"CYBERCHECK_DATA_DIR":tmp}):
   with self.assertRaises(PermissionError): mobile_auth_ticket.consume("unknown")
 def test_raw_session_is_not_the_ticket(self):
  with tempfile.TemporaryDirectory() as tmp,mock.patch.dict(os.environ,{"CYBERCHECK_DATA_DIR":tmp}):
   ticket=mobile_auth_ticket.issue("secret-session")
   self.assertNotEqual(ticket,"secret-session")
if __name__=="__main__": unittest.main()
