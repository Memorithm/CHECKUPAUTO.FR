import unittest
from mercure_booking_write_schema import (
    VL_REQUIRED,audit_fields,MercureWriteSchemaError,
)


class MercureWriteSchemaTests(unittest.TestCase):
    def test_vl_schema_observed_but_write_not_qualified(self):
        result=audit_fields(vehicle_class="vl",observed=VL_REQUIRED)
        self.assertTrue(result["schemaObserved"])
        self.assertFalse(result["customerWriteQualified"])

    def test_heavy_vehicle_class_is_explicitly_out_of_scope(self):
        with self.assertRaisesRegex(MercureWriteSchemaError,"mercure_vehicle_class_invalid"):
            audit_fields(vehicle_class="pl",observed=VL_REQUIRED)

    def test_invalid_class_rejected(self):
        with self.assertRaises(MercureWriteSchemaError):
            audit_fields(vehicle_class="unknown",observed=VL_REQUIRED)


if __name__=="__main__":
    unittest.main()
