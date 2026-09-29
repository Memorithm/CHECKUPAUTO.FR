import Foundation
import SwiftUI
import UserNotifications
#if canImport(ActivityKit)
import ActivityKit
#endif
#if canImport(UIKit)
import UIKit
#endif

@MainActor
final class AppModel: ObservableObject {
    @Published private(set) var vehicles: [VehicleDeadline] = []
    @Published private(set) var authoritativeVehicles: [AuthoritativeVehicleDeadline] = []
    @Published private(set) var referralWallets: [ReferralWalletProductStatus] = []
    @Published var notificationAuthorized = false
    @Published var errorMessage: String?
    @Published private(set) var localReminderNotice: String?
    @Published private(set) var schedulingLocalTest = false
    @Published private(set) var localActivityTestRunning = false
    @Published private(set) var localActivityTestNotice: String?
    private var localActivityTestTask: Task<Void, Never>?
    @Published private(set) var claimNotice: String?
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
        authoritativeVehicles = AuthoritativeInventoryStore.load()
        if installationRegistrationSuppressed {
            try? ReferralWalletSnapshotStore.clear()
        } else if let snapshot = ReferralWalletSnapshotStore.load() {
            referralWallets = snapshot.wallets
        }
        Task {
            await refreshNotificationState()
            await rescheduleAll()
            try? await DeviceRegistrationClient.registerInstallation()
            installationRegistrationSuppressed =
                InstallationLifecycleState.isAutoRegistrationSuppressed()
            await refreshMobileConfig()
            await refreshAuthoritativeInventory()
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
                    await rescheduleAll()
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
    func add(registration: String, name: String, dueDate: Date, reminderAt: Date? = nil) {
        let vehicle = VehicleDeadline(
            registration: registration,
            displayName: name,
            controlDueDate: dueDate,
            localReminderAt: reminderAt
        )
        vehicles.append(vehicle)
        vehicles.sort { $0.controlDueDate < $1.controlDueDate }
        persist()
        Task {
            if reminderAt != nil {
                do { notificationAuthorized = try await scheduler.requestAuthorization() }
                catch { errorMessage = error.localizedDescription }
            }
            if notificationAuthorized {
                do {
                    if let date = reminderAt, LocalReminderPlan.components(for: date) == nil {
                        throw LocalReminderError.pastDate
                    }
                    if useLocalFallback {
                        try await scheduler.reschedule(vehicle, policy: mobileConfig.reminders)
                    } else {
                        await scheduler.remove(vehicle, leadDays: mobileConfig.reminders.leadDays, includeCustom: false)
                    }
                    try await scheduler.rescheduleCustom(vehicle)
                    if let date = reminderAt {
                        localReminderNotice = "Rappel programmé le " + date.formatted(date: .abbreviated, time: .shortened)
                    }
                } catch {
                    errorMessage = "Le véhicule est enregistré, mais les rappels n’ont pas pu être programmés."
                }
            }
            if reminderAt != nil && !notificationAuthorized {
                errorMessage = "Véhicule enregistré. Autorisez les notifications dans Réglages pour recevoir son rappel."
            }
            await syncRemoteDeadlines()
        }
    }

    func scheduleLocalTest(at date: Date) {
        guard !schedulingLocalTest else { return }
        schedulingLocalTest = true
        localReminderNotice = nil
        Task {
            defer { schedulingLocalTest = false }
            do {
                guard LocalReminderPlan.components(for: date) != nil else { throw LocalReminderError.pastDate }
                notificationAuthorized = try await scheduler.requestAuthorization()
                guard notificationAuthorized else {
                    errorMessage = "Autorisez les notifications Checkup Auto dans Réglages pour recevoir le test."
                    return
                }
                try await scheduler.scheduleTest(at: date)
                errorMessage = nil
                localReminderNotice = "Test programmé le " + date.formatted(date: .abbreviated, time: .shortened)
            } catch {
                errorMessage = "Test non programmé : " + error.localizedDescription
            }
        }
    }

    func cancelLocalTest() {
        Task {
            await scheduler.cancelTest()
            localReminderNotice = "Test annulé."
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

    func delete(vehicleID: UUID) {
        guard let index = vehicles.firstIndex(where: { $0.id == vehicleID }) else { return }
        let removed = vehicles.remove(at: index)
        persist()
        Task {
            await scheduler.remove(
                removed,
                leadDays: Array(Set(ReminderPlan.defaultLeadDays + mobileConfig.reminders.leadDays))
            )
            await syncRemoteDeadlines()
        }
    }

    func consumeMobileClaim(url: URL) {
        Task {
            do {
                let claim = try MobileClaimLink.claim(from: url)
                switch claim.kind {
                case .vehicle:
                    _ = try await VehicleClaimClient.consume(token: claim.token)
                    installationRegistrationSuppressed =
                        InstallationLifecycleState.isAutoRegistrationSuppressed()
                    await refreshAuthoritativeInventory()
                    Task { await self.refreshAuthoritativeInventoryAfterVehicleClaim() }
                    if notificationAuthorized {
                        registerForRemoteNotifications()
                    }
                    await rescheduleAll()
                    claimNotice = "Véhicule rattaché à cet iPhone."
                case .referralWallet:
                    let response = try await ReferralWalletClaimClient.consume(token: claim.token)
                    installationRegistrationSuppressed =
                        InstallationLifecycleState.isAutoRegistrationSuppressed()
                    if let status = response.walletStatus {
                        let snapshot = ReferralWalletVerifiedSnapshot(
                            wallets: status.wallets,
                            verifiedAt: response.claimedAt
                        )
                        referralWallets = snapshot.wallets
                        try? ReferralWalletSnapshotStore.save(snapshot)
                    } else {
                        referralWallets = []
                        try? ReferralWalletSnapshotStore.clear()
                    }
                    if notificationAuthorized {
                        registerForRemoteNotifications()
                    }
                    claimNotice = "Cagnotte rattachée à cet iPhone."
                }
                errorMessage = nil
            } catch {
                claimNotice = nil
                errorMessage = "Ce lien de rattachement est invalide ou a expiré."
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
                try ReferralWalletSnapshotStore.clear()
                for vehicle in existingVehicles {
                    await scheduler.remove(
                        vehicle,
                        leadDays: Array(Set(ReminderPlan.defaultLeadDays + mobileConfig.reminders.leadDays))
                    )
                }
                for vehicle in authoritativeVehicles {
                    await scheduler.removeAuthoritative(
                        vehicle,
                        leadDays: Array(Set(ReminderPlan.defaultLeadDays + mobileConfig.reminders.leadDays))
                    )
                }
                await scheduler.cancelTest()
                localReminderNotice = nil
                VehicleDeadlineStore.clear()
                AuthoritativeInventoryStore.clear()
                #if canImport(ActivityKit)
                if #available(iOS 26.0, *) {
                    await CheckupControlLiveActivityCoordinator.clearAll()
                }
                #endif
                vehicles = []
                authoritativeVehicles = []
                referralWallets = []
                remotePushRegistered = false
                claimNotice = nil
                installationRegistrationSuppressed =
                    InstallationLifecycleState.isAutoRegistrationSuppressed()
                errorMessage = nil
            } catch {
                errorMessage = "La suppression n’a pas pu être confirmée par Checkup Auto. Réessayez avec une connexion Internet."
            }
        }
    }

    func refreshAfterForeground() {
        #if canImport(ActivityKit)
        if #available(iOS 26.0, *) {
            Task {
                await CheckupControlLiveActivityCoordinator.endExpiredLocalTests()
                localActivityTestRunning = Activity<CheckupControlActivityAttributes>.activities
                    .contains { $0.attributes.kind == .localTest }
            }
        }
        #endif
        Task {
            await refreshNotificationState()
            await rescheduleAll()
            try? await DeviceRegistrationClient.registerInstallation()
            installationRegistrationSuppressed =
                InstallationLifecycleState.isAutoRegistrationSuppressed()
            await refreshMobileConfig()
            await refreshAuthoritativeInventory()
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

    func startLocalActivityTest() {
        #if canImport(ActivityKit)
        guard #available(iOS 26.0, *) else {
            errorMessage = "Le test Dynamic Island demande iOS 26 ou une version ultérieure."
            return
        }
        localActivityTestTask?.cancel()
        localActivityTestRunning = true
        localActivityTestNotice = nil
        Task {
            do {
                _ = try await CheckupControlLiveActivityCoordinator.startLocalTest()
                errorMessage = nil
                localActivityTestNotice = "Test Dynamic Island lancé pour 2 minutes."
                localActivityTestTask = Task { [weak self] in
                    do { try await Task.sleep(for: .seconds(120)) } catch { return }
                    await CheckupControlLiveActivityCoordinator.endLocalTest()
                    self?.localActivityTestRunning = false
                    self?.localActivityTestNotice = "Test Dynamic Island terminé."
                }
            } catch {
                localActivityTestRunning = false
                errorMessage = error.localizedDescription
            }
        }
        #else
        errorMessage = "Les Activités en direct ne sont pas disponibles sur cet appareil."
        #endif
    }

    func stopLocalActivityTest() {
        localActivityTestTask?.cancel()
        localActivityTestTask = nil
        #if canImport(ActivityKit)
        if #available(iOS 26.0, *) {
            Task {
                await CheckupControlLiveActivityCoordinator.endLocalTest()
                localActivityTestRunning = false
                localActivityTestNotice = "Test Dynamic Island arrêté."
            }
        }
        #endif
    }

    func acknowledgeControlLiveActivity(reminderId: String?) {
        #if canImport(ActivityKit)
        if #available(iOS 26.0, *) {
            Task {
                await CheckupControlLiveActivityCoordinator.acknowledge(reminderId: reminderId)
            }
        }
        #endif
    }


    var remotePushActiveForDevice: Bool {
        notificationAuthorized &&
            mobileConfig.notifications.remotePushActive &&
            remotePushRegistered
    }

    var bookingURL: URL {
        URL(string: mobileConfig.booking.url) ?? URL(string: "https://rdv.checkupauto.fr/")!
    }

    var accountURL: URL {
        URL(string: mobileConfig.account?.url ?? MobileBootstrap.fallback.account?.url ?? "https://www.checkupauto.fr/compte")
            ?? URL(string: "https://www.checkupauto.fr/compte")!
    }

    var reportScanURL: URL {
        URL(string: mobileConfig.account?.reportScanUrl ?? MobileBootstrap.fallback.account?.reportScanUrl ?? "https://www.checkupauto.fr/compte#ct-report")
            ?? URL(string: "https://www.checkupauto.fr/compte#ct-report")!
    }

    var nextControlDueDate: Date? {
        let local = vehicles.map(\.controlDueDate)
        let authoritative = authoritativeVehicles.compactMap(\.dueDateValue)
        return (local + authoritative).min()
    }

    var totalReferralBalanceCents: Int {
        referralWallets.reduce(0) { $0 + $1.balanceCents }
    }

    var totalPendingReferralCents: Int {
        referralWallets.reduce(0) { $0 + $1.pendingCents }
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
                        leadDays: Array(Set(ReminderPlan.defaultLeadDays + mobileConfig.reminders.leadDays)),
                        includeCustom: false
                    )
                }
                try await scheduler.rescheduleCustom(vehicle)
            } catch {
                errorMessage = "Certains rappels n’ont pas pu être reprogrammés."
            }
        }
        for vehicle in authoritativeVehicles {
            do {
                if useLocalFallback {
                    try await scheduler.rescheduleAuthoritative(vehicle, policy: mobileConfig.reminders)
                } else {
                    await scheduler.removeAuthoritative(
                        vehicle,
                        leadDays: Array(Set(ReminderPlan.defaultLeadDays + mobileConfig.reminders.leadDays))
                    )
                }
            } catch {
                errorMessage = "Certains rappels autoritaires n’ont pas pu être reprogrammés."
            }
        }
    }

    private func refreshAuthoritativeInventoryAfterVehicleClaim() async {
        for delaySeconds: UInt64 in [2, 5, 10, 20, 30] {
            try? await Task.sleep(nanoseconds: delaySeconds * 1_000_000_000)
            if Task.isCancelled { return }
            await refreshAuthoritativeInventory()
        }
    }

    private func refreshAuthoritativeInventory() async {
        guard !installationRegistrationSuppressed else { return }
        do {
            let response = try await AuthoritativeInventoryClient.fetch(
                requireFreshAppointments: true
            )
            let stale = AuthoritativeInventoryReconciliation.remindersToRemove(
                previous: authoritativeVehicles,
                next: response.vehicles
            )
            for vehicle in stale {
                await scheduler.removeAuthoritative(
                    vehicle,
                    leadDays: Array(
                        Set(ReminderPlan.defaultLeadDays + mobileConfig.reminders.leadDays)
                    )
                )
                #if canImport(ActivityKit)
                if #available(iOS 26.0, *), let reference = vehicle.bindingUUID {
                    await CheckupControlLiveActivityCoordinator.cancel(reference: reference)
                }
                #endif
            }
            authoritativeVehicles = response.vehicles
            AuthoritativeInventoryStore.save(response.vehicles)
            await scheduleControlLiveActivities()

            if let walletStatus = response.referralWalletStatus {
                if walletStatus.wallets.isEmpty {
                    referralWallets = []
                    try? ReferralWalletSnapshotStore.clear()
                } else {
                    let snapshot = ReferralWalletVerifiedSnapshot(
                        wallets: walletStatus.wallets,
                        verifiedAt: ISO8601DateFormatter().string(from: Date())
                    )
                    referralWallets = snapshot.wallets
                    try? ReferralWalletSnapshotStore.save(snapshot)
                }
            }
        } catch {
            // Preserve the last verified opaque inventory and referral-wallet snapshot
            // when the server is offline or does not yet expose the combined response.
        }
    }

    private func scheduleControlLiveActivities() async {
        #if canImport(ActivityKit)
        if #available(iOS 26.0, *) {
            var retryFailed = false
            for vehicle in authoritativeVehicles {
                guard let reference = vehicle.bindingUUID else { continue }
                guard let appointmentAt = vehicle.appointmentAtValue,
                      appointmentAt > Date() else {
                    await CheckupControlLiveActivityCoordinator.cancel(reference: reference)
                    continue
                }
                do {
                    try await CheckupControlLiveActivityCoordinator.schedule(
                        appointmentAt: appointmentAt,
                        reference: reference
                    )
                } catch {
                    retryFailed = true
                    // A Live Activity is an enhancement. Existing local/APNs reminders remain authoritative fallbacks.
                }
            }
            CheckupControlLiveActivityRetryScheduler.submit(
                for: authoritativeVehicles,
                retryFailed: retryFailed
            )
        }
        #endif
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
