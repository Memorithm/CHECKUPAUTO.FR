import Foundation

@main
struct MobileDeadlineSyncSmoke {
    static func main() throws {
        var components = DateComponents()
        components.calendar = Calendar(identifier: .gregorian)
        components.timeZone = TimeZone(identifier: "Europe/Paris")
        components.year = 2027
        components.month = 1
        components.day = 15
        components.hour = 12
        let vehicle = VehicleDeadline(
            id: UUID(uuidString: "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca")!,
            registration: "AA-123-AA",
            displayName: "Mon véhicule",
            controlDueDate: components.date!
        )
        let request = try MobileDeadlineSyncClient.request(
            vehicles: [vehicle],
            timezone: "Europe/Paris",
            identity: ("60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1", String(repeating: "A", count: 43))
        )
        precondition(request.deadlines.count == 1)
        precondition(request.deadlines[0].deadlineId == "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca")
        precondition(request.deadlines[0].dueDate == "2027-01-15")
        let encoded = try JSONEncoder().encode(request)
        let text = String(data: encoded, encoding: .utf8)!
        precondition(!text.contains("AA-123-AA"))
        precondition(!text.contains("Mon véhicule"))
        print("MOBILE_DEADLINE_SYNC_SMOKE_OK")
    }
}
