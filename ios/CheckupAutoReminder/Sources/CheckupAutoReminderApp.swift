import SwiftUI
#if canImport(UIKit)
import UIKit

final class CheckupAutoAppDelegate: NSObject, UIApplicationDelegate {
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
}
#endif

@main
struct CheckupAutoReminderApp: App {
    @StateObject private var model = AppModel()
    #if canImport(UIKit)
    @UIApplicationDelegateAdaptor(CheckupAutoAppDelegate.self) private var appDelegate
    #endif

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
        }
    }
}
