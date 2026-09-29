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

        var journeyHeading: String {
            switch moment {
            case .tomorrow: return "Votre CT est prévu"
            case .approaching, .localTest: return "Votre CT arrive"
            case .acknowledged: return "Rappel confirmé"
            }
        }

        var journeyDetail: String {
            switch moment {
            case .tomorrow: return "demain"
            case .approaching, .localTest: return "à échéance"
            case .acknowledged: return "Bon trajet !"
            }
        }

        var journeyMessage: String { journeyHeading + " " + journeyDetail }

        var primaryMessage: String {
            switch moment {
            case .tomorrow: return "Contrôle technique demain"
            case .approaching, .localTest: return "Votre CT arrive à échéance"
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

/// A single trip: enter from the right, roll left, brake, then remain parked.
/// Animation endpoints are advanced every two seconds by the local demo.
enum CheckupControlJourneyMotion {
    static let animationDuration: TimeInterval = 1.95
    static let arrivalPhase = 5

    static func phase(for seed: Int) -> Int { min(arrivalPhase, max(0, seed)) }
    static func progress(for seed: Int) -> Double {
        [0.0, 0.23, 0.48, 0.72, 0.90, 1.0][phase(for: seed)]
    }
    static func isParked(for seed: Int) -> Bool { phase(for: seed) == arrivalPhase }

    static func layout(trackWidth: Double) -> CheckupControlJourneyLayout {
        CheckupControlJourneyLayout(trackWidth: max(0, trackWidth))
    }
    static func carOffset(for seed: Int, trackWidth: Double) -> Double {
        let layout = layout(trackWidth: trackWidth)
        let start = max(layout.stopX, trackWidth - 42 * layout.scale)
        return start + (layout.stopX - start) * progress(for: seed)
    }
    static func wheelRotation(for seed: Int, trackWidth: Double) -> Double {
        let scale = layout(trackWidth: trackWidth).scale
        let distance = carOffset(for: seed, trackWidth: trackWidth) - carOffset(for: 0, trackWidth: trackWidth)
        return distance / (6.5 * scale) * 180 / .pi
    }
}

struct CheckupControlJourneyLayout {
    let trackWidth: Double
    var scale: Double { min(1.1, max(0.45, (trackWidth - 24) / 280)) }
    var buildingWidth: Double { 72 * scale }
    var convoyWidth: Double { 208 * scale }
    var stopX: Double { 16 + buildingWidth }
}
