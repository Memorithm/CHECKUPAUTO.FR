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
