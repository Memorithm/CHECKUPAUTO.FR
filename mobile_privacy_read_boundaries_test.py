from __future__ import annotations

import unittest
from unittest import mock

import mobile_authoritative_sync as authoritative
import mobile_claim_delivery as claims


class MobilePrivacyReadBoundariesTest(unittest.TestCase):
    def test_claim_candidates_filter_cached_subject_after_all_processing_suppression(self):
        rows = [
            {
                "vehicle_id": "vehicle-suppressed",
                "due_date": "2026-10-01",
                "appointment_id": "rdv-suppressed",
                "last_seen_at": "2026-09-23T10:00:00+00:00",
            },
            {
                "vehicle_id": "vehicle-visible",
                "due_date": "2026-10-02",
                "appointment_id": "rdv-visible",
                "last_seen_at": "2026-09-23T09:00:00+00:00",
            },
        ]
        targets = {
            "vehicle-suppressed": {
                "vehicle_id": "vehicle-suppressed",
                "client_kind": "account",
                "client_id": "42",
                "due_date": "2026-10-01",
            },
            "vehicle-visible": {
                "vehicle_id": "vehicle-visible",
                "client_kind": "free",
                "client_id": "84",
                "due_date": "2026-10-02",
            },
        }

        def suppressed(candidates, purpose):
            self.assertEqual(purpose, "all_processing")
            return ("vehicle", "vehicle-suppressed") in candidates

        with mock.patch.object(claims.reminder_dispatch, "mobile_claim_candidates", return_value=rows), \
             mock.patch.object(
                 claims.reminder_dispatch,
                 "mobile_claim_target",
                 side_effect=lambda vehicle_id: targets[vehicle_id],
             ), \
             mock.patch.object(claims.privacy, "any_suppressed", side_effect=suppressed):
            result = claims.candidates(30)

        self.assertEqual(result, [{
            "vehicleId": "vehicle-visible",
            "dueDate": "2026-10-02",
            "appointmentId": "rdv-visible",
            "lastSeenAt": "2026-09-23T09:00:00+00:00",
        }])

    def test_suppressed_target_cannot_issue_mobile_claim(self):
        target = {
            "vehicle_id": "vehicle-suppressed",
            "client_kind": "account",
            "client_id": "42",
            "due_date": "2026-10-01",
        }
        with mock.patch.object(claims, "status", return_value={"ready": True}), \
             mock.patch.object(claims.reminder_dispatch, "mobile_claim_target", return_value=target), \
             mock.patch.object(claims.privacy, "any_suppressed", return_value=True) as suppressed, \
             mock.patch.object(claims.mobile_devices, "issue_vehicle_claim") as issue:
            with self.assertRaisesRegex(LookupError, "inventaire Mercure"):
                claims.issue_for_vehicle({}, "vehicle-suppressed")

        issue.assert_not_called()
        candidates, purpose = suppressed.call_args.args
        self.assertEqual(purpose, "all_processing")
        self.assertIn(("vehicle", "vehicle-suppressed"), candidates)
        self.assertIn(("mercure_account", "42"), candidates)

    def test_authoritative_sync_excludes_suppressed_binding_and_removes_stale_deadline(self):
        bindings = [
            {
                "binding_id": "binding-suppressed",
                "installation_id": "11111111-1111-4111-8111-111111111111",
                "vehicle_id": "vehicle-suppressed",
                "client_kind": "account",
                "client_id": "42",
            },
            {
                "binding_id": "binding-visible",
                "installation_id": "11111111-1111-4111-8111-111111111111",
                "vehicle_id": "vehicle-visible",
                "client_kind": "free",
                "client_id": "84",
            },
        ]

        def suppressed(candidates, purpose):
            self.assertEqual(purpose, "all_processing")
            return ("vehicle", "vehicle-suppressed") in candidates

        with mock.patch.object(authoritative.mobile_devices, "_install_id", return_value=bindings[0]["installation_id"]), \
             mock.patch.object(authoritative.privacy, "is_suppressed", return_value=False), \
             mock.patch.object(authoritative.mobile_devices, "registered_vehicle_bindings", return_value=bindings), \
             mock.patch.object(authoritative.privacy, "any_suppressed", side_effect=suppressed), \
             mock.patch.object(
                 authoritative.reminder_dispatch,
                 "deadlines_for_vehicle_ids",
                 return_value=[{"vehicle_id": "vehicle-visible", "due_date": "2026-10-02"}],
             ) as inventory, \
             mock.patch.object(
                 authoritative.mobile_devices,
                 "sync_authoritative_deadlines",
                 return_value={"deadlineCount": 1},
             ) as sync:
            result = authoritative.sync_installation(bindings[0]["installation_id"])

        inventory.assert_called_once_with(["vehicle-visible"])
        sync.assert_called_once_with(
            bindings[0]["installation_id"],
            [{"deadlineId": "binding-visible", "dueDate": "2026-10-02"}],
        )
        self.assertEqual(result["suppressedBindings"], 1)
        self.assertEqual(result["authoritativeDeadlines"], 1)

    def test_all_suppressed_bindings_sync_empty_snapshot_to_clear_cached_deadlines(self):
        installation = "22222222-2222-4222-8222-222222222222"
        binding = {
            "binding_id": "binding-suppressed",
            "installation_id": installation,
            "vehicle_id": "vehicle-suppressed",
            "client_kind": "account",
            "client_id": "42",
        }
        with mock.patch.object(authoritative.mobile_devices, "_install_id", return_value=installation), \
             mock.patch.object(authoritative.privacy, "is_suppressed", return_value=False), \
             mock.patch.object(authoritative.mobile_devices, "registered_vehicle_bindings", return_value=[binding]), \
             mock.patch.object(authoritative.privacy, "any_suppressed", return_value=True), \
             mock.patch.object(
                 authoritative.reminder_dispatch,
                 "deadlines_for_vehicle_ids",
                 return_value=[],
             ) as inventory, \
             mock.patch.object(
                 authoritative.mobile_devices,
                 "sync_authoritative_deadlines",
                 return_value={"deadlineCount": 0},
             ) as sync:
            result = authoritative.sync_installation(installation)

        inventory.assert_called_once_with([])
        sync.assert_called_once_with(installation, [])
        self.assertEqual(result["suppressedBindings"], 1)
        self.assertEqual(result["authoritativeDeadlines"], 0)


if __name__ == "__main__":
    unittest.main()
