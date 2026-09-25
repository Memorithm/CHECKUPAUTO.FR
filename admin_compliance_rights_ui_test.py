from pathlib import Path
import unittest


class AdminComplianceRightsUIContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("admin/index.html").read_text(encoding="utf-8")
        cls.js = Path("admin/compliance.js").read_text(encoding="utf-8")

    def test_all_dispatcher_adapters_are_operable_from_console(self):
        for adapter in (
            "mobile_installation",
            "mercure_customer_contact",
            "compliance_contracts",
            "privacy_suppression",
            "mobile_deadline_rectification",
            "referral_wallet",
        ):
            self.assertIn(f'value="{adapter}"', self.html)

    def test_typed_inputs_exist_for_partial_adapters(self):
        for element_id in (
            "complianceRightAccountId",
            "complianceRightDeadlineId",
            "complianceRightDueDate",
            "complianceRightPurposeWrap",
            "complianceRightWalletWrap",
            "complianceRightRectificationWrap",
        ):
            self.assertIn(f'id="{element_id}"', self.html)

    def test_executor_builds_exact_adapter_specific_payloads(self):
        self.assertIn("function rightsExecutionPayload(requestId)", self.js)
        self.assertIn("payload.purpose=$('#complianceRightPurpose').value", self.js)
        self.assertIn("payload.accountId=$('#complianceRightAccountId').value", self.js)
        self.assertIn("payload.correction={deadlineId:$('#complianceRightDeadlineId').value,dueDate:$('#complianceRightDueDate').value}", self.js)
        self.assertIn("await api('/api/admin/compliance/request-execute',rightsExecutionPayload(b.dataset.id))", self.js)

    def test_provider_erasure_evidence_is_rendered_without_raw_appointments(self):
        self.assertIn("function providerErasureText(requestId)", self.js)
        self.assertIn("PLAN CHIFFRÉ EN ATTENTE", self.js)
        self.assertIn("Effacement provider : PROUVÉ", self.js)
        self.assertIn("providerState", self.js)
        self.assertNotIn("appointmentIds", self.js)

    def test_legacy_generic_payload_no_longer_sends_purpose_to_every_adapter(self):
        self.assertNotIn("adapter:$('#complianceRightAdapter').value,\n    subjectRef:$('#complianceRightExecutionRef').value,\n    purpose:$('#complianceRightPurpose').value", self.js)


if __name__ == "__main__":
    unittest.main()
