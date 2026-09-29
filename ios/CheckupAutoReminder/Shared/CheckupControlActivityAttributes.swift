import ActivityKit
import Foundation

struct CheckupControlActivityAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        enum Moment: String, Codable, Hashable {
            case tomorrow
            case approaching
            case acknowledged
            case localTest
        }

        let moment: Moment
        let appointmentAt: Date
        let animationSeed: Int

        var shortLabel: String {
            switch moment {
            case .tomorrow: return "CT demain"
            case .approaching: return "CT bientôt"
            case .acknowledged: return "Rappel vu"
            case .localTest: return "TEST"
            }
        }

        var primaryMessage: String {
            switch moment {
            case .tomorrow: return "Contrôle technique demain"
            case .approaching: return "Votre contrôle approche"
            case .acknowledged: return "Bon trajet vers Checkup Auto"
            case .localTest: return "Test Dynamic Island"
            }
        }
    }

    enum ReminderKind: String, Codable, Hashable {
        case dayBefore
        case dayOf
        case localTest
    }

    let reminderId: String
    let kind: ReminderKind
}

enum CheckupControlActivityPolicy {
    static let cardReminder = "Pensez à votre carte grise"
    static let hornSoundName = "checkupauto-horn.wav"
    static let dayOfLeadHours = 2
    // ActivityKit currently accepts scheduled starts only inside a bounded future window.
    // Keep a conservative one-day margin and use a persisted background refresh for later starts.
    static let activitySchedulingLookahead: TimeInterval = 6 * 24 * 60 * 60

    static func dayBeforeStart(for appointment: Date, calendar: Calendar = .current) -> Date? {
        guard let previous = calendar.date(byAdding: .day, value: -1, to: appointment) else { return nil }
        var components = calendar.dateComponents([.year, .month, .day], from: previous)
        components.hour = 18
        components.minute = 0
        return calendar.date(from: components)
    }

    static func dayOfStart(for appointment: Date, leadHours: Int = dayOfLeadHours, calendar: Calendar = .current) -> Date? {
        calendar.date(byAdding: .hour, value: -max(1, leadHours), to: appointment)
    }

    static func isInsideSchedulingLookahead(_ requestedStart: Date, now: Date = Date()) -> Bool {
        requestedStart <= now.addingTimeInterval(activitySchedulingLookahead)
    }

    static func retryDate(
        for appointment: Date,
        now: Date = Date(),
        calendar: Calendar = .current
    ) -> Date? {
        let boundary = now.addingTimeInterval(activitySchedulingLookahead)
        let starts = [
            dayBeforeStart(for: appointment, calendar: calendar),
            dayOfStart(for: appointment, calendar: calendar),
        ].compactMap { $0 }
        return starts
            .filter { $0 > boundary }
            .map { $0.addingTimeInterval(-activitySchedulingLookahead) }
            .min()
    }
}
