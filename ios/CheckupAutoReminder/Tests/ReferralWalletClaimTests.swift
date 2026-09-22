import XCTest
@testable import CheckupAutoReminder

final class ReferralWalletClaimTests: XCTestCase {
    private let identity = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
    private let secret = String(repeating: "S", count: 43)
    private let walletToken = "rw_" + String(repeating: "W", count: 43)
    private let vehicleToken = "vc_" + String(repeating: "V", count: 40)

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
            provenance: "authenticated_mobile_wallet_claim"
        )
        XCTAssertNoThrow(try valid.validated())

        XCTAssertThrowsError(try ReferralWalletClaimResponse(
            ok: true,
            claimType: "vehicle",
            claimedAt: valid.claimedAt,
            provenance: valid.provenance
        ).validated())
        XCTAssertThrowsError(try ReferralWalletClaimResponse(
            ok: true,
            claimType: valid.claimType,
            claimedAt: valid.claimedAt,
            provenance: "unverified"
        ).validated())
    }

    func testGenericClaimLinkAcceptsWalletButVehicleLinkRejectsIt() throws {
        let url = URL(string: "https://www.checkupauto.fr/app/claim#token=\(walletToken)")!
        XCTAssertEqual(try MobileClaimLink.token(from: url), walletToken)
        XCTAssertEqual(try MobileClaimToken.kind(of: MobileClaimLink.token(from: url)), .referralWallet)
        XCTAssertThrowsError(try VehicleClaimLink.token(from: url))
    }

    func testWalletClientUsesSharedTypedEndpoint() {
        XCTAssertEqual(ReferralWalletClaimClient.endpoint.path, "/api/mobile/claims/consume")
        XCTAssertEqual(ReferralWalletClaimClient.endpoint, VehicleClaimClient.endpoint)
    }
}
