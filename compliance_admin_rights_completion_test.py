from __future__ import annotations

import unittest
from unittest import mock

import compliance_admin


class ComplianceAdminRightsCompletionTest(unittest.TestCase):
    def test_completion_snapshot_batches_without_dropping_requests(self):
        rows = [{"id": f"request-{index}"} for index in range(205)]

        def fake_statuses(request_ids, db_path=None):
            return [
                {
                    "requestId": request_id,
                    "requestType": "access",
                    "requestStatus": "open",
                    "coverageScope": "implemented_adapters",
                    "knownAdapters": [],
                    "planComplete": False,
                    "knownScopeComplete": False,
                    "globalCoverageComplete": False,
                    "closureReady": False,
                    "requestComplete": False,
                    "rawJustificationPersisted": False,
                    "items": [],
                }
                for request_id in request_ids
            ]

        with mock.patch(
            "compliance_admin.rights_completion_admin.statuses",
            side_effect=fake_statuses,
        ) as statuses, mock.patch(
            "compliance_admin.rights_completion_admin.capability",
            return_value={
                "configureReady": True,
                "statusReady": True,
                "bulkStatusLimit": 200,
                "closureMutationExposed": False,
                "coverageScope": "implemented_adapters",
                "globalCoverageComplete": False,
                "rawJustificationPersisted": False,
            },
        ):
            result = compliance_admin.rights_completion_snapshot(rows, "db")

        self.assertEqual(statuses.call_count, 2)
        self.assertEqual(len(statuses.call_args_list[0].args[0]), 200)
        self.assertEqual(len(statuses.call_args_list[1].args[0]), 5)
        self.assertEqual(result["requestCount"], 205)
        self.assertEqual(len(result["plans"]), 205)
        self.assertEqual(result["plans"][0]["requestId"], "request-0")
        self.assertEqual(result["plans"][-1]["requestId"], "request-204")
        self.assertFalse(result["capability"]["closureMutationExposed"])
        self.assertFalse(result["capability"]["globalCoverageComplete"])

    def test_completion_snapshot_ignores_invalid_and_duplicate_rows(self):
        rows = [
            {"id": "request-1"},
            {"id": "request-1"},
            {"id": ""},
            {},
            None,
            {"id": "request-2"},
        ]
        with mock.patch(
            "compliance_admin.rights_completion_admin.statuses",
            return_value=[],
        ) as statuses, mock.patch(
            "compliance_admin.rights_completion_admin.capability",
            return_value={"globalCoverageComplete": False},
        ):
            result = compliance_admin.rights_completion_snapshot(rows)

        statuses.assert_called_once_with(["request-1", "request-2"], None)
        self.assertEqual(result["requestCount"], 2)

    def test_completion_snapshot_keeps_global_coverage_fail_closed(self):
        with mock.patch(
            "compliance_admin.rights_completion_admin.statuses",
            return_value=[],
        ), mock.patch(
            "compliance_admin.rights_completion_admin.capability",
            return_value={
                "globalCoverageComplete": False,
                "closureMutationExposed": False,
            },
        ):
            result = compliance_admin.rights_completion_snapshot([])

        self.assertFalse(result["capability"]["globalCoverageComplete"])
        self.assertFalse(result["capability"]["closureMutationExposed"])
        self.assertEqual(result["requestCount"], 0)
        self.assertEqual(result["plans"], [])


if __name__ == "__main__":
    unittest.main()
