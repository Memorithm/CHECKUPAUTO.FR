import Foundation

@main
enum LiveStagingBootstrapSmoke {
    static func main() async throws {
        let environment = ProcessInfo.processInfo.environment
        guard let rawBase = environment[MobileAPI.debugEnvironmentKey],
              let base = URL(string: rawBase),
              base.scheme == "https",
              base.host != nil else {
            throw MobileBootstrapError.invalidConfiguration
        }

        let resolved = MobileAPI.resolvedBaseURL(
            environment: environment,
            allowOverride: true
        )
        guard resolved == base else {
            throw MobileBootstrapError.invalidConfiguration
        }

        let bootstrap = try await MobileBootstrapClient.fetch()
        guard bootstrap.schemaVersion == 1,
              bootstrap.reminders.leadDays == [60, 30, 15, 7, 1],
              bootstrap.reminders.hour == 9,
              bootstrap.reminders.timezone == "Europe/Paris",
              bootstrap.notifications.localFallback != bootstrap.notifications.remotePushActive,
              bootstrap.referral.currency == "EUR",
              bootstrap.referral.rewardCents == 500 else {
            throw MobileBootstrapError.invalidConfiguration
        }

        print("IOS_LIVE_STAGING_BOOTSTRAP_OK")
        print("remotePushActive=\(bootstrap.notifications.remotePushActive)")
        print("localFallback=\(bootstrap.notifications.localFallback)")
    }
}
