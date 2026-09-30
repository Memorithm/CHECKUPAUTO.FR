import Foundation

enum MobileAPI {
    static let productionBaseURL = URL(string: "https://www.checkupauto.fr")!
    static let preproductionBaseURL = URL(string: "https://stage.179.198.210.187.sslip.io")!
    static let environmentInfoKey = "CheckupAutoEnvironment"

    static func packagedBaseURL(environment: String?) -> URL {
        environment == "preproduction" ? preproductionBaseURL : productionBaseURL
    }

    static var isPreproduction: Bool {
        Bundle.main.object(forInfoDictionaryKey: environmentInfoKey) as? String == "preproduction"
    }

    static func storageKey(_ key: String, preproduction: Bool = isPreproduction) -> String {
        preproduction ? key + ".preproduction" : key
    }

    static func websiteURL(_ url: URL, preproduction: Bool = isPreproduction) -> URL {
        guard preproduction,
              url.scheme == "https",
              ["www.checkupauto.fr", "checkupauto.fr"].contains(url.host?.lowercased() ?? ""),
              url.user == nil, url.password == nil, url.port == nil,
              var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return url }
        components.host = preproductionBaseURL.host
        return components.url ?? url
    }

    static func bookingJourneyURL(preproduction: Bool = isPreproduction) -> URL {
        let origin = preproduction ? preproductionBaseURL : productionBaseURL
        var components = URLComponents(url: origin, resolvingAgainstBaseURL: false)!
        components.path = preproduction ? "/payment/test" : "/"
        components.queryItems = [URLQueryItem(name: "source", value: "ios-app")]
        components.fragment = preproduction ? nil : "reservation"
        return components.url!
    }

    static let debugEnvironmentKey = "CHECKUPAUTO_API_BASE_URL"

    static func resolvedBaseURL(
        environment: [String: String],
        allowOverride: Bool,
        packagedEnvironment: String? = nil
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
            return packagedBaseURL(environment: packagedEnvironment)
        }
        return candidate
    }

    static var currentBaseURL: URL {
        #if DEBUG
        return resolvedBaseURL(
            environment: ProcessInfo.processInfo.environment,
            allowOverride: true,
            packagedEnvironment: Bundle.main.object(forInfoDictionaryKey: environmentInfoKey) as? String
        )
        #else
        return packagedBaseURL(environment: Bundle.main.object(forInfoDictionaryKey: environmentInfoKey) as? String)
        #endif
    }

    static func endpoint(_ path: String, baseURL: URL = currentBaseURL) -> URL {
        precondition(path.hasPrefix("/"), "Mobile API paths must be absolute")
        return baseURL.appendingPathComponent(String(path.dropFirst()))
    }
}
