import XCTest
@testable import CheckupAutoReminder

final class ReminderPlanTests: XCTestCase {
    private var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        return calendar
    }

    private func date(_ year: Int, _ month: Int, _ day: Int, hour: Int = 0) -> Date {
        calendar.date(from: DateComponents(year: year, month: month, day: day, hour: hour))!
    }

    func testCreatesAllDefaultReminderMomentsWhenTheyAreFuture() {
        let moments = ReminderPlan.moments(
            dueDate: date(2027, 1, 1),
            now: date(2026, 10, 1),
            calendar: calendar
        )
        XCTAssertEqual(moments.map(\.daysBefore), [60, 30, 15, 7, 1])
    }
}

extension ReminderPlanTests {
    func testDropsReminderMomentsThatAlreadyPassed() {
        let moments = ReminderPlan.moments(
            dueDate: date(2027, 1, 1),
            now: date(2026, 12, 20),
            calendar: calendar
        )
        XCTAssertEqual(moments.map(\.daysBefore), [7, 1])
        XCTAssertTrue(moments.allSatisfy { $0.fireDate > date(2026, 12, 20) })
    }
}
