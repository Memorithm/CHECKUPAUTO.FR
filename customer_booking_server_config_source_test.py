import unittest
from customer_booking_server_config_source import load,BookingServerConfigError

class Tests(unittest.TestCase):
    def test_default_disabled(self):
        self.assertFalse(load(environ={})["enabled"])

    def test_disabled_ignores_untrusted_ids(self):
        self.assertEqual(load(environ={"CHECKUPAUTO_MERCURE_VL_LINE_ID":"bad"}),
                         {"enabled":False,"lineId":"","operatorId":""})

    def test_enabled_requires_numeric_ids(self):
        with self.assertRaises(BookingServerConfigError):
            load(environ={"CHECKUPAUTO_MERCURE_CUSTOMER_WRITE_ENABLED":"true"})

    def test_explicit_qualified_config(self):
        self.assertEqual(load(environ={
            "CHECKUPAUTO_MERCURE_CUSTOMER_WRITE_ENABLED":"true",
            "CHECKUPAUTO_MERCURE_VL_LINE_ID":"454",
            "CHECKUPAUTO_MERCURE_VL_OPERATOR_ID":"464"}),
            {"enabled":True,"lineId":"454","operatorId":"464"})
