from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import rights_execution_dispatch


class RightsContractDispatchTest(unittest.TestCase):
    def test_contract_adapter_uses_subject_wide_executor_with_exact_payload(self):
        expected = {"ok": True, "adapter": "compliance_contracts"}
        db = Path("/tmp/compliance.sqlite3")
        with mock.patch.object(
            rights_execution_dispatch.contract_subject_rights,
            "execute",
            return_value=expected,
        ) as execute:
            result = rights_execution_dispatch.execute(
                {
                    "id": "a" * 32,
                    "subjectRef": "account:42",
                    "adapter": "compliance_contracts",
                },
                db,
            )

        self.assertEqual(result, expected)
        execute.assert_called_once_with("a" * 32, "account:42", db)

    def test_contract_adapter_rejects_overbroad_payload_before_execution(self):
        with mock.patch.object(
            rights_execution_dispatch.contract_subject_rights,
            "execute",
        ) as execute:
            with self.assertRaises(ValueError):
                rights_execution_dispatch.execute(
                    {
                        "id": "a" * 32,
                        "subjectRef": "account:42",
                        "adapter": "compliance_contracts",
                        "purpose": "unexpected",
                    }
                )
        execute.assert_not_called()

    def test_dispatch_capability_surfaces_subject_wide_contract_executor(self):
        expected = {
            "adapter": "compliance_contracts",
            "supportedRights": ["access", "portability"],
            "subjectWideExportReady": True,
        }
        with mock.patch.object(
            rights_execution_dispatch.contract_subject_rights,
            "capability",
            return_value=expected,
        ):
            state = rights_execution_dispatch.capability()
        self.assertEqual(state["contractSubject"], expected)
        self.assertFalse(state["globalCoverageComplete"])


if __name__ == "__main__":
    unittest.main()
