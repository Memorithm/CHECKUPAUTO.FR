from __future__ import annotations

import json
import unittest
from unittest import mock

import rights_completion_admin
import rights_completion_admin_http


SAMPLE_STATE = {
    "requestId": "request-1",
    "requestType": "access",
    "requestStatus": "open",
    "coverageScope": "implemented_adapters",
    "knownAdapters": ["mobile_installation", "referral_wallet"],
    "planComplete": True,
    "knownScopeComplete": False,
    "globalCoverageComplete": False,
    "closureReady": False,
    "requestComplete": False,
    "rawJustificationPersisted": False,
    "items": [
        {
            "adapter": "mobile_installation",
            "disposition": "required",
            "executed": True,
            "executionComplete": True,
            "executionLimitation": "",
            "satisfied": True,
            "justificationHash": "",
            "updatedAt": "2026-09-23T00:00:00+00:00",
            "rawJustification": "MUST-NOT-LEAK",
        },
        {
            "adapter": "referral_wallet",
            "disposition": "required",
            "executed": True,
            "executionComplete": False,
            "executionLimitation": "bounded_wallet_or_retained_erasure",
            "satisfied": False,
            "justificationHash": "",
            "updatedAt": "2026-09-23T00:00:00+00:00",
        },
    ],
    "unexpectedSubjectReference": "MUST-NOT-LEAK",
}


class RightsCompletionAdminTest(unittest.TestCase):
    def test_configure_is_exact_and_does_not_reflect_raw_justification(self):
        raw = "aucune cagnotte rattachée à cette demande"
        payload = {
            "id": "request-1",
            "entries": [
                {"adapter": "mobile_installation", "disposition": "required"},
                {
                    "adapter": "referral_wallet",
                    "disposition": "not_applicable",
                    "justification": raw,
                },
            ],
        }
        with mock.patch(
            "rights_completion_admin.rights_completion_plan.configure",
            return_value=SAMPLE_STATE,
        ) as configure:
            result = rights_completion_admin.configure(payload)

        configure.assert_called_once_with("request-1", payload["entries"], None)
        encoded = json.dumps(result, ensure_ascii=False)
        self.assertNotIn(raw, encoded)
        self.assertNotIn("MUST-NOT-LEAK", encoded)
        self.assertFalse(result["globalCoverageComplete"])
        self.assertFalse(result["closureReady"])
        self.assertTrue(result["items"][0]["executionComplete"])
        self.assertEqual(
            result["items"][1]["executionLimitation"],
            "bounded_wallet_or_retained_erasure",
        )
        self.assertFalse(result["items"][1]["satisfied"])

    def test_configure_rejects_missing_or_extra_fields_before_core(self):
        for payload in (
            {"id": "request-1"},
            {"id": "request-1", "entries": [], "close": True},
            {"id": "", "entries": []},
            {"id": "request-1", "entries": {}},
        ):
            with self.subTest(payload=payload):
                with mock.patch(
                    "rights_completion_admin.rights_completion_plan.configure"
                ) as configure:
                    with self.assertRaises(ValueError):
                        rights_completion_admin.configure(payload)
                    configure.assert_not_called()

    def test_statuses_rejects_duplicates_and_unbounded_lists(self):
        with self.assertRaises(ValueError):
            rights_completion_admin.statuses(["request-1", "request-1"])
        with self.assertRaises(ValueError):
            rights_completion_admin.statuses(
                [f"request-{index}" for index in range(rights_completion_admin.MAX_REQUESTS + 1)]
            )

    def test_statuses_returns_bounded_rows_without_exposing_close_mutation(self):
        with mock.patch(
            "rights_completion_admin.rights_completion_plan.status",
            return_value=SAMPLE_STATE,
        ) as status:
            rows = rights_completion_admin.statuses(["request-1", "request-2"])
        self.assertEqual(status.call_count, 2)
        self.assertEqual([row["requestId"] for row in rows], ["request-1", "request-1"])
        capability = rights_completion_admin.capability()
        self.assertTrue(capability["configureReady"])
        self.assertFalse(capability["closureMutationExposed"])
        self.assertFalse(capability["globalCoverageComplete"])
        self.assertTrue(capability["partialExecutionDoesNotSatisfyRequiredPlan"])

    def test_http_adapter_maps_conflicts_and_sanitizes_internal_errors(self):
        with mock.patch(
            "rights_completion_admin_http.rights_completion_admin.configure",
            side_effect=RuntimeError("RAW-INTERNAL-CONFLICT"),
        ):
            status, body = rights_completion_admin_http.configure({"id": "request-1", "entries": []})
        self.assertEqual(status, 409)
        self.assertEqual(body, {"ok": False, "error": "compliance_completion_plan_conflict"})
        self.assertNotIn("RAW-INTERNAL-CONFLICT", json.dumps(body))

        with mock.patch(
            "rights_completion_admin_http.rights_completion_admin.configure",
            side_effect=Exception("RAW-INTERNAL-SECRET"),
        ):
            status, body = rights_completion_admin_http.configure({"id": "request-1", "entries": []})
        self.assertEqual(status, 500)
        self.assertEqual(body, {"ok": False, "error": "compliance_completion_plan_unavailable"})
        self.assertNotIn("RAW-INTERNAL-SECRET", json.dumps(body))

    def test_http_status_maps_not_found_without_details(self):
        with mock.patch(
            "rights_completion_admin_http.rights_completion_admin.status",
            side_effect=LookupError("subject reference must not leak"),
        ):
            status, body = rights_completion_admin_http.status("request-1")
        self.assertEqual(status, 404)
        self.assertEqual(body, {"ok": False, "error": "compliance_request_not_found"})
        self.assertNotIn("subject reference", json.dumps(body))


if __name__ == "__main__":
    unittest.main()
