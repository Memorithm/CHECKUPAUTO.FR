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


extension ReminderPlanTests {
    func testVehicleDeadlineStoreCanBeCleared() {
        let suite = "VehicleDeadlineStoreTests.\(UUID().uuidString)"
        guard let defaults = UserDefaults(suiteName: suite) else {
            return XCTFail("Unable to create isolated defaults")
        }
        defer { defaults.removePersistentDomain(forName: suite) }
        let vehicle = VehicleDeadline(
            registration: "AA-123-BB",
            controlDueDate: date(2027, 1, 1)
        )
        VehicleDeadlineStore.save([vehicle], defaults: defaults)
        XCTAssertEqual(VehicleDeadlineStore.load(defaults: defaults), [vehicle])
        VehicleDeadlineStore.clear(defaults: defaults)
        XCTAssertTrue(VehicleDeadlineStore.load(defaults: defaults).isEmpty)
    }

    func testUsesServerSuppliedLeadDaysAndHour() {
        let moments = ReminderPlan.moments(
            dueDate: date(2027, 1, 1),
            now: date(2026, 12, 1),
            calendar: calendar,
            leadDays: [10, 2],
            hour: 8
        )
        XCTAssertEqual(moments.map(\.daysBefore), [10, 2])
        XCTAssertTrue(moments.allSatisfy { calendar.component(.hour, from: $0.fireDate) == 8 })
    }
}

extension ReminderPlanTests {
    func testSameDayReminderPreservesHourMinuteAndSeconds() throws {
        let now = date(2026, 9, 29, hour: 11)
        let selected = now.addingTimeInterval(12 * 60 + 37)
        let components = try XCTUnwrap(LocalReminderPlan.components(for: selected, now: now))
        XCTAssertEqual(components.hour, 11)
        XCTAssertEqual(components.minute, 12)
        XCTAssertEqual(components.second, 37)
        XCTAssertEqual(components.calendar?.date(from: components), selected)
        XCTAssertNil(LocalReminderPlan.components(for: now, now: now))
        XCTAssertNil(LocalReminderPlan.components(for: now.addingTimeInterval(-60), now: now))
    }

    func testTwoMinuteTestDoesNotWaitUntilTomorrow() throws {
        let now = date(2026, 9, 29, hour: 11).addingTimeInterval(17)
        let selected = LocalReminderPlan.testDate(now: now)
        XCTAssertEqual(selected.timeIntervalSince(now), 120)
        XCTAssertEqual(try XCTUnwrap(LocalReminderPlan.components(for: selected, now: now)).day, 29)
    }

    func testLegacyVehicleDecodesWithoutLosingExistingData() throws {
        let vehicle = VehicleDeadline(registration: "AA-123-BB", controlDueDate: date(2027, 1, 1))
        var payload = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(vehicle)) as? [String: Any])
        payload.removeValue(forKey: "localReminderAt")
        let legacy = try JSONDecoder().decode(VehicleDeadline.self, from: JSONSerialization.data(withJSONObject: payload))
        XCTAssertEqual(legacy.id, vehicle.id)
        XCTAssertEqual(legacy.controlDueDate, vehicle.controlDueDate)
        XCTAssertNil(legacy.localReminderAt)
    }

    func testPreciseReminderSurvivesStorageAndClockChange() throws {
        let selected = ISO8601DateFormatter().date(from: "2026-10-25T01:30:00Z")!
        let vehicle = VehicleDeadline(registration: "AA-123-BB",
                                      controlDueDate: date(2027, 1, 1), localReminderAt: selected)
        let suite = "PreciseReminder.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        VehicleDeadlineStore.save([vehicle], defaults: defaults)
        XCTAssertEqual(VehicleDeadlineStore.load(defaults: defaults).first?.localReminderAt, selected)
        let components = try XCTUnwrap(LocalReminderPlan.components(for: selected, now: date(2026, 10, 1)))
        XCTAssertEqual(components.calendar?.date(from: components), selected)
        XCTAssertEqual(components.timeZone?.secondsFromGMT(), 0)
    }
}

#if os(iOS)
import UserNotifications

extension ReminderPlanTests {
    func testNotificationUsesSelectedInstantWithoutRepeating() throws {
        let now = date(2026, 9, 29, hour: 11)
        let selected = LocalReminderPlan.testDate(now: now)
        let request = try ReminderScheduler.localRequest(identifier: ReminderScheduler.testIdentifier,
            date: selected, body: "Test", now: now)
        let trigger = try XCTUnwrap(request.trigger as? UNCalendarNotificationTrigger)
        XCTAssertFalse(trigger.repeats)
        XCTAssertEqual(trigger.dateComponents.calendar?.date(from: trigger.dateComponents), selected)
        XCTAssertNotNil(request.content.sound)
        XCTAssertTrue(request.content.userInfo.isEmpty)
        XCTAssertThrowsError(try ReminderScheduler.localRequest(identifier: "past", date: now, body: "", now: now))
    }

    func testManualReminderAndTestHaveSeparateIdentifiers() {
        let id = UUID()
        XCTAssertNotEqual(ReminderScheduler.customIdentifier(id), ReminderScheduler.testIdentifier)
        XCTAssertNotEqual(ReminderScheduler.customIdentifier(id), "ct.\(id.uuidString).1")
    }
}
#endif
