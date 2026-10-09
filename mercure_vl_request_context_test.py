import unittest
from unittest.mock import patch
import mercure_vl_request_context as context

class Tests(unittest.TestCase):
    def setUp(self):
        self.metadata=dict(service_id="1",duration="40",centre_type="1",line_id="2",operator_id="3")

    def test_binds_assembled_customer_to_provider_payload(self):
        assembled={"appointment":{"nom":"Test"}}
        with patch.object(context,"assemble",return_value=assembled),patch.object(context,"build",return_value={"ok":True}) as builder:
            result=context.prepare(request=object(),account={},vehicle={},metadata=self.metadata)
        self.assertEqual(result["payload"],{"ok":True})
        self.assertFalse(result["providerWritePerformed"])
        builder.assert_called_once_with(appointment=assembled["appointment"],**self.metadata)

    def test_missing_metadata_rejected(self):
        with patch.object(context,"assemble",return_value={"appointment":{}}),patch.object(context,"build") as builder:
            with self.assertRaises(ValueError):
                context.prepare(request=object(),account={},vehicle={},metadata={})
            builder.assert_not_called()
