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
            case .localTest: return "Rappel dans 2 min"
            }
        }

        var compactMessage: String {
            switch moment {
            case .tomorrow: return "CT demain"
            case .approaching, .localTest: return "CT bientôt"
            case .acknowledged: return "Rappel vu"
            }
        }

        var trailerHeading: String {
            moment == .acknowledged ? "RAPPEL" : "CT"
        }

        var trailerDetail: String {
            switch moment {
            case .tomorrow: return "DEMAIN !"
            case .approaching, .localTest: return "BIENTÔT !"
            case .acknowledged: return "VU"
            }
        }

        var trailerMessage: String { trailerHeading + " " + trailerDetail }

        var primaryMessage: String {
            switch moment {
            case .tomorrow: return "Contrôle technique demain"
            case .approaching, .localTest: return "Votre contrôle technique arrive à échéance"
            case .acknowledged: return "Bon trajet vers Checkup Auto"
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

/// Six two-second scene updates: approach, stop, exit, walk, turn, gesture.
/// Compact car and message share the same trajectory during the approach.
/// Phase zero resets without animation rather than reversing the whole scene.
enum CheckupControlConvoyMotion {
    static let animationDuration: TimeInterval = 1.85
    static let phaseCount = 6

    static func phase(for seed: Int) -> Int {
        (seed % phaseCount + phaseCount) % phaseCount
    }

    static func rightToLeftProgress(for seed: Int) -> Double {
        max(0, Double(2 - phase(for: seed)) / 2)
    }

    static func carOffset(for seed: Int, trackWidth: Double) -> Double {
        let travel = carFacesRight(for: seed) ? max(0, trackWidth) + 28 : max(0, trackWidth - 142)
        return travel * carProgress(for: seed)
    }

    static func compactOffset(for seed: Int) -> Double {
        8 * rightToLeftProgress(for: seed) - 4
    }

    static func animatesTransition(for seed: Int) -> Bool {
        phase(for: seed) != 0
    }

    static func characterIsVisible(for seed: Int) -> Bool { phase(for: seed) >= 2 }
    static func characterFacesCar(for seed: Int) -> Bool { phase(for: seed) >= 4 }
    static func carFacesRight(for seed: Int) -> Bool { phase(for: seed) >= 3 }

    static func carProgress(for seed: Int) -> Double {
        [1.0, 0.65, 0.35, 0.58, 0.84, 1.0][phase(for: seed)]
    }

    static func characterProgress(for seed: Int) -> Double {
        [0.28, 0.28, 0.28, 0.12, 0.04, 0.04][phase(for: seed)]
    }

    static func stride(for seed: Int) -> Double {
        [0.0, 0.0, -0.75, 0.85, 0.0, 0.0][phase(for: seed)]
    }

    static func gesture(for seed: Int) -> Double {
        [0.0, 0.0, 0.05, 0.15, 0.45, 1.0][phase(for: seed)]
    }
}
