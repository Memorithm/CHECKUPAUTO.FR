// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "CheckupAutoReminder",
    platforms: [.macOS(.v15)],
    products: [
        .library(name: "CheckupAutoReminder", targets: ["CheckupAutoReminder"])
    ],
    targets: [
        .target(
            name: "CheckupAutoReminder",
            path: "Sources",
            exclude: [
                "AddVehicleView.swift", "AppModel.swift", "CheckupAutoReminderApp.swift",
                "ContentView.swift", "PremiumWelcomeView.swift", "NativeCustomerAccountView.swift",
                "NativeDashboardBridge.swift", "AuthenticatedCustomerDashboardWebView.swift",
                "AuthenticatedBookingWebView.swift", "BookingJourneyView.swift",
                "CentreGPSChoice.swift",
                "CustomerAuthenticationOptions.swift", "EmailAccountView.swift",
                "EmailCustomerAuth.swift", "InAppBrowserView.swift",
                "ReminderScheduler.swift", "PrivacyInfo.xcprivacy"
            ],
            sources: ["Models.swift", "NotificationRouting.swift", "MobileAPI.swift", "MobileBootstrap.swift", "DeviceRegistration.swift", "MobileDeadlineSync.swift", "VehicleClaim.swift", "ReferralWalletClaim.swift", "AuthoritativeInventory.swift", "VehicleRegistrationRules.swift"]
        ),
        .testTarget(
            name: "CheckupAutoReminderTests",
            dependencies: ["CheckupAutoReminder"],
            path: "Tests",
            exclude: ["ReminderPlanSmoke.swift", "MobileBootstrapSmoke.swift", "MobileDeadlineSyncSmoke.swift"],
            sources: ["ReminderPlanTests.swift", "NotificationRoutingTests.swift", "MobileAPITests.swift", "MobileBootstrapTests.swift", "DeviceRegistrationTests.swift", "MobileDeadlineSyncTests.swift", "VehicleClaimTests.swift", "ReferralWalletClaimTests.swift", "AuthoritativeInventoryTests.swift", "VehicleRegistrationRulesTests.swift"]
        )
    ]
)
