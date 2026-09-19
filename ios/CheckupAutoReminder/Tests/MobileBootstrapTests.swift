import Foundation
import XCTest
@testable import CheckupAutoReminder

final class MobileBootstrapTests: XCTestCase {
    func testDecodesAndValidatesServerPolicy() throws {
        let json = """
        {"schemaVersion":1,"reminders":{"leadDays":[60,30,15,7,1],"hour":9,"timezone":"Europe/Paris"},"booking":{"url":"https://rdv.checkupauto.fr/"},"referral":{"rewardCents":500,"currency":"EUR"},"app":{"landingUrl":"https://www.checkupauto.fr/app","available":false,"downloadPath":"/go/app"}}
        """.data(using: .utf8)!
        let config = try JSONDecoder().decode(MobileBootstrap.self, from: json).validated()
        XCTAssertEqual(config.reminders.leadDays, [60, 30, 15, 7, 1])
        XCTAssertEqual(config.reminders.timezone, "Europe/Paris")
        XCTAssertEqual(config.referral.rewardCents, 500)
    }

    func testRejectsUnknownSchema() throws {
        let invalid = MobileBootstrap(
            schemaVersion: 2,
            reminders: MobileBootstrap.fallback.reminders,
            booking: MobileBootstrap.fallback.booking,
            referral: MobileBootstrap.fallback.referral,
            app: MobileBootstrap.fallback.app
        )
        XCTAssertThrowsError(try invalid.validated())
    }
}
