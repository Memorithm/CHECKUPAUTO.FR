import unittest
from dataclasses import replace

from mercure_legacy_gateway_contract import CentreGatewayEvidence, REQUIRED, qualification


class LegacyGatewayQualificationTest(unittest.TestCase):
    def test_current_unqualified_state_refuses_live_writes(self):
        result=qualification(CentreGatewayEvidence())
        self.assertFalse(result["qualified"])
        self.assertFalse(result["realBookingEnabled"])
        self.assertFalse(result["legacyDatabaseDirectWriteAllowed"])
        self.assertFalse(result["syntheticWriterAllowedForCustomers"])
        self.assertEqual(set(result["missing"]),set(REQUIRED))

    def test_each_independent_gate_is_mandatory(self):
        full=CentreGatewayEvidence(**{field:True for field in REQUIRED})
        self.assertTrue(qualification(full)["qualified"])
        self.assertFalse(qualification(full)["realBookingEnabled"])
        for field in REQUIRED:
            with self.subTest(field=field):
                partial=replace(full,**{field:False})
                self.assertIn(field,qualification(partial)["missing"])
                self.assertFalse(qualification(partial)["qualified"])

    def test_truthy_strings_do_not_qualify_gateway(self):
        partial=CentreGatewayEvidence(**{field:"true" for field in REQUIRED})
        self.assertFalse(qualification(partial)["qualified"])


if __name__=="__main__":
    unittest.main()
