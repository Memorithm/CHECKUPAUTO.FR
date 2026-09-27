import XCTest
@testable import CheckupAutoReminder

final class AuthoritativeInventoryTests: XCTestCase {
    func testFreshAppointmentRequestTimeoutCoversSequentialProviderBudget() {
        XCTAssertEqual(
            AuthoritativeInventoryClient.timeoutInterval(requireFreshAppointments: false),
            8
        )
        XCTAssertGreaterThan(
            AuthoritativeInventoryClient.timeoutInterval(requireFreshAppointments: true),
            55
        )
    }

    func testFreshAppointmentRequestIsExplicitlyEncoded() throws {
        let request = AuthoritativeInventoryRequest(
            installationId: "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1",
            registrationSecret: String(repeating: "A", count: 43),
            refreshAppointments: true
        )
        let data = try JSONEncoder().encode(try request.validated())
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(object["refreshAppointments"] as? Bool, true)
    }

    func testResponseAcceptsOnlyOpaqueBindingAndDate() throws {
        let response = AuthoritativeInventoryResponse(
            ok: true,
            vehicles: [
                AuthoritativeVehicleDeadline(
                    bindingId: "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1",
                    dueDate: "2027-04-30"
                )
            ],
            source: "mercure"
        )
        let validated = try response.validated()
        XCTAssertEqual(validated.vehicles.count, 1)
        XCTAssertNotNil(validated.vehicles[0].dueDateValue)
        XCTAssertNotNil(validated.vehicles[0].bindingUUID)
        XCTAssertNil(validated.referralWalletStatus)
    }

    func testResponseAcceptsOpaqueFutureAppointmentTimestamp() throws {
        let json = "{\"ok\":true,\"vehicles\":[{\"bindingId\":\"60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1\",\"dueDate\":\"2027-04-30\",\"appointmentAt\":\"2026-10-04T14:30:00+02:00\"}],\"source\":\"mercure\"}"
        let response = try JSONDecoder().decode(AuthoritativeInventoryResponse.self, from: Data(json.utf8))
        let vehicle = try XCTUnwrap(try response.validated().vehicles.first)
        XCTAssertNotNil(vehicle.appointmentAtValue)
    }

    func testResponseRejectsMalformedAppointmentTimestamp() throws {
        let json = "{\"ok\":true,\"vehicles\":[{\"bindingId\":\"60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1\",\"dueDate\":\"2027-04-30\",\"appointmentAt\":\"2026-10-04 14:30\"}],\"source\":\"mercure\"}"
        let response = try JSONDecoder().decode(AuthoritativeInventoryResponse.self, from: Data(json.utf8))
        XCTAssertThrowsError(try response.validated())
    }

    func testResponseAllowsBindingWhileAuthoritativeDateIsPending() throws {
        let response = AuthoritativeInventoryResponse(
            ok: true,
            vehicles: [
                AuthoritativeVehicleDeadline(
                    bindingId: "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1",
                    dueDate: nil
                )
            ],
            source: "mercure"
        )
        XCTAssertNoThrow(try response.validated())
    }

    func testResponseRejectsDuplicateBindingOrInvalidDate() {
        let binding = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
        XCTAssertThrowsError(try AuthoritativeInventoryResponse(
            ok: true,
            vehicles: [
                AuthoritativeVehicleDeadline(bindingId: binding, dueDate: "2027-04-30"),
                AuthoritativeVehicleDeadline(bindingId: binding, dueDate: "2027-05-30")
            ],
            source: "mercure"
        ).validated())
        XCTAssertThrowsError(try AuthoritativeVehicleDeadline(
            bindingId: binding,
            dueDate: "2027-02-31"
        ).validated())
    }

    func testResponseValidatesCombinedReferralWalletStatus() throws {
        let wallet = ReferralWalletProductStatus(
            referralCode: "OWNER-7K4P",
            active: true,
            currency: "EUR",
            rewardCents: 500,
            balanceCents: 1000,
            pendingCents: 500,
            earnedReferrals: 2,
            pendingReferrals: 1,
            cancelledReferrals: 0,
            reversedReferrals: 0
        )
        let walletStatus = ReferralWalletStatusResponse(
            ok: true,
            walletCount: 1,
            wallets: [wallet],
            ownershipProvenance: "authenticated_mobile_wallet_claim",
            shareCodeIsOwnershipProof: false,
            accountIdentifiersExposed: false,
            thirdPartyAppointmentIdentifiersExposed: false,
            ledgerReferencesExposed: false
        )
        let validated = try AuthoritativeInventoryResponse(
            ok: true,
            vehicles: [],
            source: "mercure",
            referralWalletStatus: walletStatus
        ).validated()
        XCTAssertEqual(validated.referralWalletStatus?.wallets, [wallet])
    }

    func testResponseRejectsUnsafeReferralWalletProjection() {
        let unsafe = ReferralWalletStatusResponse(
            ok: true,
            walletCount: 0,
            wallets: [],
            ownershipProvenance: "authenticated_mobile_wallet_claim",
            shareCodeIsOwnershipProof: false,
            accountIdentifiersExposed: true,
            thirdPartyAppointmentIdentifiersExposed: false,
            ledgerReferencesExposed: false
        )
        XCTAssertThrowsError(try AuthoritativeInventoryResponse(
            ok: true,
            vehicles: [],
            source: "mercure",
            referralWalletStatus: unsafe
        ).validated())
    }

    func testLegacyInventoryJSONWithoutWalletStatusRemainsDecodable() throws {
        let data = Data("""
        {"ok":true,"vehicles":[],"source":"mercure"}
        """.utf8)
        let decoded = try JSONDecoder().decode(AuthoritativeInventoryResponse.self, from: data)
        let validated = try decoded.validated()
        XCTAssertNil(validated.referralWalletStatus)
    }

    func testOpaqueInventoryPersistsAndClears() {
        let suite = "AuthoritativeInventoryTests.\(UUID().uuidString)"
        guard let defaults = UserDefaults(suiteName: suite) else {
            return XCTFail("Unable to create isolated defaults")
        }
        defer { defaults.removePersistentDomain(forName: suite) }

        let vehicles = [
            AuthoritativeVehicleDeadline(
                bindingId: "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1",
                dueDate: "2027-04-30"
            )
        ]
        AuthoritativeInventoryStore.save(vehicles, defaults: defaults)
        XCTAssertEqual(AuthoritativeInventoryStore.load(defaults: defaults), vehicles)
        AuthoritativeInventoryStore.clear(defaults: defaults)
        XCTAssertTrue(AuthoritativeInventoryStore.load(defaults: defaults).isEmpty)
    }
}

extension AuthoritativeInventoryTests {
    func testReconciliationRemovesDeletedBinding() {
        let previous = [
            AuthoritativeVehicleDeadline(
                bindingId: "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1",
                dueDate: "2027-04-30"
            )
        ]
        XCTAssertEqual(
            AuthoritativeInventoryReconciliation.remindersToRemove(
                previous: previous,
                next: []
            ),
            previous
        )
    }

    func testReconciliationRemovesReminderWhenDateBecomesUnknown() {
        let binding = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
        let previous = [
            AuthoritativeVehicleDeadline(bindingId: binding, dueDate: "2027-04-30")
        ]
        let next = [
            AuthoritativeVehicleDeadline(bindingId: binding, dueDate: nil)
        ]
        XCTAssertEqual(
            AuthoritativeInventoryReconciliation.remindersToRemove(
                previous: previous,
                next: next
            ),
            previous
        )
    }

    func testReconciliationKeepsBindingWhoseDateWillBeRescheduled() {
        let binding = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
        let previous = [
            AuthoritativeVehicleDeadline(bindingId: binding, dueDate: "2027-04-30")
        ]
        let next = [
            AuthoritativeVehicleDeadline(bindingId: binding, dueDate: "2027-05-15")
        ]
        XCTAssertTrue(
            AuthoritativeInventoryReconciliation.remindersToRemove(
                previous: previous,
                next: next
            ).isEmpty
        )
    }
}
