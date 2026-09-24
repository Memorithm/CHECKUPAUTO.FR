import Foundation
import XCTest
@testable import CheckupAutoReminder

final class MobileBootstrapTests: XCTestCase {
    func testDecodesAndValidatesServerPolicy() throws {
        let json = """
        {"schemaVersion":1,"reminders":{"leadDays":[60,30,15,7,1],"hour":9,"timezone":"Europe/Paris"},"booking":{"url":"https://rdv.checkupauto.fr/"},"notifications":{"remotePushActive":false,"localFallback":true},"referral":{"rewardCents":500,"currency":"EUR"},"app":{"landingUrl":"https://www.checkupauto.fr/app","available":false,"downloadPath":"/go/app"}}
        """.data(using: .utf8)!
        let config = try JSONDecoder().decode(MobileBootstrap.self, from: json).validated()
        XCTAssertEqual(config.reminders.leadDays, [60, 30, 15, 7, 1])
        XCTAssertEqual(config.reminders.timezone, "Europe/Paris")
        XCTAssertEqual(config.referral.rewardCents, 500)
        XCTAssertEqual(config.booking.url, "https://rdv.checkupauto.fr/")
        XCTAssertEqual(config.app.landingUrl, "https://www.checkupauto.fr/app")
        XCTAssertEqual(config.app.downloadPath, "/go/app")
    }

    func testRejectsUnknownSchema() throws {
        let invalid = MobileBootstrap(
            schemaVersion: 2,
            reminders: MobileBootstrap.fallback.reminders,
            booking: MobileBootstrap.fallback.booking,
            notifications: MobileBootstrap.fallback.notifications,
            referral: MobileBootstrap.fallback.referral,
            app: MobileBootstrap.fallback.app
        )
        XCTAssertThrowsError(try invalid.validated())
    }

    func testRejectsUntrustedBookingOrigin() throws {
        let invalid = MobileBootstrap(
            schemaVersion: 1,
            reminders: MobileBootstrap.fallback.reminders,
            booking: MobileBookingConfig(url: "https://example.com/"),
            notifications: MobileBootstrap.fallback.notifications,
            referral: MobileBootstrap.fallback.referral,
            app: MobileBootstrap.fallback.app
        )
        XCTAssertThrowsError(try invalid.validated())
    }

    func testRejectsBookingURLWithCredentialsOrQuery() throws {
        for url in [
            "https://user@rdv.checkupauto.fr/",
            "https://rdv.checkupauto.fr/?source=test",
        ] {
            let invalid = MobileBootstrap(
                schemaVersion: 1,
                reminders: MobileBootstrap.fallback.reminders,
                booking: MobileBookingConfig(url: url),
                notifications: MobileBootstrap.fallback.notifications,
                referral: MobileBootstrap.fallback.referral,
                app: MobileBootstrap.fallback.app
            )
            XCTAssertThrowsError(try invalid.validated(), url)
        }
    }

    func testRejectsUntrustedAppDistributionOriginOrPath() throws {
        for landing in [
            "https://example.com/app",
            "https://www.checkupauto.fr/other",
            "https://www.checkupauto.fr/app?source=test",
        ] {
            let invalid = MobileBootstrap(
                schemaVersion: 1,
                reminders: MobileBootstrap.fallback.reminders,
                booking: MobileBootstrap.fallback.booking,
                notifications: MobileBootstrap.fallback.notifications,
                referral: MobileBootstrap.fallback.referral,
                app: MobileAppConfig(
                    landingUrl: landing,
                    available: false,
                    downloadPath: "/go/app"
                )
            )
            XCTAssertThrowsError(try invalid.validated(), landing)
        }
    }
}
