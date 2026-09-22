from __future__ import annotations

import io
import json
import unittest
from unittest import mock

import data_subject_rights_cli as cli


class DataSubjectRightsCliTest(unittest.TestCase):
    def test_prove_contract_reads_sensitive_refs_only_from_stdin_and_redacts_output(self):
        payload = {
            "requestId": "a" * 32,
            "installationId": "11111111-1111-4111-8111-111111111111",
            "mercureSubjectRef": "account:customer-secret",
            "contractRef": "appointment-secret",
        }
        output = io.StringIO()
        with mock.patch.object(
            cli.data_subject_rights,
            "bind_mercure_from_mobile",
            return_value={
                "bound": True,
                "adapter": "mercure_customer_contact",
                "provenance": "mobile_vehicle_binding",
                "bindingCount": 1,
                "rawSubjectReferencePersisted": False,
                "unexpectedRawValue": payload["mercureSubjectRef"],
            },
        ) as bind_mercure, mock.patch.object(
            cli.rights_subject_bindings,
            "bind_contract_from_mercure",
            return_value={
                "bound": True,
                "adapter": "compliance_contracts",
                "provenance": "mercure_appointment",
                "appointmentMatchCount": 1,
                "checkoutAcceptanceCount": 1,
                "rawSubjectReferencePersisted": False,
                "unexpectedRawValue": payload["contractRef"],
            },
        ) as bind_contract:
            code = cli.main(
                ["prove-contract"],
                stdin=io.StringIO(json.dumps(payload)),
                stdout=output,
            )

        self.assertEqual(code, 0)
        bind_mercure.assert_called_once_with(
            payload["requestId"],
            payload["installationId"],
            payload["mercureSubjectRef"],
        )
        bind_contract.assert_called_once_with(
            payload["requestId"],
            payload["mercureSubjectRef"],
            payload["contractRef"],
        )
        text = output.getvalue()
        self.assertNotIn(payload["installationId"], text)
        self.assertNotIn(payload["mercureSubjectRef"], text)
        self.assertNotIn(payload["contractRef"], text)
        response = json.loads(text)
        self.assertTrue(response["ok"])
        self.assertFalse(response["proof"]["mercure"]["rawSubjectReferencePersisted"])
        self.assertFalse(response["proof"]["contract"]["rawSubjectReferencePersisted"])

    def test_raw_identifiers_cannot_be_supplied_as_process_arguments(self):
        output = io.StringIO()
        with mock.patch.object(cli, "_prove_contract") as prove:
            code = cli.main(
                ["prove-contract", "account:secret"],
                stdin=io.StringIO("{}"),
                stdout=output,
            )
        self.assertEqual(code, 2)
        prove.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["error"], "usage")

    def test_provider_error_does_not_leak_sensitive_reference(self):
        secret = "account:provider-secret"
        payload = {
            "requestId": "b" * 32,
            "installationId": "22222222-2222-4222-8222-222222222222",
            "mercureSubjectRef": secret,
            "contractRef": "appointment-provider-secret",
        }
        output = io.StringIO()
        with mock.patch.object(
            cli.data_subject_rights,
            "bind_mercure_from_mobile",
            side_effect=RuntimeError(f"provider failure for {secret}"),
        ):
            code = cli.main(
                ["prove-contract"],
                stdin=io.StringIO(json.dumps(payload)),
                stdout=output,
            )
        self.assertEqual(code, 2)
        self.assertNotIn(secret, output.getvalue())
        self.assertEqual(
            json.loads(output.getvalue()),
            {"error": "invalid_or_unauthorized_request", "ok": False},
        )

    def test_prove_contract_fails_closed_without_explicit_privacy_evidence(self):
        payload = {
            "requestId": "e" * 32,
            "installationId": "33333333-3333-4333-8333-333333333333",
            "mercureSubjectRef": "account:customer-private",
            "contractRef": "appointment-private",
        }
        output = io.StringIO()
        with mock.patch.object(
            cli.data_subject_rights,
            "bind_mercure_from_mobile",
            return_value={
                "bound": True,
                "adapter": "mercure_customer_contact",
                "provenance": "mobile_vehicle_binding",
                "bindingCount": 1,
                "rawSubjectReferencePersisted": False,
            },
        ), mock.patch.object(
            cli.rights_subject_bindings,
            "bind_contract_from_mercure",
            return_value={
                "bound": True,
                "adapter": "compliance_contracts",
                "provenance": "mercure_appointment",
                "appointmentMatchCount": 1,
                "checkoutAcceptanceCount": 1,
            },
        ):
            code = cli.main(
                ["prove-contract"],
                stdin=io.StringIO(json.dumps(payload)),
                stdout=output,
            )
        self.assertEqual(code, 2)
        self.assertEqual(
            json.loads(output.getvalue()),
            {"error": "invalid_or_unauthorized_request", "ok": False},
        )

    def test_oversized_stdin_is_rejected_before_proof_calls(self):
        output = io.StringIO()
        oversized = '{"padding":"' + ("x" * cli.MAX_STDIN_BYTES) + '"}'
        with mock.patch.object(cli, "_prove_contract") as prove:
            code = cli.main(
                ["prove-contract"],
                stdin=io.StringIO(oversized),
                stdout=output,
            )
        self.assertEqual(code, 2)
        prove.assert_not_called()
        self.assertEqual(
            json.loads(output.getvalue())["error"],
            "invalid_or_unauthorized_request",
        )

    def test_bindings_projection_drops_unknown_fields(self):
        output = io.StringIO()
        with mock.patch.object(
            cli.rights_subject_bindings,
            "rows",
            return_value=[{
                "requestId": "c" * 32,
                "adapter": "compliance_contracts",
                "provenance": "mercure_appointment",
                "evidenceHash": "d" * 64,
                "createdAt": "2026-09-22T01:00:00+00:00",
                "subjectRef": "must-not-leak",
            }],
        ):
            code = cli.main(["bindings"], stdout=output)
        self.assertEqual(code, 0)
        self.assertNotIn("must-not-leak", output.getvalue())
        row = json.loads(output.getvalue())["bindings"][0]
        self.assertEqual(
            set(row),
            {"requestId", "adapter", "provenance", "evidenceHash", "createdAt"},
        )


if __name__ == "__main__":
    unittest.main()
