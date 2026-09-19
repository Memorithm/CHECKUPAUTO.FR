import XCTest
@testable import CheckupAutoReminder

final class DeviceRegistrationTests: XCTestCase {
    func testRegistrationRequestValidation() throws {
        let request = DeviceRegistrationRequest(
            installationId: "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1",
            registrationSecret: String(repeating: "A", count: 43),
            deviceToken: String(repeating: "ab", count: 32),
            environment: "sandbox")
        XCTAssertNoThrow(try request.validated())
    }

    func testRegistrationRejectsMalformedTokenAndEnvironment() {
        let base = DeviceRegistrationRequest(
            installationId: "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1",
            registrationSecret: String(repeating: "A", count: 43), deviceToken: "xyz", environment: "sandbox")
        XCTAssertThrowsError(try base.validated())
        let badEnv = DeviceRegistrationRequest(installationId: base.installationId,
            registrationSecret: base.registrationSecret, deviceToken: String(repeating: "ab", count: 32), environment: "other")
        XCTAssertThrowsError(try badEnv.validated())
    }
}

extension DeviceRegistrationTests {
    func testUnregistrationRequestValidation() throws {
        let request = DeviceUnregistrationRequest(
            installationId: "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1",
            registrationSecret: String(repeating: "A", count: 43)
        )
        XCTAssertNoThrow(try request.validated())
        XCTAssertThrowsError(try DeviceUnregistrationRequest(
            installationId: "invalid",
            registrationSecret: request.registrationSecret
        ).validated())
    }

    func testRemoteRegistrationStateIsDeviceLocalAndNotifiesOnChangeOnly() {
        let suite = "DeviceRegistrationTests.\(UUID().uuidString)"
        guard let defaults = UserDefaults(suiteName: suite) else {
            return XCTFail("Unable to create isolated defaults")
        }
        defer { defaults.removePersistentDomain(forName: suite) }
        let center = NotificationCenter()
        let changedTwice = expectation(description: "registration state changed twice")
        changedTwice.expectedFulfillmentCount = 2
        let token = center.addObserver(
            forName: DeviceRegistrationState.changedNotification,
            object: nil,
            queue: nil
        ) { _ in changedTwice.fulfill() }
        defer { center.removeObserver(token) }

        XCTAssertFalse(DeviceRegistrationState.isRegistered(defaults: defaults))
        DeviceRegistrationState.setRegistered(true, defaults: defaults, center: center)
        XCTAssertTrue(DeviceRegistrationState.isRegistered(defaults: defaults))
        DeviceRegistrationState.setRegistered(true, defaults: defaults, center: center)
        DeviceRegistrationState.setRegistered(false, defaults: defaults, center: center)
        XCTAssertFalse(DeviceRegistrationState.isRegistered(defaults: defaults))
        wait(for: [changedTwice], timeout: 1)
    }
}
