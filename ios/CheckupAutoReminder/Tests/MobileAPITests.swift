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
                       "https://test.checkupauto.fr/compte?source=app#ct-report")
        XCTAssertEqual(MobileAPI.websiteURL(account, preproduction: false), account)
        for raw in ["https://rdv.checkupauto.fr/", "https://user:secret@www.checkupauto.fr/compte", "https://www.checkupauto.fr:8443/compte"] {
            let url = URL(string: raw)!
            XCTAssertEqual(MobileAPI.websiteURL(url, preproduction: true), url)
        }
    }

    func testBookingJourneyUsesPublicPlannerOnEachHTTPSOrigin() {
        let production = MobileAPI.bookingJourneyURL(preproduction: false)
        XCTAssertEqual(production.scheme, "https")
        XCTAssertEqual(production.host, "www.checkupauto.fr")
        XCTAssertEqual(production.path, "/")
        XCTAssertEqual(production.fragment, "reservation")
        let test = MobileAPI.bookingJourneyURL(preproduction: true)
        XCTAssertEqual(test.scheme, "https")
        XCTAssertEqual(test.host, "test.checkupauto.fr")
        XCTAssertEqual(test.path, "/")
        XCTAssertEqual(test.fragment, "reservation")
        for url in [production, test] {
            XCTAssertNil(url.user)
            XCTAssertNil(url.password)
            XCTAssertEqual(URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems,
                           [URLQueryItem(name: "utm_source", value: "app:ios")])
        }
    }

    func testAccountAndProviderPathsStayOnPlanetHosterInPreproduction() {
        for path in ["/compte", "/compte/ct-report", "/auth/customer/google/callback",
                     "/auth/customer/microsoft/callback", "/auth/customer/apple/callback"] {
            let production = URL(string: "https://www.checkupauto.fr" + path)!
            let test = MobileAPI.websiteURL(production, preproduction: true)
            XCTAssertEqual(test.scheme, "https")
            XCTAssertEqual(test.host, "test.checkupauto.fr")
            XCTAssertEqual(test.path, path)
            XCTAssertEqual(MobileAPI.websiteURL(test, preproduction: true), test)
            XCTAssertEqual(MobileAPI.websiteURL(production, preproduction: false), production)
        }
        XCTAssertEqual(MobileAPI.preproductionBaseURL.absoluteString, "https://test.checkupauto.fr")
    }

    func testEndpointComposition() {
        let base = URL(string: "https://preview.example.test")!
        XCTAssertEqual(
            MobileAPI.endpoint("/api/mobile/bootstrap", baseURL: base).absoluteString,
            "https://preview.example.test/api/mobile/bootstrap"
        )
    }
}
