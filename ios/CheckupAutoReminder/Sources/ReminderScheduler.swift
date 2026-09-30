import Foundation
import UserNotifications

actor ReminderScheduler {
    private let center = UNUserNotificationCenter.current()

    func requestAuthorization() async throws -> Bool {
        try await center.requestAuthorization(options: [.alert, .badge, .sound])
    }

    func reschedule(_ vehicle: VehicleDeadline, policy: MobileReminderPolicy) async throws {
        await remove(vehicle, leadDays: Array(Set(ReminderPlan.defaultLeadDays + policy.leadDays)), includeCustom: false)
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

    func remove(_ vehicle: VehicleDeadline, leadDays: [Int] = ReminderPlan.defaultLeadDays, includeCustom: Bool = true) async {
        var ids = leadDays.map {
            identifier(vehicleID: vehicle.id, days: $0)
        }
        if includeCustom { ids.append(Self.customIdentifier(vehicle.id)) }
        center.removePendingNotificationRequests(withIdentifiers: ids)
        center.removeDeliveredNotifications(withIdentifiers: ids)
    }

    static let islandHornTestIdentifier = "ct.local.test-island.horn"
    static let islandHornTestDelay: TimeInterval = 5

    static func islandHornTestRequest(choice: CheckupControlHornChoice = .current) -> UNNotificationRequest {
        let content = UNMutableNotificationContent()
        content.title = "Test du klaxon Checkup Auto"
        content.body = "Pensez à votre contrôle technique"
        content.sound = UNNotificationSound(named: UNNotificationSoundName(choice.soundName))
        return UNNotificationRequest(
            identifier: islandHornTestIdentifier,
            content: content,
            trigger: UNTimeIntervalNotificationTrigger(timeInterval: islandHornTestDelay, repeats: false)
        )
    }

    func scheduleIslandHornTest() async throws {
        let settings = await center.notificationSettings()
        guard settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional else {
            throw IslandHornTestError.notificationsDisabled
        }
        guard settings.soundSetting == .enabled else { throw IslandHornTestError.soundDisabled }
        guard Bundle.main.url(forResource: CheckupControlActivityPolicy.hornSoundName, withExtension: nil) != nil else {
            throw IslandHornTestError.soundMissing
        }
        cancelIslandHornTest()
        try await center.add(Self.islandHornTestRequest())
    }

    func cancelIslandHornTest() {
        center.removePendingNotificationRequests(withIdentifiers: [Self.islandHornTestIdentifier])
        center.removeDeliveredNotifications(withIdentifiers: [Self.islandHornTestIdentifier])
    }

    static let testIdentifier = "ct.local.test"

    static func customIdentifier(_ vehicleID: UUID) -> String {
        "ct.local.\(vehicleID.uuidString)"
    }

    static func localRequest(identifier: String, date: Date, body: String, now: Date = Date()) throws -> UNNotificationRequest {
        guard let components = LocalReminderPlan.components(for: date, now: now) else {
            throw LocalReminderError.pastDate
        }
        let content = UNMutableNotificationContent()
        content.title = identifier == testIdentifier ? "Test de rappel Checkup Auto" : "Rappel Checkup Auto"
        content.body = body
        content.sound = .default
        return UNNotificationRequest(identifier: identifier, content: content,
            trigger: UNCalendarNotificationTrigger(dateMatching: components, repeats: false))
    }

    func rescheduleCustom(_ vehicle: VehicleDeadline) async throws {
        let id = Self.customIdentifier(vehicle.id)
        guard let date = vehicle.localReminderAt, LocalReminderPlan.components(for: date) != nil else {
            center.removePendingNotificationRequests(withIdentifiers: [id])
            return
        }
        let name = vehicle.displayName.isEmpty ? vehicle.registration : vehicle.displayName
        let request = try Self.localRequest(identifier: id, date: date,
            body: "\(name) : c’est l’heure du rappel que vous avez choisi.")
        try await center.add(request)
    }

    func scheduleTest(at date: Date) async throws {
        let request = try Self.localRequest(identifier: Self.testIdentifier, date: date,
            body: "Votre notification locale fonctionne. Ce test ne dépend pas du site Internet.")
        try await center.add(request)
    }

    func cancelTest() {
        center.removePendingNotificationRequests(withIdentifiers: [Self.testIdentifier])
        center.removeDeliveredNotifications(withIdentifiers: [Self.testIdentifier])
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

enum LocalReminderError: LocalizedError {
    case pastDate
    var errorDescription: String? { "Choisissez une date et une heure à venir." }
}

enum IslandHornTestError: LocalizedError {
    case notificationsDisabled, soundDisabled, soundMissing

    var errorDescription: String? {
        switch self {
        case .notificationsDisabled: return "Autorisez les notifications Checkup Auto pour entendre le klaxon."
        case .soundDisabled: return "Activez les sons des notifications Checkup Auto dans Réglages."
        case .soundMissing: return "Le fichier du klaxon est absent de l’application."
        }
    }
}
