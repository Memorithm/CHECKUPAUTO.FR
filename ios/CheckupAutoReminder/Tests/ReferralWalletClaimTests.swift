import XCTest
@testable import CheckupAutoReminder

final class ReferralWalletClaimTests: XCTestCase {
    private let identity = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
    private let secret = String(repeating: "S", count: 43)
    private let walletToken = "rw_" + String(repeating: "W", count: 43)
    private let vehicleToken = "vc_" + String(repeating: "V", count: 40)

    private var verifiedWallet: ReferralWalletProductStatus {
        ReferralWalletProductStatus(
            referralCode: "OWNER-7K4P",
            active: true,
            currency: "EUR",
            rewardCents: 500,
            balanceCents: 1250,
            pendingCents: 500,
            earnedReferrals: 2,
            pendingReferrals: 1,
            cancelledReferrals: 0,
            reversedReferrals: 0
        )
    }

    private func walletStatus(
        walletCount: Int = 1,
        accountIdentifiersExposed: Bool = false
    ) -> ReferralWalletStatusResponse {
        ReferralWalletStatusResponse(
            ok: true,
            walletCount: walletCount,
            wallets: [verifiedWallet],
            ownershipProvenance: "authenticated_mobile_wallet_claim",
            shareCodeIsOwnershipProof: false,
            accountIdentifiersExposed: accountIdentifiersExposed,
            thirdPartyAppointmentIdentifiersExposed: false,
            ledgerReferencesExposed: false
        )
    }

    func testWalletRequestRequiresWalletNamespaceAndOpaqueIdentity() throws {
        let request = ReferralWalletClaimRequest(
            installationId: identity,
            registrationSecret: secret,
            claimToken: walletToken
        )
        XCTAssertEqual(try request.validated().claimToken, walletToken)

        XCTAssertThrowsError(try ReferralWalletClaimRequest(
            installationId: identity,
            registrationSecret: secret,
            claimToken: vehicleToken
        ).validated())
        XCTAssertThrowsError(try ReferralWalletClaimRequest(
            installationId: "not-a-uuid",
            registrationSecret: secret,
            claimToken: walletToken
        ).validated())
    }

    func testWalletResponseRequiresBoundedProvenance() throws {
        let valid = ReferralWalletClaimResponse(
            ok: true,
            claimType: "referral_wallet",
            claimedAt: "2026-09-22T08:00:00+00:00",
            provenance: "authenticated_mobile_wallet_claim",
            walletStatus: nil
        )
        XCTAssertNoThrow(try valid.validated())

        XCTAssertThrowsError(try ReferralWalletClaimResponse(
            ok: true,
            claimType: "vehicle",
            claimedAt: valid.claimedAt,
            provenance: valid.provenance,
            walletStatus: nil
        ).validated())
        XCTAssertThrowsError(try ReferralWalletClaimResponse(
            ok: true,
            claimType: valid.claimType,
            claimedAt: valid.claimedAt,
            provenance: "unverified",
            walletStatus: nil
        ).validated())
        XCTAssertThrowsError(try ReferralWalletClaimResponse(
            ok: true,
            claimType: valid.claimType,
            claimedAt: "not-a-timestamp",
            provenance: valid.provenance,
            walletStatus: nil
        ).validated())
    }

    func testWalletResponseAcceptsOnlyPrivacyBoundedVerifiedSnapshot() throws {
        let valid = ReferralWalletClaimResponse(
            ok: true,
            claimType: "referral_wallet",
            claimedAt: "2026-09-22T08:00:00+00:00",
            provenance: "authenticated_mobile_wallet_claim",
            walletStatus: walletStatus()
        )
        let result = try valid.validated()
        XCTAssertEqual(result.walletStatus?.wallets, [verifiedWallet])
        XCTAssertEqual(result.walletStatus?.walletCount, 1)

        XCTAssertThrowsError(try ReferralWalletClaimResponse(
            ok: true,
            claimType: "referral_wallet",
            claimedAt: valid.claimedAt,
            provenance: valid.provenance,
            walletStatus: walletStatus(walletCount: 2)
        ).validated())
        XCTAssertThrowsError(try ReferralWalletClaimResponse(
            ok: true,
            claimType: "referral_wallet",
            claimedAt: valid.claimedAt,
            provenance: valid.provenance,
            walletStatus: walletStatus(accountIdentifiersExposed: true)
        ).validated())
    }

    func testVerifiedWalletSnapshotCodecIsBoundedAndDeterministic() throws {
        let snapshot = ReferralWalletVerifiedSnapshot(
            wallets: [verifiedWallet],
            verifiedAt: "2026-09-22T08:00:00+00:00"
        )
        let data = try ReferralWalletSnapshotStore.encode(snapshot)
        XCTAssertEqual(try ReferralWalletSnapshotStore.decode(data), snapshot)
        let serialized = try XCTUnwrap(String(data: data, encoding: .utf8))
        XCTAssertFalse(serialized.contains(identity))
        XCTAssertFalse(serialized.contains(secret))
        XCTAssertFalse(serialized.contains("accountId"))
        XCTAssertFalse(serialized.contains("appointment"))
        XCTAssertFalse(serialized.contains("ledger"))

        XCTAssertThrowsError(try ReferralWalletSnapshotStore.encode(
            ReferralWalletVerifiedSnapshot(
                wallets: [verifiedWallet],
                verifiedAt: "invalid"
            )
        ))
    }

    func testWalletStatusRejectsUnboundedWalletCollection() {
        let wallets = Array(repeating: verifiedWallet, count: 17)
        let response = ReferralWalletStatusResponse(
            ok: true,
            walletCount: wallets.count,
            wallets: wallets,
            ownershipProvenance: "authenticated_mobile_wallet_claim",
            shareCodeIsOwnershipProof: false,
            accountIdentifiersExposed: false,
            thirdPartyAppointmentIdentifiersExposed: false,
            ledgerReferencesExposed: false
        )
        XCTAssertThrowsError(try response.validated())
    }

    func testGenericClaimLinkResolvesWalletAndVehicleTrustDomains() throws {
        let walletURL = URL(string: "https://www.checkupauto.fr/app/claim#token=\(walletToken)")!
        let wallet = try MobileClaimLink.claim(from: walletURL)
        XCTAssertEqual(wallet, MobileClaim(kind: .referralWallet, token: walletToken))
        XCTAssertThrowsError(try VehicleClaimLink.token(from: walletURL))

        let vehicleURL = URL(string: "https://www.checkupauto.fr/app/claim#token=\(vehicleToken)")!
        let vehicle = try MobileClaimLink.claim(from: vehicleURL)
        XCTAssertEqual(vehicle, MobileClaim(kind: .vehicle, token: vehicleToken))
        XCTAssertEqual(try VehicleClaimLink.token(from: vehicleURL), vehicleToken)
    }

    func testGenericClaimLinkAcceptsConfiguredDebugHostOnly() throws {
        let stage = URL(string: "https://stage.179.198.210.187.sslip.io")!
        let stageURL = URL(string: "https://stage.179.198.210.187.sslip.io/app/claim#token=\(walletToken)")!
        let claim = try MobileClaimLink.claim(from: stageURL, trustedBaseURL: stage)
        XCTAssertEqual(claim, MobileClaim(kind: .referralWallet, token: walletToken))

        let unrelated = URL(string: "https://example.com/app/claim#token=\(walletToken)")!
        XCTAssertThrowsError(try MobileClaimLink.claim(from: unrelated, trustedBaseURL: stage))
    }

    func testGenericClaimLinkRejectsUntrustedOriginsAndQueryTokens() {
        XCTAssertThrowsError(try MobileClaimLink.claim(
            from: URL(string: "https://example.com/app/claim#token=\(walletToken)")!
        ))
        XCTAssertThrowsError(try MobileClaimLink.claim(
            from: URL(string: "https://www.checkupauto.fr/app/claim?token=\(walletToken)")!
        ))
    }

    func testWalletClientUsesSharedTypedEndpoint() {
        XCTAssertEqual(ReferralWalletClaimClient.endpoint.path, "/api/mobile/claims/consume")
        XCTAssertEqual(ReferralWalletClaimClient.endpoint, VehicleClaimClient.endpoint)
    }
}
