import ActivityKit
import Foundation

struct CheckupControlActivityAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        enum Moment: String, Codable, Hashable {
            case tomorrow
            case approaching
            case acknowledged
        }

        let moment: Moment
        let appointmentAt: Date
        let animationSeed: Int

        var shortLabel: String {
            switch moment {
            case .tomorrow: return "CT demain"
            case .approaching: return "CT bientôt"
            case .acknowledged: return "Rappel vu"
            }
        }

        var primaryMessage: String {
            switch moment {
            case .tomorrow: return "Contrôle technique demain"
            case .approaching: return "Votre contrôle approche"
            case .acknowledged: return "Bon trajet vers Checkup Auto"
            }
        }
    }

    enum ReminderKind: String, Codable, Hashable {
        case dayBefore
        case dayOf
    }

    let reminderId: String
    let kind: ReminderKind
}

enum CheckupControlActivityPolicy {
    static let cardReminder = "Pensez à votre carte grise"
    static let dayOfLeadHours = 2

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
}
