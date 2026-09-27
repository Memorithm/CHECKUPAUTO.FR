import SwiftUI
import UserNotifications
#if canImport(UIKit)
import UIKit

final class CheckupAutoAppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
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
        if #available(iOS 26.0, *),
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
            let config = (try? await MobileBootstrapClient.fetch()) ?? .fallback
            guard let url = URL(string: config.booking.url) else {
                completionHandler()
                return
            }
            await MainActor.run {
                UIApplication.shared.open(url, options: [:]) { _ in
                    completionHandler()
                }
            }
        }
    }

}
#endif

@main
struct CheckupAutoReminderApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var model = AppModel()
    #if canImport(UIKit)
    @UIApplicationDelegateAdaptor(CheckupAutoAppDelegate.self) private var appDelegate
    #endif

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .onChange(of: scenePhase) { _, phase in
                    if phase == .active {
                        model.refreshAfterForeground()
                    }
                }
        }
    }
}
