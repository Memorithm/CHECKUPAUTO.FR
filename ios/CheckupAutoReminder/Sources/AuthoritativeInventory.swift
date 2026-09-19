import Foundation

struct AuthoritativeInventoryRequest: Codable, Equatable, Sendable {
    let installationId: String
    let registrationSecret: String

    func validated() throws -> AuthoritativeInventoryRequest {
        guard UUID(uuidString: installationId)?.uuidString.lowercased() == installationId.lowercased() else {
            throw AuthoritativeInventoryError.invalidIdentity
        }
        let allowed = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
        guard (32...128).contains(registrationSecret.count),
              registrationSecret.unicodeScalars.allSatisfy(allowed.contains) else {
            throw AuthoritativeInventoryError.invalidIdentity
        }
        return self
    }
}

struct AuthoritativeVehicleDeadline: Codable, Equatable, Hashable, Identifiable, Sendable {
    let bindingId: String
    let dueDate: String?

    var id: String { bindingId }

    func validated() throws -> AuthoritativeVehicleDeadline {
        guard UUID(uuidString: bindingId)?.uuidString.lowercased() == bindingId.lowercased() else {
            throw AuthoritativeInventoryError.invalidResponse
        }
        if let dueDate, AuthoritativeInventoryDate.date(from: dueDate) == nil {
            throw AuthoritativeInventoryError.invalidResponse
        }
        return self
    }

    var dueDateValue: Date? { dueDate.flatMap(AuthoritativeInventoryDate.date(from:)) }
    var bindingUUID: UUID? { UUID(uuidString: bindingId) }
}

struct AuthoritativeInventoryResponse: Codable, Equatable, Sendable {
    let ok: Bool
    let vehicles: [AuthoritativeVehicleDeadline]
    let source: String

    func validated() throws -> AuthoritativeInventoryResponse {
        guard ok, source == "mercure", vehicles.count <= 24 else {
            throw AuthoritativeInventoryError.invalidResponse
        }
        let checked = try vehicles.map { try $0.validated() }
        guard Set(checked.map(\.bindingId)).count == checked.count else {
            throw AuthoritativeInventoryError.invalidResponse
        }
        return AuthoritativeInventoryResponse(ok: true, vehicles: checked, source: source)
    }
}

enum AuthoritativeInventoryError: Error {
    case invalidIdentity
    case invalidResponse
}

enum AuthoritativeInventoryDate {
    static func date(from raw: String) -> Date? {
        let parts = raw.split(separator: "-")
        guard parts.count == 3,
              let year = Int(parts[0]),
              let month = Int(parts[1]),
              let day = Int(parts[2]),
              (2020...2100).contains(year) else { return nil }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Europe/Paris")!
        var components = DateComponents()
        components.calendar = calendar
        components.timeZone = calendar.timeZone
        components.year = year
        components.month = month
        components.day = day
        components.hour = 12
        guard let date = calendar.date(from: components),
              calendar.component(.year, from: date) == year,
              calendar.component(.month, from: date) == month,
              calendar.component(.day, from: date) == day else { return nil }
        return date
    }
}

enum AuthoritativeInventoryReconciliation {
    static func remindersToRemove(
        previous: [AuthoritativeVehicleDeadline],
        next: [AuthoritativeVehicleDeadline]
    ) -> [AuthoritativeVehicleDeadline] {
        let nextByBinding = Dictionary(
            uniqueKeysWithValues: next.map { ($0.bindingId, $0) }
        )
        return previous.filter { old in
            guard let current = nextByBinding[old.bindingId] else {
                return true
            }
            return old.dueDate != nil && current.dueDate == nil
        }
    }
}

enum AuthoritativeInventoryStore {
    static let storageKey = "checkupauto.authoritative.inventory.v1"

    static func load(defaults: UserDefaults = .standard) -> [AuthoritativeVehicleDeadline] {
        guard let data = defaults.data(forKey: storageKey),
              let decoded = try? JSONDecoder().decode([AuthoritativeVehicleDeadline].self, from: data) else {
            return []
        }
        return decoded.compactMap { try? $0.validated() }
    }

    static func save(_ vehicles: [AuthoritativeVehicleDeadline], defaults: UserDefaults = .standard) {
        guard let data = try? JSONEncoder().encode(vehicles) else { return }
        defaults.set(data, forKey: storageKey)
    }

    static func clear(defaults: UserDefaults = .standard) {
        defaults.removeObject(forKey: storageKey)
    }
}

enum AuthoritativeInventoryClient {
    static var endpoint: URL { MobileAPI.endpoint("/api/mobile/inventory") }

    static func fetch(session: URLSession = .shared) async throws -> AuthoritativeInventoryResponse {
        guard let identity = DeviceRegistrationIdentity.loadExisting() else {
            return AuthoritativeInventoryResponse(ok: true, vehicles: [], source: "mercure")
        }
        let payload = try AuthoritativeInventoryRequest(
            installationId: identity.installationId,
            registrationSecret: identity.secret
        ).validated()
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = 8
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONEncoder().encode(payload)
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw AuthoritativeInventoryError.invalidResponse
        }
        return try JSONDecoder().decode(AuthoritativeInventoryResponse.self, from: data).validated()
    }
}
