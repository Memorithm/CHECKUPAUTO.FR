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
            sources: ["Models.swift"]
        ),
        .testTarget(
            name: "CheckupAutoReminderTests",
            dependencies: ["CheckupAutoReminder"],
            path: "Tests",
            exclude: ["ReminderPlanSmoke.swift"],
            sources: ["ReminderPlanTests.swift"]
        )
    ]
)
