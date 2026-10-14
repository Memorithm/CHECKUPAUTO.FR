import Foundation
import AuthenticationServices
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
    @Published private(set) var localActivityTestTransitionPending = false
    @Published private(set) var localActivityTestNotice: String?
    @Published var selectedHorn = CheckupControlHornChoice.current {
        didSet { selectedHorn.save() }
    }
    private var localActivityTestTask: Task<Void, Never>?
    @Published private(set) var claimNotice: String?
    @Published private(set) var mobileConfig = MobileBootstrap.fallback
    @Published private(set) var remotePushRegistered = DeviceRegistrationState.isRegistered()
    @Published private(set) var deletingAllData = false
    @Published private(set) var customerSignedIn = false
    @Published private(set) var authenticationResolving = true
    @Published private(set) var sessionRecoveryRequired = false
    @Published private(set) var accountVehicles: [CustomerAccountVehicle] = []
    @Published private(set) var accountProfile: CustomerAccountProfile?
    private var restoringCustomerSession = false
    private var appleSignInNonce: String?
    private var prefetchedAppleSignInNonce: (value: String, fetchedAt: Date)?
    @Published private(set) var installationRegistrationSuppressed =
        InstallationLifecycleState.isAutoRegistrationSuppressed()

    private let scheduler = ReminderScheduler()
    private let hornPreview = CheckupControlHornPreview()
    private let googleCustomerSignIn = GoogleCustomerSignIn()

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
            await restoreCustomerSession()
            await prefetchAppleSignInNonce()
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

    func prepareAppleSignIn(_ request: ASAuthorizationAppleIDRequest) {
        // Nonce serveur pré-chargé si disponible ; sinon nonce local, accepté
        // tant que CYBERCHECK_APPLE_SERVER_NONCE_REQUIRED n'est pas activé.
        // Le serveur le garde 10 minutes : au-delà de 8, on n'utilise plus le pré-chargé.
        let fresh = prefetchedAppleSignInNonce.flatMap { Date().timeIntervalSince($0.fetchedAt) < 480 ? $0.value : nil }
        let nonce = fresh ?? AppleSignInNonce.make()
        prefetchedAppleSignInNonce = nil
        appleSignInNonce = nonce
        request.requestedScopes = [.fullName, .email]
        request.nonce = AppleSignInNonce.sha256(nonce)
    }

    func completeAppleSignIn(_ result: Result<ASAuthorization, Error>) {
        Task {
            do {
                let authorization = try result.get()
                guard let credential = authorization.credential as? ASAuthorizationAppleIDCredential else {
                    throw URLError(.userAuthenticationRequired)
                }
                guard let nonce = appleSignInNonce else { throw URLError(.userAuthenticationRequired) }
                appleSignInNonce = nil
                let payload = try AppleSignInCredentialMapper.payload(from: credential, nonce: nonce)
                _ = try await AppleSignInClient.authenticate(payload)
                customerSignedIn = true
                sessionRecoveryRequired = false
                authenticationResolving = false
                errorMessage = nil
                await refreshNativeAccount()
            } catch {
                customerSignedIn = false
                errorMessage = "La connexion avec Apple n’a pas pu être finalisée."
            }
            await prefetchAppleSignInNonce()
        }
    }

    /// Pré-charge un nonce serveur : la requête Apple est préparée de façon synchrone.
    func prefetchAppleSignInNonce() async {
        guard !customerSignedIn else { return }
        if let nonce = try? await AppleSignInNonceClient.fetch() {
            prefetchedAppleSignInNonce = (nonce, Date())
        }
    }

    func signInWithGoogle() {
        Task {
            do {
                try await googleCustomerSignIn.start()
                customerSignedIn = CustomerSessionKeychain.load() != nil
                guard customerSignedIn else { throw URLError(.userAuthenticationRequired) }
                sessionRecoveryRequired = false
                authenticationResolving = false
                errorMessage = nil
                await refreshNativeAccount()
            } catch {
                errorMessage = "La connexion avec Google n’a pas pu être finalisée."
            }
        }
    }

    func signInWithEmail(_ email: String, password: String) async throws {
        try await EmailCustomerAuthClient.signIn(email: email, password: password)
        customerSignedIn = CustomerSessionKeychain.load() != nil
        guard customerSignedIn else { throw URLError(.userAuthenticationRequired) }
        sessionRecoveryRequired = false
        authenticationResolving = false
        errorMessage = nil
        await refreshNativeAccount()
    }

    /// A foreground resume must not sign out an already authenticated client
    /// because of a timeout, a 503, or temporary radio/network unavailability.
    /// Only an authoritative 401 (or explicit logout) invalidates the session.
    private func restoreCustomerSession() async {
        guard !restoringCustomerSession else { return }
        restoringCustomerSession = true
        let previouslySignedIn = customerSignedIn
        if !previouslySignedIn { authenticationResolving = true }
        defer {
            restoringCustomerSession = false
            authenticationResolving = false
        }
        guard let requestedToken = CustomerSessionKeychain.load() else {
            accountVehicles = []
            accountProfile = nil
            customerSignedIn = false
            sessionRecoveryRequired = false
            return
        }
        do {
            let accepted = try await CustomerAccountAPI.validateStoredSession()
            // A login may have replaced the token while the HTTP call was in
            // flight. The stale result must not change the new account state.
            guard CustomerSessionKeychain.load() == requestedToken else { return }
            if accepted {
                customerSignedIn = true
                sessionRecoveryRequired = false
                errorMessage = nil
                await refreshNativeAccount()
            } else {
                signOutCustomer()
            }
        } catch {
            guard CustomerSessionKeychain.load() == requestedToken else { return }
            if !previouslySignedIn {
                customerSignedIn = false
                sessionRecoveryRequired = true
            }
            // Retain the verified foreground session and its profile/vehicles.
            errorMessage = "Connexion temporairement indisponible. Votre session a été conservée."
        }
    }

    func retryCustomerSession() {
        Task { await restoreCustomerSession() }
    }

    func refreshNativeAccount() async {
        guard customerSignedIn else { return }
        await refreshAccountProfile()
        await refreshAccountVehicles()
    }

    private func refreshAccountProfile() async {
        guard customerSignedIn, let originalToken = CustomerSessionKeychain.load() else { return }
        do {
            let profile = try await CustomerAccountAPI.fetchProfile()
            guard CustomerSessionKeychain.load() == originalToken else { return }
            accountProfile = profile
        } catch CustomerAccountAPIError.sessionExpired {
            if CustomerSessionKeychain.load() == originalToken { signOutCustomer() }
        } catch {
            // A network outage must not erase an already retrieved profile.
            errorMessage = "Informations de compte momentanément indisponibles."
        }
    }

    private func refreshAccountVehicles() async {
        guard customerSignedIn, let originalToken = CustomerSessionKeychain.load() else { return }
        do {
            let vehicles = try await CustomerAccountAPI.fetchOwnedVehicles()
            guard CustomerSessionKeychain.load() == originalToken else { return }
            accountVehicles = vehicles
            // The account's date is authoritative for an already-linked car;
            // keep device-only reminders but realign their CT-based schedule.
            let accountDueDates = Dictionary(
                uniqueKeysWithValues: vehicles.compactMap { vehicle -> (String, Date)? in
                    guard let due = vehicle.nextControlDueDate else { return nil }
                    return (vehicle.registration, due)
                }
            )
            var changed = false
            for index in self.vehicles.indices {
                let registration = self.vehicles[index].registration
                if let due = accountDueDates[registration],
                   !Calendar.current.isDate(self.vehicles[index].controlDueDate, inSameDayAs: due) {
                    self.vehicles[index].controlDueDate = due
                    changed = true
                }
            }
            if changed {
                self.vehicles.sort { $0.controlDueDate < $1.controlDueDate }
                persist()
                await rescheduleAll()
            }
        } catch CustomerAccountAPIError.sessionExpired {
            if CustomerSessionKeychain.load() == originalToken { signOutCustomer() }
        } catch {
            // Keep the last verified vehicle list on temporary network errors.
            errorMessage = "Vos véhicules sont temporairement indisponibles."
        }
    }

    func signOutCustomer() {
        CustomerSessionKeychain.clear()
        accountVehicles = []
        accountProfile = nil
        customerSignedIn = false
        sessionRecoveryRequired = false
        authenticationResolving = false
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
                await scheduler.cancelIslandHornTest()
                localReminderNotice = nil
                VehicleDeadlineStore.clear()
                AuthoritativeInventoryStore.clear()
                #if canImport(ActivityKit)
                if #available(iOS 17.0, *) {
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
        if customerSignedIn {
            Task { await restoreCustomerSession() }
        } else if CustomerSessionKeychain.load() != nil {
            Task { await restoreCustomerSession() }
        }
        #if canImport(ActivityKit)
        if #available(iOS 17.0, *) {
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

    func previewControlHorn() {
        do {
            try hornPreview.play(choice: selectedHorn)
            errorMessage = nil
            localActivityTestNotice = "Écoute du klaxon. Le mode silencieux et le volume des alertes restent ceux de l’iPhone."
        } catch {
            errorMessage = "Le klaxon n’a pas pu être lancé : " + error.localizedDescription
        }
    }

    func startLocalActivityTest() {
        #if canImport(ActivityKit)
        guard #available(iOS 17.0, *) else {
            errorMessage = "Le test Dynamic Island demande iOS 17 ou une version ultérieure."
            return
        }
        guard !localActivityTestTransitionPending else { return }

        localActivityTestTask?.cancel()
        localActivityTestTransitionPending = true
        localActivityTestRunning = true
        localActivityTestNotice = nil
        localActivityTestTask = Task { [weak self] in
            guard let self else { return }
            do {
                await self.scheduler.cancelIslandHornTest()
                let endsAt = try await CheckupControlLiveActivityCoordinator.startLocalTest()
                let hornNotice: String
                do {
                    self.notificationAuthorized = try await self.scheduler.requestAuthorization()
                    guard self.notificationAuthorized else { throw IslandHornTestError.notificationsDisabled }
                    try await self.scheduler.scheduleIslandHornTest()
                    hornNotice = "Klaxon programmé dans cinq secondes."
                } catch {
                    hornNotice = "Klaxon non programmé : " + error.localizedDescription
                }
                try Task.checkCancellation()

                self.localActivityTestTransitionPending = false
                self.errorMessage = nil
                self.localActivityTestNotice = "La voiture et le rappel sont affichés. " + hornNotice + " Maintenez la Dynamic Island pour lire le message complet."

                while Date() < endsAt {
                    do {
                        try await Task.sleep(
                            for: .seconds(2)
                        )
                    } catch {
                        return
                    }
                    guard !Task.isCancelled, Date() < endsAt else { break }
                    guard CheckupControlLiveActivityCoordinator.hasActiveLocalTest() else { break }
                }
                guard !Task.isCancelled else { return }
                self.localActivityTestTransitionPending = true
                await self.scheduler.cancelIslandHornTest()
                await CheckupControlLiveActivityCoordinator.endLocalTest()
                self.localActivityTestTask = nil
                self.localActivityTestTransitionPending = false
                self.localActivityTestRunning = false
                self.localActivityTestNotice = "Test Dynamic Island terminé."
            } catch is CancellationError {
                await self.scheduler.cancelIslandHornTest()
                await CheckupControlLiveActivityCoordinator.endLocalTest()
                self.localActivityTestTransitionPending = false
                self.localActivityTestRunning = false
            } catch {
                self.localActivityTestTransitionPending = false
                self.localActivityTestRunning = false
                self.errorMessage = error.localizedDescription
            }
        }
        #else
        errorMessage = "Les Activités en direct ne sont pas disponibles sur cet appareil."
        #endif
    }

    func stopLocalActivityTest() {
        #if canImport(ActivityKit)
        guard #available(iOS 17.0, *) else { return }
        guard !localActivityTestTransitionPending else { return }

        localActivityTestTransitionPending = true
        let scheduler = self.scheduler
        let taskToCancel = localActivityTestTask
        taskToCancel?.cancel()
        localActivityTestTask = Task { [weak self] in
            await taskToCancel?.value
            await scheduler.cancelIslandHornTest()
            await CheckupControlLiveActivityCoordinator.endLocalTest()

            guard let self else { return }
            self.localActivityTestTask = nil
            self.localActivityTestTransitionPending = false
            self.localActivityTestRunning = false
            self.localActivityTestNotice = "Test Dynamic Island arrêté."
        }
        #endif
    }

    func acknowledgeControlLiveActivity(reminderId: String?) {
        #if canImport(ActivityKit)
        if #available(iOS 17.0, *) {
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
        MobileAPI.bookingJourneyURL()
    }

    var accountURL: URL {
        MobileAPI.websiteURL(URL(string: mobileConfig.account?.url ?? MobileBootstrap.fallback.account?.url ?? "https://www.checkupauto.fr/compte")
            ?? URL(string: "https://www.checkupauto.fr/compte")!)
    }

    var reportScanURL: URL {
        MobileAPI.websiteURL(URL(string: mobileConfig.account?.reportScanUrl ?? MobileBootstrap.fallback.account?.reportScanUrl ?? "https://www.checkupauto.fr/compte#ct-report")
            ?? URL(string: "https://www.checkupauto.fr/compte#ct-report")!)
    }

    var nextControlDueDate: Date? {
        let account = accountVehicles.compactMap(\.nextControlDueDate)
        let accountPlatesWithDueDate = Set(
            accountVehicles.filter { $0.nextControlDueDate != nil }.map(\.registration)
        )
        let local = vehicles
            .filter { !accountPlatesWithDueDate.contains($0.registration) }
            .map(\.controlDueDate)
        let authoritative = authoritativeVehicles.compactMap(\.dueDateValue)
        return (account + local + authoritative).min()
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
                if #available(iOS 17.0, *), let reference = vehicle.bindingUUID {
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
        if #available(iOS 17.0, *) {
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

