import Foundation

struct VehicleDeadline: Codable, Identifiable, Hashable {
    let id: UUID
    var registration: String
    var displayName: String
    var controlDueDate: Date
    var localReminderAt: Date?

    init(
        id: UUID = UUID(),
        registration: String,
        displayName: String = "",
        controlDueDate: Date,
        localReminderAt: Date? = nil
    ) {
        self.id = id
        self.registration = registration
            .uppercased()
            .filter { $0.isLetter || $0.isNumber || $0 == "-" }
        self.displayName = displayName.trimmingCharacters(in: .whitespacesAndNewlines)
        self.controlDueDate = controlDueDate
        self.localReminderAt = localReminderAt
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

enum VehicleDeadlineStore {
    static let storageKey = "checkupauto.vehicle.deadlines.v1"

    static func load(defaults: UserDefaults = .standard) -> [VehicleDeadline] {
        guard let data = defaults.data(forKey: storageKey),
              let decoded = try? JSONDecoder().decode([VehicleDeadline].self, from: data) else {
            return []
        }
        return decoded.sorted { $0.controlDueDate < $1.controlDueDate }
    }

    static func save(_ vehicles: [VehicleDeadline], defaults: UserDefaults = .standard) {
        guard let data = try? JSONEncoder().encode(vehicles) else { return }
        defaults.set(data, forKey: storageKey)
    }

    static func clear(defaults: UserDefaults = .standard) {
        defaults.removeObject(forKey: storageKey)
    }
}

enum LocalReminderPlan {
    static func components(for date: Date, now: Date = Date()) -> DateComponents? {
        guard date > now else { return nil }
        // Store an absolute instant, including seconds for the two-minute test.
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        var components = calendar.dateComponents([.year, .month, .day, .hour, .minute, .second], from: date)
        components.calendar = calendar
        components.timeZone = calendar.timeZone
        guard let resolved = calendar.date(from: components), resolved > now else { return nil }
        return components
    }

    static func testDate(now: Date = Date()) -> Date { now.addingTimeInterval(120) }
}
