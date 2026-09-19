import XCTest
@testable import CheckupAutoReminder

final class MobileAPITests: XCTestCase {
    func testProductionBaseCannotBeOverriddenWhenOverrideIsDisabled() {
        let env = [MobileAPI.debugEnvironmentKey: "https://preview.example.test"]
        XCTAssertEqual(
            MobileAPI.resolvedBaseURL(environment: env, allowOverride: false),
            MobileAPI.productionBaseURL
        )
    }

    func testDebugOverrideAcceptsOnlyCleanHTTPSOrigin() {
        let valid = [MobileAPI.debugEnvironmentKey: "https://preview.example.test"]
        XCTAssertEqual(
            MobileAPI.resolvedBaseURL(environment: valid, allowOverride: true).absoluteString,
            "https://preview.example.test"
        )

        for invalid in [
            "http://preview.example.test",
            "https://user:secret@preview.example.test",
            "https://preview.example.test/path",
            "https://preview.example.test?token=secret",
            "not-a-url",
        ] {
            XCTAssertEqual(
                MobileAPI.resolvedBaseURL(
                    environment: [MobileAPI.debugEnvironmentKey: invalid],
                    allowOverride: true
                ),
                MobileAPI.productionBaseURL
            )
        }
    }

    func testEndpointComposition() {
        let base = URL(string: "https://preview.example.test")!
        XCTAssertEqual(
            MobileAPI.endpoint("/api/mobile/bootstrap", baseURL: base).absoluteString,
            "https://preview.example.test/api/mobile/bootstrap"
        )
    }
}
