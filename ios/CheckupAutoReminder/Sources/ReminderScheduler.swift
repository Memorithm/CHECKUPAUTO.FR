import Foundation
import UserNotifications

actor ReminderScheduler {
    private let center = UNUserNotificationCenter.current()

    func requestAuthorization() async throws -> Bool {
        try await center.requestAuthorization(options: [.alert, .badge, .sound])
    }

    func reschedule(_ vehicle: VehicleDeadline) async throws {
        await remove(vehicle)
        let moments = ReminderPlan.moments(dueDate: vehicle.controlDueDate)
        for moment in moments {
            let content = UNMutableNotificationContent()
            content.title = "Contrôle technique à prévoir"
            content.body = message(for: vehicle, daysBefore: moment.daysBefore)
            content.sound = .default
            content.userInfo = ["vehicleID": vehicle.id.uuidString]
            var date = Calendar.current.dateComponents(
                [.year, .month, .day, .hour, .minute],
                from: moment.fireDate
            )
            date.timeZone = .current
            let trigger = UNCalendarNotificationTrigger(dateMatching: date, repeats: false)
            let request = UNNotificationRequest(
                identifier: identifier(vehicleID: vehicle.id, days: moment.daysBefore),
                content: content,
                trigger: trigger
            )
            try await center.add(request)
        }
    }

    func remove(_ vehicle: VehicleDeadline) async {
        let ids = ReminderPlan.defaultLeadDays.map {
            identifier(vehicleID: vehicle.id, days: $0)
        }
        center.removePendingNotificationRequests(withIdentifiers: ids)
        center.removeDeliveredNotifications(withIdentifiers: ids)
    }

    private func identifier(vehicleID: UUID, days: Int) -> String {
        "ct.\(vehicleID.uuidString).\(days)"
    }

    private func message(for vehicle: VehicleDeadline, daysBefore: Int) -> String {
        let vehicleName = vehicle.displayName.isEmpty ? vehicle.registration : vehicle.displayName
        return "\(vehicleName) : échéance dans \(daysBefore) jour\(daysBefore > 1 ? "s" : ""). Réservez votre contrôle Checkup Auto."
    }
}
