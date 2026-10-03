import os
import tempfile
import unittest
from unittest import mock
import mobile_auth_ticket

class MobileAuthTicketTest(unittest.TestCase):
    def test_ticket_is_single_use(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ,{"CYBERCHECK_DATA_DIR":tmp}):
            ticket=mobile_auth_ticket.issue("opaque-session")
            self.assertEqual(mobile_auth_ticket.consume(ticket),"opaque-session")
            with self.assertRaises(PermissionError):
                mobile_auth_ticket.consume(ticket)

if __name__=="__main__":
    unittest.main()
