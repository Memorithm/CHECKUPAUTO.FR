from __future__ import annotations

import unittest
from unittest import mock

import mobile_authoritative_sync
import mobile_claim_dispatch


INSTALLATION = "11111111-1111-1111-1111-111111111111"
VEHICLE_CLAIM = "vc_" + "a" * 40


class MobilePrivacyRepopulationGuardTest(unittest.TestCase):
    def test_shared_claim_boundary_rejects_all_processing_before_claim_mutation(self):
        payload = {
            "installationId": INSTALLATION,
            "registrationSecret": "s" * 32,
            "claimToken": VEHICLE_CLAIM,
        }
        with mock.patch.object(
            mobile_claim_dispatch.privacy, "is_suppressed", return_value=True
        ) as suppressed, mock.patch.object(
            mobile_claim_dispatch.mobile_devices, "consume_vehicle_claim"
        ) as consume_vehicle, mock.patch.object(
            mobile_claim_dispatch.referral_wallet_claims, "consume"
        ) as consume_wallet:
            with self.assertRaisesRegex(PermissionError, "traitement mobile refusé"):
                mobile_claim_dispatch.consume(payload)

        suppressed.assert_called_once_with(
            "installation", INSTALLATION, "all_processing"
        )
        consume_vehicle.assert_not_called()
        consume_wallet.assert_not_called()

    def test_unsuppressed_shared_claim_boundary_still_routes_vehicle_claim(self):
        payload = {
            "installationId": INSTALLATION,
            "registrationSecret": "s" * 32,
            "claimToken": VEHICLE_CLAIM,
        }
        with mock.patch.object(
            mobile_claim_dispatch.privacy, "is_suppressed", return_value=False
        ), mock.patch.object(
            mobile_claim_dispatch.mobile_devices,
            "consume_vehicle_claim",
            return_value={
                "ok": True,
                "bindingId": "binding-1",
                "claimedAt": "2026-09-23T00:00:00+00:00",
            },
        ) as consume_vehicle:
            result = mobile_claim_dispatch.consume(payload)

        self.assertTrue(result["ok"])
        self.assertEqual(result["claimType"], "vehicle")
        self.assertEqual(result["bindingId"], "binding-1")
        consume_vehicle.assert_called_once_with(payload)

    def test_authoritative_sync_stops_before_binding_or_mercure_lookup(self):
        with mock.patch.object(
            mobile_authoritative_sync.privacy, "is_suppressed", return_value=True
        ) as suppressed, mock.patch.object(
            mobile_authoritative_sync.mobile_devices, "registered_vehicle_bindings"
        ) as bindings, mock.patch.object(
            mobile_authoritative_sync.reminder_dispatch, "deadlines_for_vehicle_ids"
        ) as deadlines, mock.patch.object(
            mobile_authoritative_sync.mobile_devices, "sync_authoritative_deadlines"
        ) as write_deadlines:
            result = mobile_authoritative_sync.sync_installation(INSTALLATION)

        self.assertTrue(result["ok"])
        self.assertTrue(result["privacySuppressed"])
        self.assertEqual(result["authoritativeDeadlines"], 0)
        suppressed.assert_called_once_with(
            "installation", INSTALLATION, "all_processing"
        )
        bindings.assert_not_called()
        deadlines.assert_not_called()
        write_deadlines.assert_not_called()

    def test_background_sync_counts_privacy_suppression_without_failure(self):
        with mock.patch.object(
            mobile_authoritative_sync.mobile_devices,
            "registered_vehicle_bindings",
            return_value=[{"installation_id": INSTALLATION}],
        ), mock.patch.object(
            mobile_authoritative_sync,
            "sync_installation",
            return_value={
                "ok": True,
                "installationId": INSTALLATION,
                "bindings": 0,
                "authoritativeDeadlines": 0,
                "privacySuppressed": True,
            },
        ):
            result = mobile_authoritative_sync.sync_once()

        self.assertTrue(result["ok"])
        self.assertEqual(result["installations"], 1)
        self.assertEqual(result["synced"], 0)
        self.assertEqual(result["privacySuppressed"], 1)
        self.assertEqual(result["failed"], 0)


if __name__ == "__main__":
    unittest.main()
