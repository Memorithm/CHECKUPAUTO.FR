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

    func testSignedEnvironmentIsAllowlistedAndProcessOverrideCannotChangeRelease() {
        XCTAssertEqual(MobileAPI.packagedBaseURL(environment: nil), MobileAPI.productionBaseURL)
        XCTAssertEqual(MobileAPI.packagedBaseURL(environment: "production"), MobileAPI.productionBaseURL)
        XCTAssertEqual(MobileAPI.packagedBaseURL(environment: "https://attacker.test"), MobileAPI.productionBaseURL)
        XCTAssertEqual(MobileAPI.packagedBaseURL(environment: "preproduction"), MobileAPI.preproductionBaseURL)
        XCTAssertEqual(MobileAPI.resolvedBaseURL(
            environment: [MobileAPI.debugEnvironmentKey: "https://attacker.test"],
            allowOverride: false, packagedEnvironment: "preproduction"
        ), MobileAPI.preproductionBaseURL)
        XCTAssertEqual(MobileAPI.resolvedBaseURL(
            environment: [MobileAPI.debugEnvironmentKey: "http://invalid.test"],
            allowOverride: true, packagedEnvironment: "preproduction"
        ), MobileAPI.preproductionBaseURL)
    }

    func testPreproductionSeparatesStorageAndPreservesAccountRoutes() {
        XCTAssertEqual(MobileAPI.storageKey("identity", preproduction: false), "identity")
        XCTAssertEqual(MobileAPI.storageKey("identity", preproduction: true), "identity.preproduction")
        let account = URL(string: "https://www.checkupauto.fr/compte?source=app#ct-report")!
        XCTAssertEqual(MobileAPI.websiteURL(account, preproduction: true).absoluteString,
                       "https://stage.179.198.210.187.sslip.io/compte?source=app#ct-report")
        XCTAssertEqual(MobileAPI.websiteURL(account, preproduction: false), account)
        for raw in ["https://rdv.checkupauto.fr/", "https://user:secret@www.checkupauto.fr/compte", "https://www.checkupauto.fr:8443/compte"] {
            let url = URL(string: raw)!
            XCTAssertEqual(MobileAPI.websiteURL(url, preproduction: true), url)
        }
    }

    func testBookingJourneyUsesHTTPSOwnOriginAndSeparatesSandbox() {
        let production = MobileAPI.bookingJourneyURL(preproduction: false)
        XCTAssertEqual(production.scheme, "https")
        XCTAssertEqual(production.host, "www.checkupauto.fr")
        XCTAssertEqual(production.path, "/")
        XCTAssertEqual(production.fragment, "reservation")
        let test = MobileAPI.bookingJourneyURL(preproduction: true)
        XCTAssertEqual(test.scheme, "https")
        XCTAssertEqual(test.host, MobileAPI.preproductionBaseURL.host)
        XCTAssertEqual(test.path, "/payment/test")
        XCTAssertNil(test.fragment)
        for url in [production, test] {
            XCTAssertNil(url.user)
            XCTAssertNil(url.password)
            XCTAssertEqual(URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems,
                           [URLQueryItem(name: "source", value: "ios-app")])
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
