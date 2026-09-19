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
                "ContentView.swift", "ReminderScheduler.swift"
            ],
            sources: ["Models.swift", "MobileBootstrap.swift", "DeviceRegistration.swift", "MobileDeadlineSync.swift"]
        ),
        .testTarget(
            name: "CheckupAutoReminderTests",
            dependencies: ["CheckupAutoReminder"],
            path: "Tests",
            exclude: ["ReminderPlanSmoke.swift", "MobileBootstrapSmoke.swift", "MobileDeadlineSyncSmoke.swift"],
            sources: ["ReminderPlanTests.swift", "MobileBootstrapTests.swift", "DeviceRegistrationTests.swift", "MobileDeadlineSyncTests.swift"]
        )
    ]
)
