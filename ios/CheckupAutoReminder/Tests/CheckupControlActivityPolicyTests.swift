import XCTest
@testable import CheckupAutoReminder

final class CheckupControlActivityPolicyTests: XCTestCase {
    func testDayBeforeReminderStartsAt18ParisTime() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Europe/Paris")!
        let appointment = try XCTUnwrap(calendar.date(from: DateComponents(year: 2026, month: 10, day: 4, hour: 14, minute: 30)))
        let start = try XCTUnwrap(CheckupControlActivityPolicy.dayBeforeStart(for: appointment, calendar: calendar))
        let c = calendar.dateComponents([.year,.month,.day,.hour,.minute], from: start)
        XCTAssertEqual(c.day, 3)
        XCTAssertEqual(c.hour, 18)
        XCTAssertEqual(c.minute, 0)
    }

    func testDayOfReminderStartsTwoHoursBeforeAppointment() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Europe/Paris")!
        let appointment = try XCTUnwrap(calendar.date(from: DateComponents(year: 2026, month: 10, day: 4, hour: 14, minute: 30)))
        let start = try XCTUnwrap(CheckupControlActivityPolicy.dayOfStart(for: appointment, calendar: calendar))
        let c = calendar.dateComponents([.hour,.minute], from: start)
        XCTAssertEqual(c.hour, 12)
        XCTAssertEqual(c.minute, 30)
    }
    func testFutureAppointmentPersistsRetryAtSchedulingHorizon() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Europe/Paris")!
        let now = try XCTUnwrap(
            calendar.date(from: DateComponents(year: 2026, month: 10, day: 1, hour: 10))
        )
        let appointment = try XCTUnwrap(
            calendar.date(from: DateComponents(year: 2026, month: 10, day: 31, hour: 14, minute: 30))
        )
        let retry = try XCTUnwrap(
            CheckupControlActivityPolicy.retryDate(
                for: appointment,
                now: now,
                calendar: calendar
            )
        )
        let expectedStart = try XCTUnwrap(
            CheckupControlActivityPolicy.dayBeforeStart(for: appointment, calendar: calendar)
        )
        XCTAssertEqual(
            retry,
            expectedStart.addingTimeInterval(
                -CheckupControlActivityPolicy.activitySchedulingLookahead
            )
        )
    }

    func testAppointmentAlreadyInsideSchedulingHorizonNeedsNoDeferredRetry() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Europe/Paris")!
        let now = try XCTUnwrap(
            calendar.date(from: DateComponents(year: 2026, month: 10, day: 1, hour: 10))
        )
        let appointment = try XCTUnwrap(
            calendar.date(from: DateComponents(year: 2026, month: 10, day: 4, hour: 14, minute: 30))
        )
        XCTAssertNil(
            CheckupControlActivityPolicy.retryDate(
                for: appointment,
                now: now,
                calendar: calendar
            )
        )
    }
}
