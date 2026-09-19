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
    @Published private(set) var remotePushRegistered = DeviceRegistrationState.isRegistered()
    @Published private(set) var deletingAllData = false
    @Published private(set) var installationRegistrationSuppressed =
        InstallationLifecycleState.isAutoRegistrationSuppressed()

    private let scheduler = ReminderScheduler()

    private var useLocalFallback: Bool {
        mobileConfig.notifications.localFallback || !remotePushRegistered
    }

    init() {
        load()
        Task {
            try? await DeviceRegistrationClient.registerInstallation()
            installationRegistrationSuppressed =
                InstallationLifecycleState.isAutoRegistrationSuppressed()
            await refreshMobileConfig()
            await refreshNotificationState()
            refreshRegistrationState()
            await rescheduleAll()
            await syncRemoteDeadlines()
        }
    }

    func requestNotifications() {
        Task {
            do {
                notificationAuthorized = try await scheduler.requestAuthorization()
                if notificationAuthorized {
                    _ = try await DeviceRegistrationClient.registerInstallation(reactivate: true)
                    installationRegistrationSuppressed =
                        InstallationLifecycleState.isAutoRegistrationSuppressed()
                    DeviceRegistrationState.setRegistered(false)
                    refreshRegistrationState()
                    registerForRemoteNotifications()
                    await rescheduleAll()
                } else {
                    await disableRemoteRegistration()
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
            if notificationAuthorized {
                do {
                    if useLocalFallback {
                        try await scheduler.reschedule(vehicle, policy: mobileConfig.reminders)
                    } else {
                        await scheduler.remove(vehicle, leadDays: mobileConfig.reminders.leadDays)
                    }
                } catch {
                    errorMessage = "Le véhicule est enregistré, mais les rappels n’ont pas pu être programmés."
                }
            }
            await syncRemoteDeadlines()
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
            await syncRemoteDeadlines()
        }
    }

    func consumeVehicleClaim(url: URL) {
        Task {
            do {
                let token = try VehicleClaimLink.token(from: url)
                _ = try await VehicleClaimClient.consume(token: token)
                installationRegistrationSuppressed =
                    InstallationLifecycleState.isAutoRegistrationSuppressed()
                if notificationAuthorized {
                    registerForRemoteNotifications()
                }
                errorMessage = nil
            } catch {
                errorMessage = "Ce lien de rattachement véhicule est invalide ou a expiré."
            }
        }
    }

    func deleteAllData() {
        guard !deletingAllData else { return }
        Task {
            deletingAllData = true
            defer { deletingAllData = false }
            let existingVehicles = vehicles
            do {
                _ = try await DeviceRegistrationClient.deleteInstallation()
                for vehicle in existingVehicles {
                    await scheduler.remove(
                        vehicle,
                        leadDays: Array(Set(ReminderPlan.defaultLeadDays + mobileConfig.reminders.leadDays))
                    )
                }
                VehicleDeadlineStore.clear()
                vehicles = []
                remotePushRegistered = false
                installationRegistrationSuppressed =
                    InstallationLifecycleState.isAutoRegistrationSuppressed()
                errorMessage = nil
            } catch {
                errorMessage = "La suppression n’a pas pu être confirmée par Checkup Auto. Réessayez avec une connexion Internet."
            }
        }
    }

    func refreshAfterForeground() {
        Task {
            try? await DeviceRegistrationClient.registerInstallation()
            installationRegistrationSuppressed =
                InstallationLifecycleState.isAutoRegistrationSuppressed()
            await refreshMobileConfig()
            await refreshNotificationState()
            refreshRegistrationState()
            await rescheduleAll()
            await syncRemoteDeadlines()
        }
    }

    func refreshRegistrationState() {
        remotePushRegistered = DeviceRegistrationState.isRegistered()
        Task {
            await rescheduleAll()
        }
    }

    var remotePushActiveForDevice: Bool {
        notificationAuthorized &&
            mobileConfig.notifications.remotePushActive &&
            remotePushRegistered
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
                if useLocalFallback {
                    try await scheduler.reschedule(vehicle, policy: mobileConfig.reminders)
                } else {
                    await scheduler.remove(
                        vehicle,
                        leadDays: Array(Set(ReminderPlan.defaultLeadDays + mobileConfig.reminders.leadDays))
                    )
                }
            } catch {
                errorMessage = "Certains rappels n’ont pas pu être reprogrammés."
            }
        }
    }

    private func refreshNotificationState() async {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        notificationAuthorized = settings.authorizationStatus == .authorized ||
            settings.authorizationStatus == .provisional
        if notificationAuthorized {
            if !installationRegistrationSuppressed {
                registerForRemoteNotifications()
            }
        } else {
            await disableRemoteRegistration()
        }
    }

    private func registerForRemoteNotifications() {
        #if canImport(UIKit)
        UIApplication.shared.registerForRemoteNotifications()
        #endif
    }

    private func syncRemoteDeadlines() async {
        guard notificationAuthorized, remotePushRegistered else { return }
        do {
            try await MobileDeadlineSyncClient.sync(
                vehicles: vehicles,
                timezone: mobileConfig.reminders.timezone
            )
        } catch {
            // Remote push is an optional channel. Local reminders remain the safe fallback.
        }
    }

    private func disableRemoteRegistration() async {
        DeviceRegistrationState.setRegistered(false)
        refreshRegistrationState()
        _ = try? await DeviceRegistrationClient.unregister()
        for vehicle in vehicles {
            await scheduler.remove(
                vehicle,
                leadDays: Array(Set(ReminderPlan.defaultLeadDays + mobileConfig.reminders.leadDays))
            )
        }
    }

    private func load() {
        vehicles = VehicleDeadlineStore.load()
    }

    private func persist() {
        VehicleDeadlineStore.save(vehicles)
    }
}
