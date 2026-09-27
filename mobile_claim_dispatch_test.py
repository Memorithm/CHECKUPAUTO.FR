import unittest
from unittest import mock

import mobile_claim_dispatch as dispatch


class MobileClaimDispatchTest(unittest.TestCase):
    def setUp(self):
        self.identity = {
            "installationId": "11111111-1111-4111-8111-111111111111",
            "registrationSecret": "unit_test_registration_secret_placeholder_000000",
        }

    def test_vehicle_claim_stays_in_vehicle_trust_domain(self):
        payload = {**self.identity, "claimToken": "B" * 43}
        vehicle_result = {
            "ok": True,
            "bindingId": "22222222-2222-4222-8222-222222222222",
            "claimedAt": "2026-09-22T06:00:00+00:00",
        }
        with mock.patch.object(dispatch.mobile_devices, "consume_vehicle_claim", return_value=vehicle_result) as vehicle, \
             mock.patch.object(dispatch.referral_wallet_claims, "consume") as wallet, \
             mock.patch.object(dispatch.referral_wallet_mobile, "status") as wallet_status:
            result = dispatch.consume(payload)
        vehicle.assert_called_once_with(payload)
        wallet.assert_not_called()
        wallet_status.assert_not_called()
        self.assertEqual(result["claimType"], "vehicle")
        self.assertEqual(result["bindingId"], vehicle_result["bindingId"])

    def test_wallet_claim_uses_reserved_namespace_and_minimized_response(self):
        payload = {**self.identity, "claimToken": "rw_" + "C" * 43}
        wallet_result = {
            "ok": True,
            "accountId": "33333333-3333-4333-8333-333333333333",
            "claimType": "referral_wallet",
            "claimedAt": "2026-09-22T06:00:00+00:00",
            "provenance": "authenticated_mobile_wallet_claim",
            "rawInstallationPersisted": False,
            "rawClaimTokenPersisted": False,
        }
        status_result = {
            "ok": True,
            "walletCount": 1,
            "wallets": [{
                "referralCode": "OWNER-7K4P",
                "active": True,
                "currency": "EUR",
                "rewardCents": 500,
                "balanceCents": 500,
                "pendingCents": 0,
                "earnedReferrals": 1,
                "pendingReferrals": 0,
                "cancelledReferrals": 0,
                "reversedReferrals": 0,
            }],
            "ownershipProvenance": "authenticated_mobile_wallet_claim",
            "shareCodeIsOwnershipProof": False,
            "accountIdentifiersExposed": False,
            "thirdPartyAppointmentIdentifiersExposed": False,
            "ledgerReferencesExposed": False,
        }
        with mock.patch.object(dispatch.referral_wallet_claims, "consume", return_value=wallet_result) as wallet, \
             mock.patch.object(dispatch.mobile_devices, "consume_vehicle_claim") as vehicle, \
             mock.patch.object(dispatch.referral_wallet_mobile, "status", return_value=status_result) as wallet_status:
            result = dispatch.consume(payload)
        wallet.assert_called_once_with(payload)
        vehicle.assert_not_called()
        wallet_status.assert_called_once_with(self.identity)
        self.assertEqual(result["claimType"], "referral_wallet")
        self.assertEqual(result["provenance"], "authenticated_mobile_wallet_claim")
        self.assertEqual(result["walletStatus"], status_result)
        self.assertNotIn("accountId", result)
        self.assertNotIn("installationId", result)
        self.assertNotIn("registrationSecret", result)
        self.assertNotIn("claimToken", result)
        self.assertNotIn(payload["claimToken"], repr(wallet_status.call_args))

    def test_wallet_status_failure_does_not_turn_consumed_claim_into_failure(self):
        payload = {**self.identity, "claimToken": "rw_" + "C" * 43}
        wallet_result = {
            "ok": True,
            "accountId": "33333333-3333-4333-8333-333333333333",
            "claimedAt": "2026-09-22T06:00:00+00:00",
            "provenance": "authenticated_mobile_wallet_claim",
        }
        with mock.patch.object(dispatch.referral_wallet_claims, "consume", return_value=wallet_result) as wallet, \
             mock.patch.object(dispatch.referral_wallet_mobile, "status", side_effect=RuntimeError("read model unavailable")) as status:
            result = dispatch.consume(payload)
        wallet.assert_called_once_with(payload)
        status.assert_called_once_with(self.identity)
        self.assertTrue(result["ok"])
        self.assertEqual(result["claimType"], "referral_wallet")
        self.assertNotIn("walletStatus", result)

    def test_malformed_or_ambiguous_payload_never_reaches_a_claim_store(self):
        bad_payloads = [
            {**self.identity, "claimToken": "rw_short"},
            {**self.identity, "claimToken": "B" * 43, "extra": True},
            "not-a-dict",
        ]
        with mock.patch.object(dispatch.referral_wallet_claims, "consume") as wallet, \
             mock.patch.object(dispatch.mobile_devices, "consume_vehicle_claim") as vehicle, \
             mock.patch.object(dispatch.referral_wallet_mobile, "status") as wallet_status:
            for payload in bad_payloads:
                with self.subTest(payload=payload):
                    with self.assertRaises(ValueError):
                        dispatch.consume(payload)
        wallet.assert_not_called()
        vehicle.assert_not_called()
        wallet_status.assert_not_called()

    def test_vehicle_claim_refreshes_authoritative_inventory_after_consumption(self):
        payload = {**self.identity, "claimToken": "vc_" + "D" * 40}
        vehicle_result = {
            "ok": True,
            "bindingId": "22222222-2222-4222-8222-222222222222",
            "claimedAt": "2026-09-22T06:00:00+00:00",
        }
        with mock.patch.object(dispatch.mobile_devices, "consume_vehicle_claim", return_value=vehicle_result) as vehicle, \
             mock.patch.object(dispatch, "_start_authoritative_refresh") as start_refresh:
            result = dispatch.consume_with_authoritative_refresh(payload)
        vehicle.assert_called_once_with(payload)
        start_refresh.assert_called_once_with(self.identity["installationId"])
        self.assertEqual(result["claimType"], "vehicle")

    def test_wallet_claim_never_triggers_authoritative_vehicle_refresh(self):
        payload = {**self.identity, "claimToken": "rw_" + "C" * 43}
        wallet_result = {
            "ok": True,
            "accountId": "33333333-3333-4333-8333-333333333333",
            "claimedAt": "2026-09-22T06:00:00+00:00",
            "provenance": "authenticated_mobile_wallet_claim",
        }
        with mock.patch.object(dispatch.referral_wallet_claims, "consume", return_value=wallet_result) as wallet, \
             mock.patch.object(dispatch.referral_wallet_mobile, "status", return_value={"ok": True, "wallets": [], "walletCount": 0}) as status, \
             mock.patch.object(dispatch.mobile_authoritative_sync, "sync_installation") as sync:
            result = dispatch.consume_with_authoritative_refresh(payload)
        wallet.assert_called_once_with(payload)
        status.assert_called_once_with(self.identity)
        sync.assert_not_called()
        self.assertEqual(result["claimType"], "referral_wallet")

    def test_vehicle_claim_survives_best_effort_refresh_failure(self):
        payload = {**self.identity, "claimToken": "vc_" + "E" * 40}
        vehicle_result = {
            "ok": True,
            "bindingId": "22222222-2222-4222-8222-222222222222",
            "claimedAt": "2026-09-22T06:00:00+00:00",
        }
        with mock.patch.object(
            dispatch.mobile_authoritative_sync,
            "sync_installation",
            side_effect=RuntimeError("upstream unavailable"),
        ) as sync:
            dispatch._refresh_vehicle_claim(self.identity["installationId"])
        sync.assert_called_once_with(
            self.identity["installationId"],
            refresh_appointments=True,
        )

    def test_malformed_payload_never_triggers_authoritative_refresh(self):
        payload = {**self.identity, "claimToken": "rw_short"}
        with mock.patch.object(dispatch.mobile_authoritative_sync, "sync_installation") as sync:
            with self.assertRaises(ValueError):
                dispatch.consume_with_authoritative_refresh(payload)
        sync.assert_not_called()

    def test_capability_reports_shared_http_endpoint_ready(self):
        capability = dispatch.capability()
        self.assertTrue(capability["bound"])
        self.assertEqual(capability["claimTypes"], ["vehicle", "referral_wallet"])
        self.assertTrue(capability["vehicleAuthoritativeRefreshBound"])
        self.assertEqual(capability["walletStatusAfterClaim"], "best_effort_verified_read_model")
        self.assertTrue(capability["sharedEndpointReady"])
        self.assertFalse(capability["rawClaimTokenPersisted"])


if __name__ == "__main__":
    unittest.main()
