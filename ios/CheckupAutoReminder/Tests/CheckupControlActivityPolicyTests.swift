import XCTest
@testable import CheckupAutoReminder

final class CheckupControlActivityPolicyTests: XCTestCase {
    func testLocalActivityTestIsDistinctFromAppointmentReminders() {
        let state = CheckupControlActivityAttributes.ContentState(
            moment: .localTest,
            appointmentAt: Date(timeIntervalSince1970: 1_790_000_000),
            animationSeed: 42
        )
        let attributes = CheckupControlActivityAttributes(
            reminderId: "ct.local.test-island.test",
            kind: .localTest
        )

        XCTAssertEqual(state.shortLabel, "Rappel dans 2 min")
        XCTAssertEqual(state.compactMessage, "CT bientôt")
        XCTAssertEqual(state.primaryMessage, "Votre contrôle technique arrive à échéance")
        XCTAssertEqual(attributes.kind, .localTest)
        XCTAssertTrue(attributes.reminderId.hasPrefix("ct.local.test-island."))
    }

    func testCompactReminderLabelMatchesDeadlineState() {
        func state(for moment: CheckupControlActivityAttributes.ContentState.Moment) -> CheckupControlActivityAttributes.ContentState {
            CheckupControlActivityAttributes.ContentState(
                moment: moment,
                appointmentAt: Date(timeIntervalSince1970: 1_790_000_000),
                animationSeed: 1
            )
        }

        XCTAssertEqual(state(for: .tomorrow).compactMessage, "CT demain")
        XCTAssertEqual(state(for: .approaching).compactMessage, "CT bientôt")
        XCTAssertEqual(state(for: .localTest).compactMessage, "CT bientôt")
    }

    func testTrailerCopyMatchesReminderWithoutInventingAppointment() {
        func state(_ moment: CheckupControlActivityAttributes.ContentState.Moment) -> CheckupControlActivityAttributes.ContentState {
            .init(moment: moment, appointmentAt: Date(timeIntervalSince1970: 1_790_000_000), animationSeed: 0)
        }
        XCTAssertEqual(state(.localTest).trailerMessage, "CT BIENTÔT !")
        XCTAssertEqual(state(.approaching).trailerMessage, "CT BIENTÔT !")
        XCTAssertEqual(state(.tomorrow).trailerMessage, "CT DEMAIN !")
        XCTAssertEqual(state(.acknowledged).trailerMessage, "RAPPEL VU")
    }

    func testConvoyMovesLeftAndWrapDoesNotAnimateBackwards() {
        let positions = (0...2).map {
            CheckupControlConvoyMotion.carOffset(for: $0, trackWidth: 280)
        }
        XCTAssertGreaterThan(positions[0], positions[1])
        XCTAssertGreaterThan(positions[1], positions[2])
        XCTAssertGreaterThanOrEqual(positions[2], 0)
        XCTAssertFalse(CheckupControlConvoyMotion.animatesTransition(for: 6))
        XCTAssertTrue(CheckupControlConvoyMotion.animatesTransition(for: 1))
        XCTAssertLessThanOrEqual(CheckupControlConvoyMotion.animationDuration, 2)
        XCTAssertEqual(CheckupControlConvoyMotion.carOffset(for: 0, trackWidth: 100), 0)
        XCTAssertGreaterThan(CheckupControlConvoyMotion.carOffset(for: 5, trackWidth: 280), 280)
        for seed in [Int.min, -7, -1, 0, 7, Int.max] {
            XCTAssertTrue((0..<6).contains(CheckupControlConvoyMotion.phase(for: seed)))
        }
    }

    func testCharacterExitsWalksLeftAndTurnsTowardsDepartingCar() {
        XCTAssertFalse(CheckupControlConvoyMotion.characterIsVisible(for: 1))
        XCTAssertTrue(CheckupControlConvoyMotion.characterIsVisible(for: 2))
        XCTAssertLessThan(CheckupControlConvoyMotion.characterProgress(for: 3), CheckupControlConvoyMotion.characterProgress(for: 2))
        XCTAssertLessThan(CheckupControlConvoyMotion.characterProgress(for: 4), CheckupControlConvoyMotion.characterProgress(for: 3))
        XCTAssertGreaterThan(CheckupControlConvoyMotion.carProgress(for: 3), CheckupControlConvoyMotion.carProgress(for: 2))
        XCTAssertGreaterThan(CheckupControlConvoyMotion.carProgress(for: 4), CheckupControlConvoyMotion.carProgress(for: 3))
        XCTAssertFalse(CheckupControlConvoyMotion.characterFacesCar(for: 3))
        XCTAssertTrue(CheckupControlConvoyMotion.characterFacesCar(for: 4))
        XCTAssertGreaterThan(CheckupControlConvoyMotion.gesture(for: 5), CheckupControlConvoyMotion.gesture(for: 4))
    }

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
