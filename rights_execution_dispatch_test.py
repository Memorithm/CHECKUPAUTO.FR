from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import rights_execution_dispatch


class RightsExecutionDispatchTest(unittest.TestCase):
    def test_routes_existing_central_adapter_without_extra_fields(self):
        expected = {"ok": True, "adapter": "mobile_installation"}
        with mock.patch.object(
            rights_execution_dispatch.data_subject_rights,
            "execute",
            return_value=expected,
        ) as execute, mock.patch.object(
            rights_execution_dispatch.data_subject_rights,
            "_request",
            return_value={"request_type": "access"},
        ):
            result = rights_execution_dispatch.execute(
                {
                    "id": "a" * 32,
                    "subjectRef": "11111111-1111-1111-1111-111111111111",
                    "adapter": "mobile_installation",
                },
                Path("/tmp/compliance.sqlite3"),
            )

        self.assertEqual(result, expected)
        execute.assert_called_once_with(
            "a" * 32,
            "11111111-1111-1111-1111-111111111111",
            adapter="mobile_installation",
            purpose="",
            db_path=Path("/tmp/compliance.sqlite3"),
        )

    def test_routes_mobile_erasure_through_crash_recoverable_boundary(self):
        expected = {"ok": True, "adapter": "mobile_installation", "recoveredFromReceipt": False}
        with mock.patch.object(
            rights_execution_dispatch.data_subject_rights,
            "_request",
            return_value={"request_type": "erasure"},
        ), mock.patch.object(
            rights_execution_dispatch.mobile_dsar_erasure,
            "execute",
            return_value=expected,
        ) as execute:
            result = rights_execution_dispatch.execute(
                {
                    "id": "e" * 32,
                    "subjectRef": "11111111-1111-1111-1111-111111111111",
                    "adapter": "mobile_installation",
                },
                Path("/tmp/compliance.sqlite3"),
            )

        self.assertEqual(result, expected)
        execute.assert_called_once_with(
            "e" * 32,
            "11111111-1111-1111-1111-111111111111",
            Path("/tmp/compliance.sqlite3"),
        )

    def test_privacy_suppression_accepts_bounded_purpose(self):
        with mock.patch.object(
            rights_execution_dispatch.data_subject_rights,
            "execute",
            return_value={"ok": True},
        ) as execute:
            rights_execution_dispatch.execute(
                {
                    "id": "b" * 32,
                    "subjectRef": "client@example.test",
                    "adapter": "privacy_suppression",
                    "purpose": "direct_marketing_email",
                }
            )

        self.assertEqual(execute.call_args.kwargs["purpose"], "direct_marketing_email")

    def test_routes_bounded_rectification_with_exact_correction_object(self):
        correction = {
            "deadlineId": "22222222-2222-2222-2222-222222222222",
            "dueDate": "2027-05-10",
        }
        expected = {"ok": True, "adapter": "mobile_deadline_rectification"}
        with mock.patch.object(
            rights_execution_dispatch.rights_rectification,
            "execute",
            return_value=expected,
        ) as execute:
            result = rights_execution_dispatch.execute(
                {
                    "id": "c" * 32,
                    "subjectRef": "33333333-3333-3333-3333-333333333333",
                    "adapter": "mobile_deadline_rectification",
                    "correction": correction,
                },
                Path("/tmp/compliance.sqlite3"),
            )

        self.assertEqual(result, expected)
        execute.assert_called_once_with(
            "c" * 32,
            "33333333-3333-3333-3333-333333333333",
            correction,
            Path("/tmp/compliance.sqlite3"),
        )

    def test_routes_referral_wallet_with_explicit_account_id(self):
        account = "44444444-4444-4444-4444-444444444444"
        expected = {"ok": True, "adapter": "referral_wallet"}
        with mock.patch.object(
            rights_execution_dispatch.referral_wallet_rights,
            "execute",
            return_value=expected,
        ) as execute:
            result = rights_execution_dispatch.execute(
                {
                    "id": "d" * 32,
                    "subjectRef": "55555555-5555-5555-5555-555555555555",
                    "adapter": "referral_wallet",
                    "accountId": account,
                }
            )

        self.assertEqual(result, expected)
        execute.assert_called_once_with(
            "d" * 32,
            "55555555-5555-5555-5555-555555555555",
            account,
            None,
        )

    def test_rejects_unknown_or_overbroad_payloads_before_delegation(self):
        invalid = [
            None,
            {"id": "a" * 32, "subjectRef": "x", "adapter": "unknown"},
            {
                "id": "a" * 32,
                "subjectRef": "x",
                "adapter": "mobile_installation",
                "accountId": "should-not-be-accepted",
            },
            {
                "id": "a" * 32,
                "subjectRef": "x",
                "adapter": "mobile_deadline_rectification",
            },
            {
                "id": "a" * 32,
                "subjectRef": "x",
                "adapter": "referral_wallet",
                "accountId": "y",
                "purpose": "unexpected",
            },
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    rights_execution_dispatch.execute(payload)

    def test_capability_is_explicitly_partial(self):
        with mock.patch.object(
            rights_execution_dispatch.rights_rectification,
            "capability",
            return_value={
                "bound": False,
                "partial": True,
                "adapter": "mobile_deadline_rectification",
                "requestType": "rectification",
            },
        ), mock.patch.object(
            rights_execution_dispatch.referral_wallet_rights,
            "capability",
            return_value={
                "bound": True,
                "partial": True,
                "adapter": "referral_wallet",
                "supportedRights": ["access", "portability"],
            },
        ):
            state = rights_execution_dispatch.capability()

        self.assertTrue(state["dispatchReady"])
        self.assertFalse(state["globalCoverageComplete"])
        self.assertEqual(
            state["supportedAdapters"]["mobile_deadline_rectification"],
            ["rectification"],
        )
        self.assertEqual(
            state["supportedAdapters"]["referral_wallet"],
            ["access", "portability"],
        )
        self.assertFalse(state["rawPayloadPersistedByDispatcher"])


if __name__ == "__main__":
    unittest.main()
