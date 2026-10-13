import SwiftUI
import UserNotifications
#if canImport(UIKit)
import UIKit

final class CheckupAutoAppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        if CheckupAutoLaunchMode.isJourneyVisualReview {
            return true
        }
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        let book = UNNotificationAction(
            identifier: NotificationRouting.bookAction,
            title: "Réserver",
            options: [.foreground]
        )
        let controlDue = UNNotificationCategory(
            identifier: NotificationRouting.controlDueCategory,
            actions: [book],
            intentIdentifiers: [],
            options: []
        )
        center.setNotificationCategories([controlDue])
        if #available(iOS 17.0, *),
           CheckupControlLiveActivityRetryScheduler.register() {
            CheckupControlLiveActivityRetryScheduler.submit(
                for: AuthoritativeInventoryStore.load()
            )
        }
        return true
    }

    func application(_ application: UIApplication,
                     didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        Task {
            do {
                try await DeviceRegistrationClient.register(deviceToken: deviceToken)
                let config = (try? await MobileBootstrapClient.fetch()) ?? .fallback
                try await MobileDeadlineSyncClient.sync(
                    vehicles: VehicleDeadlineStore.load(),
                    timezone: config.reminders.timezone
                )
            } catch {
                // Registration is retried on the next app launch / authorization refresh.
            }
        }
    }

    func application(
        _ application: UIApplication,
        didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
        DeviceRegistrationState.setRegistered(false)
        Task {
            try? await DeviceRegistrationClient.unregister()
        }
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        [.banner, .sound, .badge]
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        guard response.actionIdentifier == NotificationRouting.bookAction else {
            completionHandler()
            return
        }
        Task {
            let url = MobileAPI.bookingJourneyURL()
            await MainActor.run {
                UIApplication.shared.open(url, options: [:]) { _ in
                    completionHandler()
                }
            }
        }
    }

}
#endif

enum CheckupAutoLaunchMode {
    static func isJourneyVisualReview(arguments: [String]) -> Bool {
        #if DEBUG
        arguments.contains("--journey-visual-review")
        #else
        false
        #endif
    }

    static var isJourneyVisualReview: Bool {
        isJourneyVisualReview(arguments: ProcessInfo.processInfo.arguments)
    }
}

@main
struct CheckupAutoReminderApp: App {
    #if canImport(UIKit)
    @UIApplicationDelegateAdaptor(CheckupAutoAppDelegate.self) private var appDelegate
    #endif

    var body: some Scene {
        WindowGroup {
            #if DEBUG
            if CheckupAutoLaunchMode.isJourneyVisualReview {
                ControlJourneyVisualReview()
            } else {
                OperationalRootView()
            }
            #else
            OperationalRootView()
            #endif
        }
    }
}

private struct OperationalRootView: View {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var model = AppModel()

    var body: some View {
        Group {
            if model.authenticationResolving {
                VStack(spacing: 16) {
                    ProgressView()
                        .tint(Color(red: 0.12, green: 0.33, blue: 0.26))
                    Text("Vérification de votre compte…")
                        .font(.subheadline)
                        .foregroundStyle(Color(red: 0.39, green: 0.45, blue: 0.41))
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color(red: 0.965, green: 0.970, blue: 0.945))
            } else if model.customerSignedIn {
                ContentView()
                    .transition(.opacity)
            } else if model.sessionRecoveryRequired {
                NativeSessionRecoveryView()
                    .transition(.opacity)
            } else {
                PremiumWelcomeView()
                    .transition(.opacity)
            }
        }
        .environmentObject(model)
        .preferredColorScheme(.light)
        .animation(.easeInOut(duration: 0.22), value: model.customerSignedIn)
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                model.refreshAfterForeground()
            }
        }
    }
}

private struct NativeSessionRecoveryView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(spacing: 22) {
            Spacer()
            Image(systemName: "lock.shield")
                .font(.system(size: 52, weight: .light))
                .foregroundStyle(CheckupTheme.accent)
            Text("Votre session est conservée.")
                .font(.system(size: 32, weight: .regular, design: .serif))
                .multilineTextAlignment(.center)
                .foregroundStyle(CheckupTheme.ink)
            Text("Le service est momentanément indisponible. Nous n'avons pas pu vérifier votre session enregistrée. Aucun nouvel identifiant n'est nécessaire.")
                .font(.subheadline)
                .multilineTextAlignment(.center)
                .foregroundStyle(CheckupTheme.muted)
            Button {
                model.retryCustomerSession()
            } label: {
                Label("Réessayer la connexion", systemImage: "arrow.clockwise")
                    .frame(maxWidth: .infinity, minHeight: 48)
            }
            .buttonStyle(.borderedProminent)
            .tint(CheckupTheme.accent)
            .accessibilityIdentifier("native-session-retry")
            Button("Changer de compte") {
                model.signOutCustomer()
            }
            .font(.subheadline)
            .accessibilityIdentifier("native-session-explicit-logout")
            Spacer()
        }
        .frame(maxWidth: 400)
        .padding(26)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(CheckupTheme.paper.ignoresSafeArea())
        .accessibilityIdentifier("native-session-recovery")
    }
}
