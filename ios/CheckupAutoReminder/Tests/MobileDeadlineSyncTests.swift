import Foundation
import XCTest
@testable import CheckupAutoReminder

final class MobileDeadlineSyncTests: XCTestCase {
    func testRequestContainsOnlyOpaqueDeadlineIdentityAndDate() throws {
        var components = DateComponents()
        components.calendar = Calendar(identifier: .gregorian)
        components.timeZone = TimeZone(identifier: "Europe/Paris")
        components.year = 2027
        components.month = 1
        components.day = 15
        components.hour = 12
        let dueDate = try XCTUnwrap(components.date)
        let vehicle = VehicleDeadline(
            id: UUID(uuidString: "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca")!,
            registration: "AA-123-AA",
            displayName: "Mon véhicule",
            controlDueDate: dueDate
        )
        let request = try MobileDeadlineSyncClient.request(
            vehicles: [vehicle],
            timezone: "Europe/Paris",
            identity: ("60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1", String(repeating: "A", count: 43))
        )
        XCTAssertEqual(request.deadlines.count, 1)
        XCTAssertEqual(request.deadlines[0].deadlineId, "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca")
        XCTAssertEqual(request.deadlines[0].dueDate, "2027-01-15")
        let encoded = try JSONEncoder().encode(request)
        let text = try XCTUnwrap(String(data: encoded, encoding: .utf8))
        XCTAssertFalse(text.contains("AA-123-AA"))
        XCTAssertFalse(text.contains("Mon véhicule"))
    }

    func testRejectsDuplicateDeadlineIds() {
        let item = MobileDeadlineSyncItem(
            deadlineId: "e62c0b27-2141-4f5c-b2f4-1e458aa6a6ca",
            dueDate: "2027-01-15"
        )
        let request = MobileDeadlineSyncRequest(
            installationId: "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1",
            registrationSecret: String(repeating: "A", count: 43),
            deadlines: [item, item]
        )
        XCTAssertThrowsError(try request.validated())
    }
}
