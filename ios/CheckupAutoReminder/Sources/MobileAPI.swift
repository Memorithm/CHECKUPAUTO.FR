import Foundation

enum MobileAPI {
    static let productionBaseURL = URL(string: "https://www.checkupauto.fr")!
    static let debugEnvironmentKey = "CHECKUPAUTO_API_BASE_URL"

    static func resolvedBaseURL(
        environment: [String: String],
        allowOverride: Bool
    ) -> URL {
        guard allowOverride,
              let raw = environment[debugEnvironmentKey]?.trimmingCharacters(in: .whitespacesAndNewlines),
              !raw.isEmpty,
              let candidate = URL(string: raw),
              candidate.scheme?.lowercased() == "https",
              candidate.host != nil,
              candidate.user == nil,
              candidate.password == nil,
              candidate.query == nil,
              candidate.fragment == nil,
              candidate.path.isEmpty || candidate.path == "/" else {
            return productionBaseURL
        }
        return candidate
    }

    static var currentBaseURL: URL {
        #if DEBUG
        return resolvedBaseURL(
            environment: ProcessInfo.processInfo.environment,
            allowOverride: true
        )
        #else
        return productionBaseURL
        #endif
    }

    static func endpoint(_ path: String, baseURL: URL = currentBaseURL) -> URL {
        precondition(path.hasPrefix("/"), "Mobile API paths must be absolute")
        return baseURL.appendingPathComponent(String(path.dropFirst()))
    }
}
