import XCTest
@testable import CheckupAutoReminder

final class VehicleClaimTests: XCTestCase {
    private let token = String(repeating: "A", count: 43)
    private let walletToken = "rw_" + String(repeating: "B", count: 43)

    func testClaimRequestAcceptsOpaqueIdentityOnly() throws {
        let request = VehicleClaimRequest(
            installationId: "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1",
            registrationSecret: String(repeating: "B", count: 43),
            claimToken: token
        )
        XCTAssertNoThrow(try request.validated())
        XCTAssertThrowsError(try VehicleClaimRequest(
            installationId: request.installationId,
            registrationSecret: request.registrationSecret,
            claimToken: "too short"
        ).validated())
    }

    func testMobileClaimNamespaceDistinguishesVehicleAndReferralWallet() throws {
        XCTAssertEqual(try MobileClaimToken.kind(of: token), .vehicle)
        XCTAssertEqual(try MobileClaimToken.kind(of: walletToken), .referralWallet)
        XCTAssertThrowsError(try MobileClaimToken.kind(of: "rw_short"))
    }

    func testVehicleClaimRejectsReferralWalletNamespace() throws {
        XCTAssertThrowsError(try VehicleClaimToken.validated(walletToken))
        XCTAssertNoThrow(try VehicleClaimToken.validated(token))
    }

    func testClaimLinkRequiresCheckupAutoHttpsAndFragmentToken() throws {
        let valid = URL(string: "https://www.checkupauto.fr/app/claim#token=\(token)")!
        XCTAssertEqual(try VehicleClaimLink.token(from: valid), token)

        let wallet = URL(string: "https://www.checkupauto.fr/app/claim#token=\(walletToken)")!
        XCTAssertThrowsError(try VehicleClaimLink.token(from: wallet))

        let queryToken = URL(string: "https://www.checkupauto.fr/app/claim?token=\(token)")!
        XCTAssertThrowsError(try VehicleClaimLink.token(from: queryToken))

        let wrongHost = URL(string: "https://example.com/app/claim#token=\(token)")!
        XCTAssertThrowsError(try VehicleClaimLink.token(from: wrongHost))

        let clearText = URL(string: "http://www.checkupauto.fr/app/claim#token=\(token)")!
        XCTAssertThrowsError(try VehicleClaimLink.token(from: clearText))
    }

    func testClaimResponseRequiresOpaqueBindingUuid() throws {
        let response = VehicleClaimResponse(
            ok: true,
            bindingId: "bd99535d-b2f3-49aa-8b5e-2247ace56cf2",
            claimedAt: "2026-09-19T21:45:00+00:00"
        )
        XCTAssertNoThrow(try response.validated())
        XCTAssertThrowsError(try VehicleClaimResponse(
            ok: true,
            bindingId: "vehicle-77",
            claimedAt: response.claimedAt
        ).validated())
    }

    func testClaimEndpointIsDedicated() {
        XCTAssertEqual(VehicleClaimClient.endpoint.path, "/api/mobile/claims/consume")
    }
}
