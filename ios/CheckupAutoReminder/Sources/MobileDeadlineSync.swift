import Foundation

struct MobileDeadlineSyncItem: Codable, Equatable, Sendable {
    let deadlineId: String
    let dueDate: String
}

struct MobileDeadlineSyncRequest: Codable, Equatable, Sendable {
    let installationId: String
    let registrationSecret: String
    let deadlines: [MobileDeadlineSyncItem]

    func validated() throws -> MobileDeadlineSyncRequest {
        guard UUID(uuidString: installationId)?.uuidString.lowercased() == installationId.lowercased(),
              deadlines.count <= 24 else {
            throw MobileDeadlineSyncError.invalidPayload
        }
        let unique = Set(deadlines.map(\.deadlineId))
        guard unique.count == deadlines.count else { throw MobileDeadlineSyncError.invalidPayload }
        for item in deadlines {
            guard UUID(uuidString: item.deadlineId)?.uuidString.lowercased() == item.deadlineId.lowercased(),
                  item.dueDate.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil else {
                throw MobileDeadlineSyncError.invalidPayload
            }
        }
        return self
    }
}

enum MobileDeadlineSyncError: Error {
    case invalidPayload
    case invalidResponse
}

enum MobileDeadlineSyncClient {
    static var endpoint: URL { MobileAPI.endpoint("/api/mobile/reminders/sync") }

    static func request(
        vehicles: [VehicleDeadline],
        timezone: String,
        identity: (installationId: String, secret: String)
    ) throws -> MobileDeadlineSyncRequest {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: timezone) ?? TimeZone(identifier: "Europe/Paris")!
        formatter.dateFormat = "yyyy-MM-dd"
        let items = vehicles.map {
            MobileDeadlineSyncItem(
                deadlineId: $0.id.uuidString.lowercased(),
                dueDate: formatter.string(from: $0.controlDueDate)
            )
        }
        return try MobileDeadlineSyncRequest(
            installationId: identity.installationId,
            registrationSecret: identity.secret,
            deadlines: items
        ).validated()
    }

    static func sync(
        vehicles: [VehicleDeadline],
        timezone: String,
        session: URLSession = .shared
    ) async throws {
        let identity = try DeviceRegistrationIdentity.loadOrCreate()
        let payload = try request(vehicles: vehicles, timezone: timezone, identity: identity)
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = 8
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONEncoder().encode(payload)
        let (_, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw MobileDeadlineSyncError.invalidResponse
        }
    }
}
