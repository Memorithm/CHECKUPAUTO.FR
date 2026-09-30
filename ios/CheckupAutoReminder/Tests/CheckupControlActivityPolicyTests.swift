import AVFoundation
import UserNotifications
import XCTest
@testable import CheckupAutoReminder

final class CheckupControlActivityPolicyTests: XCTestCase {
    func testIslandHornTestUsesOneShortNonRepeatingNotification() throws {
        let request = ReminderScheduler.islandHornTestRequest(choice: .double)
        XCTAssertEqual(request.identifier, ReminderScheduler.islandHornTestIdentifier)
        XCTAssertNotEqual(request.identifier, ReminderScheduler.testIdentifier)
        XCTAssertEqual(request.content.body, "Pensez à votre contrôle technique")
        XCTAssertNotNil(request.content.sound)
        let trigger = try XCTUnwrap(request.trigger as? UNTimeIntervalNotificationTrigger)
        XCTAssertEqual(trigger.timeInterval, 5)
        XCTAssertFalse(trigger.repeats)
    }

    func testHornResourceIsDecodableAndShortEnoughForNotificationSound() throws {
        for choice in CheckupControlHornChoice.allCases {
            let url = try XCTUnwrap(Bundle.main.url(forResource: choice.soundName, withExtension: nil))
            let player = try AVAudioPlayer(contentsOf: url)
            XCTAssertGreaterThan(player.duration, 0)
            XCTAssertLessThan(player.duration, 30)
            XCTAssertEqual(player.numberOfChannels, 1)
        }
    }

    func testHornChoiceSurvivesReloadWithoutChangingOtherSettings() throws {
        let suite = "CheckupAutoHornTests." + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        defaults.set("keep", forKey: "unrelated")
        XCTAssertEqual(CheckupControlHornChoice.load(defaults: defaults), .short)
        for choice in CheckupControlHornChoice.allCases {
            choice.save(defaults: defaults)
            XCTAssertEqual(CheckupControlHornChoice.load(defaults: defaults), choice)
        }
        XCTAssertEqual(defaults.string(forKey: "unrelated"), "keep")
    }

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
        XCTAssertEqual(state.primaryMessage, "Pensez à votre contrôle technique")
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

    func testFixedReminderCopyDoesNotDependOnLegacyAnimationSeed() {
        for moment in [CheckupControlActivityAttributes.ContentState.Moment.tomorrow, .approaching, .localTest] {
            for seed in [Int.min, 0, 5, Int.max] {
                let state = CheckupControlActivityAttributes.ContentState(
                    moment: moment, appointmentAt: Date(timeIntervalSince1970: 1_790_000_000), animationSeed: seed
                )
                XCTAssertEqual(state.reminderMessage, "Pensez à votre contrôle technique")
            }
        }
    }

    func testSilverCarIsBundledAndSizedForEveryIslandPresentation() throws {
        for presentation in CheckupControlVehicleImage.Presentation.allCases {
            let image = try XCTUnwrap(CheckupControlVehicleImage.image(for: presentation))
            XCTAssertLessThanOrEqual(image.size.width, presentation.size.width)
            XCTAssertLessThanOrEqual(image.size.height, presentation.size.height)
            XCTAssertEqual(image.scale, 3)
            XCTAssertGreaterThan(image.size.width, 0)
        }
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

