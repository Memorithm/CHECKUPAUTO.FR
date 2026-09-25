import Foundation

struct MobileReminderPolicy: Codable, Equatable, Sendable {
    let leadDays: [Int]
    let hour: Int
    let timezone: String

    func validated() throws -> MobileReminderPolicy {
        let unique = Array(Set(leadDays)).sorted(by: >)
        guard !unique.isEmpty, unique.count == leadDays.count,
              unique.allSatisfy({ (0...3650).contains($0) }) else {
            throw MobileBootstrapError.invalidReminderPolicy
        }
        guard (0...23).contains(hour), TimeZone(identifier: timezone) != nil else {
            throw MobileBootstrapError.invalidReminderPolicy
        }
        return self
    }
}

struct MobileBookingConfig: Codable, Equatable, Sendable {
    let url: String
}

struct MobileAccountConfig: Codable, Equatable, Sendable {
    let url: String
    let reportScanUrl: String
}

struct MobileNotificationConfig: Codable, Equatable, Sendable {
    let remotePushActive: Bool
    let localFallback: Bool
}

struct MobileReferralConfig: Codable, Equatable, Sendable {
    let rewardCents: Int
    let currency: String
}

struct MobileAppConfig: Codable, Equatable, Sendable {
    let landingUrl: String
    let available: Bool
    let downloadPath: String
}

struct MobileBootstrap: Codable, Equatable, Sendable {
    let schemaVersion: Int
    let reminders: MobileReminderPolicy
    let booking: MobileBookingConfig
    let account: MobileAccountConfig?
    let notifications: MobileNotificationConfig
    let referral: MobileReferralConfig
    let app: MobileAppConfig

    static let fallback = MobileBootstrap(
        schemaVersion: 1,
        reminders: MobileReminderPolicy(leadDays: [60, 30, 15, 7, 1], hour: 9, timezone: "Europe/Paris"),
        booking: MobileBookingConfig(url: "https://rdv.checkupauto.fr/"),
        account: MobileAccountConfig(
            url: "https://www.checkupauto.fr/compte",
            reportScanUrl: "https://www.checkupauto.fr/compte#ct-report"
        ),
        notifications: MobileNotificationConfig(remotePushActive: false, localFallback: true),
        referral: MobileReferralConfig(rewardCents: 500, currency: "EUR"),
        app: MobileAppConfig(landingUrl: "https://www.checkupauto.fr/app", available: false, downloadPath: "/go/app")
    )

    func validated() throws -> MobileBootstrap {
        guard schemaVersion == 1 else { throw MobileBootstrapError.unsupportedSchema }
        _ = try reminders.validated()
        guard let bookingURL = URL(string: booking.url), bookingURL.scheme == "https", bookingURL.host != nil,
              let landingURL = URL(string: app.landingUrl), landingURL.scheme == "https", landingURL.host != nil,
              app.downloadPath.hasPrefix("/"), notifications.localFallback != notifications.remotePushActive,
              referral.rewardCents > 0, referral.rewardCents <= 5_000,
              referral.currency == "EUR" else {
            throw MobileBootstrapError.invalidConfiguration
        }
        if let account {
            guard let accountURL = URL(string: account.url), accountURL.scheme == "https", accountURL.host != nil,
                  let reportScanURL = URL(string: account.reportScanUrl), reportScanURL.scheme == "https", reportScanURL.host != nil else {
                throw MobileBootstrapError.invalidConfiguration
            }
        }
        return self
    }
}

enum MobileBootstrapError: Error {
    case unsupportedSchema
    case invalidReminderPolicy
    case invalidConfiguration
    case invalidResponse
}

enum MobileBootstrapClient {
    static var endpoint: URL { MobileAPI.endpoint("/api/mobile/bootstrap") }

    static func fetch(session: URLSession = .shared) async throws -> MobileBootstrap {
        var request = URLRequest(url: endpoint)
        request.timeoutInterval = 8
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw MobileBootstrapError.invalidResponse
        }
        return try JSONDecoder().decode(MobileBootstrap.self, from: data).validated()
    }
}
