import unittest

import mobile_claim_dispatch as dispatch


class MobileClaimWalletSnapshotBoundaryTest(unittest.TestCase):
    def test_projection_strips_unexpected_internal_identifiers(self):
        status = {
            "ok": True,
            "walletCount": 1,
            "wallets": [{
                "referralCode": "OWNER-7K4P",
                "active": True,
                "currency": "EUR",
                "rewardCents": 500,
                "balanceCents": 1250,
                "pendingCents": 500,
                "earnedReferrals": 2,
                "pendingReferrals": 1,
                "cancelledReferrals": 0,
                "reversedReferrals": 0,
                "accountId": "internal-account-id",
                "appointmentId": "internal-appointment-id",
            }],
            "ownershipProvenance": "authenticated_mobile_wallet_claim",
            "shareCodeIsOwnershipProof": False,
            "accountIdentifiersExposed": False,
            "thirdPartyAppointmentIdentifiersExposed": False,
            "ledgerReferencesExposed": False,
            "internalTrace": "must-not-cross-mobile-boundary",
        }

        result = dispatch._project_wallet_status(status)

        self.assertIsNotNone(result)
        serialized = repr(result)
        self.assertNotIn("accountId", serialized)
        self.assertNotIn("appointmentId", serialized)
        self.assertNotIn("internalTrace", serialized)
        self.assertEqual(result["walletCount"], 1)
        self.assertEqual(
            set(result["wallets"][0]),
            set(dispatch._WALLET_FIELDS),
        )

    def test_projection_fails_closed_if_privacy_contract_is_not_explicit(self):
        base = {
            "ok": True,
            "wallets": [],
            "ownershipProvenance": "authenticated_mobile_wallet_claim",
            "shareCodeIsOwnershipProof": False,
            "accountIdentifiersExposed": False,
            "thirdPartyAppointmentIdentifiersExposed": False,
            "ledgerReferencesExposed": False,
        }
        for field in (
            "shareCodeIsOwnershipProof",
            "accountIdentifiersExposed",
            "thirdPartyAppointmentIdentifiersExposed",
            "ledgerReferencesExposed",
        ):
            with self.subTest(field=field):
                unsafe = dict(base)
                unsafe[field] = True
                self.assertIsNone(dispatch._project_wallet_status(unsafe))

        missing = dict(base)
        missing.pop("accountIdentifiersExposed")
        self.assertIsNone(dispatch._project_wallet_status(missing))

    def test_projection_requires_verified_ownership_provenance(self):
        self.assertIsNone(dispatch._project_wallet_status({
            "ok": True,
            "wallets": [],
            "ownershipProvenance": "unverified",
            "shareCodeIsOwnershipProof": False,
            "accountIdentifiersExposed": False,
            "thirdPartyAppointmentIdentifiersExposed": False,
            "ledgerReferencesExposed": False,
        }))


if __name__ == "__main__":
    unittest.main()
