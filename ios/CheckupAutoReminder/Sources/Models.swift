import Foundation
import Security

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

/// Stockage protégé des échéances locales (audit I-02).
///
/// Les immatriculations ne restent plus dans `UserDefaults` (plist en clair
/// dans les sauvegardes non chiffrées) : elles vont dans le trousseau, classe
/// `AfterFirstUnlock` pour que les rappels puissent être replanifiés en arrière-plan.
protocol VehicleDeadlineSecureStorage: Sendable {
    func read() -> Data?
    func write(_ data: Data) throws
    func delete()
}

struct KeychainVehicleDeadlineStorage: VehicleDeadlineSecureStorage {
    var service = "fr.checkupauto.reminder.vehicle-deadlines"
    var account = VehicleDeadlineStore.storageKey

    private var base: [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
    }

    func read() -> Data? {
        var query = base
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess else { return nil }
        return item as? Data
    }

    func write(_ data: Data) throws {
        SecItemDelete(base as CFDictionary)
        var insert = base
        insert[kSecValueData as String] = data
        insert[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlock
        let status = SecItemAdd(insert as CFDictionary, nil)
        guard status == errSecSuccess else { throw NSError(domain: NSOSStatusErrorDomain, code: Int(status)) }
    }

    func delete() {
        SecItemDelete(base as CFDictionary)
    }
}

enum VehicleDeadlineStore {
    static let storageKey = MobileAPI.storageKey("checkupauto.vehicle.deadlines.v1")

    static func load(
        defaults: UserDefaults = .standard,
        storage: any VehicleDeadlineSecureStorage = KeychainVehicleDeadlineStorage()
    ) -> [VehicleDeadline] {
        if let data = storage.read() {
            return decode(data)
        }
        // Migration unique depuis UserDefaults : la copie en clair n'est
        // supprimée qu'une fois l'écriture dans le trousseau réussie.
        guard let legacy = defaults.data(forKey: storageKey) else { return [] }
        if (try? storage.write(legacy)) != nil {
            defaults.removeObject(forKey: storageKey)
        }
        return decode(legacy)
    }

    static func save(
        _ vehicles: [VehicleDeadline],
        defaults: UserDefaults = .standard,
        storage: any VehicleDeadlineSecureStorage = KeychainVehicleDeadlineStorage()
    ) {
        guard let data = try? JSONEncoder().encode(vehicles) else { return }
        if (try? storage.write(data)) != nil {
            defaults.removeObject(forKey: storageKey)
        } else {
            // Ne jamais perdre les échéances si le trousseau est indisponible.
            defaults.set(data, forKey: storageKey)
        }
    }

    static func clear(
        defaults: UserDefaults = .standard,
        storage: any VehicleDeadlineSecureStorage = KeychainVehicleDeadlineStorage()
    ) {
        storage.delete()
        defaults.removeObject(forKey: storageKey)
    }

    private static func decode(_ data: Data) -> [VehicleDeadline] {
        guard let decoded = try? JSONDecoder().decode([VehicleDeadline].self, from: data) else {
            return []
        }
        return decoded.sorted { $0.controlDueDate < $1.controlDueDate }
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
