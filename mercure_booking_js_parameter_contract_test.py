import unittest

from mercure_booking_write_form_contract import REQUIRED_FIELDS
from mercure_booking_js_parameter_contract import qualify_observation,MercureJavascriptContractError


class MercureJavascriptContractTests(unittest.TestCase):
    def test_observed_javascript_parameter_remains_read_only(self):
        js='''function addRendezVous(tcheckDispo = true) {
        $.ajax({url: "rendez_vous_add", data: {'tcheckDispo' : tcheckDispo}})}'''
        result=qualify_observation(html_fields=REQUIRED_FIELDS,javascript_source=js)
        self.assertTrue(result["htmlContractObserved"])
        self.assertTrue(result["javascriptParameterObserved"])
        self.assertFalse(result["customerWriteQualified"])
        self.assertFalse(result["productionWriteEnabled"])

    def test_missing_javascript_parameter_is_not_qualified(self):
        result=qualify_observation(html_fields=REQUIRED_FIELDS,javascript_source="function addRendezVous() {}")
        self.assertFalse(result["javascriptParameterObserved"])

    def test_invalid_source_rejected(self):
        with self.assertRaises(MercureJavascriptContractError):
            qualify_observation(html_fields=REQUIRED_FIELDS,javascript_source=None)


if __name__=="__main__":
    unittest.main()
