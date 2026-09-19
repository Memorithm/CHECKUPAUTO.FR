import Foundation
import SwiftUI
import UserNotifications
#if canImport(UIKit)
import UIKit
#endif

@MainActor
final class AppModel: ObservableObject {
    @Published private(set) var vehicles: [VehicleDeadline] = []
    @Published var notificationAuthorized = false
    @Published var errorMessage: String?
    @Published private(set) var mobileConfig = MobileBootstrap.fallback

    private let scheduler = ReminderScheduler()
    private let storageKey = "checkupauto.vehicle.deadlines.v1"

    init() {
        load()
        Task {
            await refreshMobileConfig()
            await refreshNotificationState()
            await rescheduleAll()
        }
    }

    func requestNotifications() {
        Task {
            do {
                notificationAuthorized = try await scheduler.requestAuthorization()
                if notificationAuthorized {
                    registerForRemoteNotifications()
                    await rescheduleAll()
                }
            } catch {
                errorMessage = "Impossible d’activer les notifications : \(error.localizedDescription)"
            }
        }
    }
    func add(registration: String, name: String, dueDate: Date) {
        let vehicle = VehicleDeadline(
            registration: registration,
            displayName: name,
            controlDueDate: dueDate
        )
        vehicles.append(vehicle)
        vehicles.sort { $0.controlDueDate < $1.controlDueDate }
        persist()
        Task {
            do {
                try await scheduler.reschedule(vehicle, policy: mobileConfig.reminders)
            } catch {
                errorMessage = "Le véhicule est enregistré, mais les rappels n’ont pas pu être programmés."
            }
        }
    }

    func delete(at offsets: IndexSet) {
        let removed = offsets.map { vehicles[$0] }
        vehicles.remove(atOffsets: offsets)
        persist()
        Task {
            for vehicle in removed {
                await scheduler.remove(
                    vehicle,
                    leadDays: Array(Set(ReminderPlan.defaultLeadDays + mobileConfig.reminders.leadDays))
                )
            }
        }
    }

    var bookingURL: URL {
        URL(string: mobileConfig.booking.url) ?? URL(string: "https://rdv.checkupauto.fr/")!
    }

    private func refreshMobileConfig() async {
        do {
            mobileConfig = try await MobileBootstrapClient.fetch()
        } catch {
            mobileConfig = .fallback
        }
    }

    private func rescheduleAll() async {
        guard notificationAuthorized else { return }
        for vehicle in vehicles {
            do {
                try await scheduler.reschedule(vehicle, policy: mobileConfig.reminders)
            } catch {
                errorMessage = "Certains rappels n’ont pas pu être reprogrammés."
            }
        }
    }

    private func refreshNotificationState() async {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        notificationAuthorized = settings.authorizationStatus == .authorized ||
            settings.authorizationStatus == .provisional
        if notificationAuthorized { registerForRemoteNotifications() }
    }

    private func registerForRemoteNotifications() {
        #if canImport(UIKit)
        UIApplication.shared.registerForRemoteNotifications()
        #endif
    }

    private func load() {
        guard
            let data = UserDefaults.standard.data(forKey: storageKey),
            let decoded = try? JSONDecoder().decode([VehicleDeadline].self, from: data)
        else { return }
        vehicles = decoded.sorted { $0.controlDueDate < $1.controlDueDate }
    }

    private func persist() {
        guard let data = try? JSONEncoder().encode(vehicles) else { return }
        UserDefaults.standard.set(data, forKey: storageKey)
    }
}
