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
        XCTAssertEqual(state.primaryMessage, "Votre CT arrive à échéance")
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

    func testJourneyTravelsLeftBrakesAndRemainsParked() {
        for width in [280.0, 320.0, 393.0, 430.0] {
            let positions = (0...5).map { CheckupControlJourneyMotion.carOffset(for: $0, trackWidth: width) }
            for index in 1...5 { XCTAssertLessThan(positions[index], positions[index - 1]) }
            XCTAssertLessThan(positions[4] - positions[5], positions[2] - positions[3])
            XCTAssertEqual(CheckupControlJourneyMotion.carOffset(for: 120, trackWidth: width), positions[5])
            let layout = CheckupControlJourneyMotion.layout(trackWidth: width)
            XCTAssertGreaterThan(positions[5], 8 + layout.buildingWidth)
            XCTAssertLessThanOrEqual(positions[5] + layout.convoyWidth, width - 4)
            XCTAssertLessThan(CheckupControlJourneyMotion.wheelRotation(for: 5, trackWidth: width), 0)
            XCTAssertEqual(CheckupControlJourneyMotion.wheelRotation(for: 120, trackWidth: width), CheckupControlJourneyMotion.wheelRotation(for: 5, trackWidth: width))
        }
        XCTAssertFalse(CheckupControlJourneyMotion.isParked(for: 4))
        XCTAssertTrue(CheckupControlJourneyMotion.isParked(for: 5))
        XCTAssertEqual(CheckupControlJourneyMotion.phase(for: Int.min), 0)
        XCTAssertEqual(CheckupControlJourneyMotion.phase(for: Int.max), 5)
        XCTAssertLessThanOrEqual(CheckupControlJourneyMotion.animationDuration, 2)
    }

    func testTrailerJourneyCopyMatchesTheActualReminder() {
        func state(_ moment: CheckupControlActivityAttributes.ContentState.Moment) -> CheckupControlActivityAttributes.ContentState {
            .init(moment: moment, appointmentAt: Date(timeIntervalSince1970: 1_790_000_000), animationSeed: 0)
        }
        XCTAssertEqual(state(.localTest).journeyMessage, "Votre CT arrive à échéance")
        XCTAssertEqual(state(.approaching).journeyMessage, "Votre CT arrive à échéance")
        XCTAssertEqual(state(.tomorrow).journeyMessage, "Votre CT est prévu demain")
        XCTAssertEqual(state(.acknowledged).journeyMessage, "Rappel confirmé Bon trajet !")
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

    func testVisualReviewLaunchModeIsExplicitAndDebugOnly() {
        XCTAssertFalse(CheckupAutoLaunchMode.isJourneyVisualReview(arguments: ["CheckupAutoReminder"]))
        #if DEBUG
        XCTAssertTrue(
            CheckupAutoLaunchMode.isJourneyVisualReview(
                arguments: ["CheckupAutoReminder", "--journey-visual-review"]
            )
        )
        #else
        XCTAssertFalse(
            CheckupAutoLaunchMode.isJourneyVisualReview(
                arguments: ["CheckupAutoReminder", "--journey-visual-review"]
            )
        )
        #endif
    }

}
