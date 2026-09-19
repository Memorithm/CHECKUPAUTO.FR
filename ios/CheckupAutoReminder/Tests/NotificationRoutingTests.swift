import XCTest
@testable import CheckupAutoReminder

final class NotificationRoutingTests: XCTestCase {
    func testControlReminderUsesStableActionIdentifiers() {
        XCTAssertEqual(NotificationRouting.controlDueCategory, "CHECKUPAUTO_CT_DUE")
        XCTAssertEqual(NotificationRouting.bookAction, "CHECKUPAUTO_BOOK")
        XCTAssertNotEqual(NotificationRouting.controlDueCategory, NotificationRouting.bookAction)
    }
}
