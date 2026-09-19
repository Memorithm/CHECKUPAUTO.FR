import Foundation
import UserNotifications

actor ReminderScheduler {
    private let center = UNUserNotificationCenter.current()

    func requestAuthorization() async throws -> Bool {
        try await center.requestAuthorization(options: [.alert, .badge, .sound])
    }

    func reschedule(_ vehicle: VehicleDeadline, policy: MobileReminderPolicy) async throws {
        await remove(vehicle, leadDays: Array(Set(ReminderPlan.defaultLeadDays + policy.leadDays)))
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: policy.timezone) ?? .current
        let moments = ReminderPlan.moments(
            dueDate: vehicle.controlDueDate,
            calendar: calendar,
            leadDays: policy.leadDays,
            hour: policy.hour
        )
        for moment in moments {
            let content = UNMutableNotificationContent()
            content.title = "Contrôle technique à prévoir"
            content.body = message(for: vehicle, daysBefore: moment.daysBefore)
            content.sound = .default
            content.categoryIdentifier = NotificationRouting.controlDueCategory
            content.userInfo = ["vehicleID": vehicle.id.uuidString]
            var date = calendar.dateComponents(
                [.year, .month, .day, .hour, .minute],
                from: moment.fireDate
            )
            date.timeZone = calendar.timeZone
            let trigger = UNCalendarNotificationTrigger(dateMatching: date, repeats: false)
            let request = UNNotificationRequest(
                identifier: identifier(vehicleID: vehicle.id, days: moment.daysBefore),
                content: content,
                trigger: trigger
            )
            try await center.add(request)
        }
    }

    func rescheduleAuthoritative(
        _ vehicle: AuthoritativeVehicleDeadline,
        policy: MobileReminderPolicy
    ) async throws {
        guard let bindingID = vehicle.bindingUUID else { return }
        await removeAuthoritative(
            vehicle,
            leadDays: Array(Set(ReminderPlan.defaultLeadDays + policy.leadDays))
        )
        guard let dueDate = vehicle.dueDateValue else { return }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: policy.timezone) ?? .current
        let moments = ReminderPlan.moments(
            dueDate: dueDate,
            calendar: calendar,
            leadDays: policy.leadDays,
            hour: policy.hour
        )
        for moment in moments {
            let content = UNMutableNotificationContent()
            content.title = "Contrôle technique à prévoir"
            content.body = "Votre échéance approche dans \(moment.daysBefore) jour\(moment.daysBefore > 1 ? "s" : ""). Réservez votre contrôle Checkup Auto."
            content.sound = .default
            content.categoryIdentifier = NotificationRouting.controlDueCategory
            content.userInfo = ["bindingID": vehicle.bindingId]
            var date = calendar.dateComponents([.year, .month, .day, .hour, .minute], from: moment.fireDate)
            date.timeZone = calendar.timeZone
            let trigger = UNCalendarNotificationTrigger(dateMatching: date, repeats: false)
            try await center.add(UNNotificationRequest(
                identifier: authoritativeIdentifier(bindingID: bindingID, days: moment.daysBefore),
                content: content,
                trigger: trigger
            ))
        }
    }

    func removeAuthoritative(
        _ vehicle: AuthoritativeVehicleDeadline,
        leadDays: [Int] = ReminderPlan.defaultLeadDays
    ) async {
        guard let bindingID = vehicle.bindingUUID else { return }
        let ids = leadDays.map { authoritativeIdentifier(bindingID: bindingID, days: $0) }
        center.removePendingNotificationRequests(withIdentifiers: ids)
        center.removeDeliveredNotifications(withIdentifiers: ids)
    }

    func remove(_ vehicle: VehicleDeadline, leadDays: [Int] = ReminderPlan.defaultLeadDays) async {
        let ids = leadDays.map {
            identifier(vehicleID: vehicle.id, days: $0)
        }
        center.removePendingNotificationRequests(withIdentifiers: ids)
        center.removeDeliveredNotifications(withIdentifiers: ids)
    }

    private func identifier(vehicleID: UUID, days: Int) -> String {
        "ct.\(vehicleID.uuidString).\(days)"
    }

    private func authoritativeIdentifier(bindingID: UUID, days: Int) -> String {
        "ct.bound.\(bindingID.uuidString).\(days)"
    }

    private func message(for vehicle: VehicleDeadline, daysBefore: Int) -> String {
        let vehicleName = vehicle.displayName.isEmpty ? vehicle.registration : vehicle.displayName
        return "\(vehicleName) : échéance dans \(daysBefore) jour\(daysBefore > 1 ? "s" : ""). Réservez votre contrôle Checkup Auto."
    }
}
