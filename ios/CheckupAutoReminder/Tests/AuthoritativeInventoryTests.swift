import XCTest
@testable import CheckupAutoReminder

final class AuthoritativeInventoryTests: XCTestCase {
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
