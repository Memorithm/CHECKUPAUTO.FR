import Foundation

struct VehicleDeadline: Codable, Identifiable, Hashable {
    let id: UUID
    var registration: String
    var displayName: String
    var controlDueDate: Date

    init(
        id: UUID = UUID(),
        registration: String,
        displayName: String = "",
        controlDueDate: Date
    ) {
        self.id = id
        self.registration = registration
            .uppercased()
            .filter { $0.isLetter || $0.isNumber || $0 == "-" }
        self.displayName = displayName.trimmingCharacters(in: .whitespacesAndNewlines)
        self.controlDueDate = controlDueDate
    }
}

struct ReminderMoment: Hashable {
    let daysBefore: Int
    let fireDate: Date
}
enum ReminderPlan {
    static let defaultLeadDays = [60, 30, 15, 7, 1]

    static func moments(
        dueDate: Date,
        now: Date = Date(),
        calendar: Calendar = .current,
        leadDays: [Int] = defaultLeadDays,
        hour: Int = 9
    ) -> [ReminderMoment] {
        leadDays.compactMap { days in
            guard let day = calendar.date(byAdding: .day, value: -days, to: dueDate) else {
                return nil
            }
            var components = calendar.dateComponents([.year, .month, .day], from: day)
            components.hour = hour
            components.minute = 0
            guard let fireDate = calendar.date(from: components), fireDate > now else {
                return nil
            }
            return ReminderMoment(daysBefore: days, fireDate: fireDate)
        }
        .sorted { $0.fireDate < $1.fireDate }
    }
}
