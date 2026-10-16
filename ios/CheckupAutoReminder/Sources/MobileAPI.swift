import Foundation

enum MobileAPI {
    static let productionBaseURL = URL(string: "https://www.checkupauto.fr")!
    static let preproductionBaseURL = URL(string: "https://test.checkupauto.fr")!

    // Direct public Mercure reservation entry point, unchanged in preproduction.
    static let directMercureBookingURL = URL(string: "https://rdv.checkupauto.fr")!

    // Exact still illustration used by the test.checkupauto.fr landing page.
    static func premiumVehicleArtworkURL(baseURL: URL = currentBaseURL) -> URL {
        endpoint("/assets/illustrations/checkupauto-lavis-option2-1020.webp", baseURL: baseURL)
    }
    // Same two approved illustrations as the website account's carte grise
    // form. Displayed in-app; no web login or browser navigation is needed.
    static func vehicleFormulaGuideURL(baseURL: URL = currentBaseURL) -> URL {
        endpoint("/assets/guides/carte-grise-formule-photo.webp", baseURL: baseURL)
    }

    static func vehicleCardDateGuideURL(baseURL: URL = currentBaseURL) -> URL {
        endpoint("/assets/guides/carte-grise-date-photo.webp", baseURL: baseURL)
    }

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
        components.path = "/"
        components.queryItems = [URLQueryItem(name: "utm_source", value: "app:ios")]
        components.fragment = "reservation"
        return components.url!
    }

    // Public Mercure planning, served as JSON through the Cloudflare-cached
    // site. The native in-app planner reads these directly so the first booking
    // screen appears instantly, without loading a web page.
    static func mercureServicesURL(baseURL: URL = currentBaseURL) -> URL {
        endpoint("/api/booking/services", baseURL: baseURL)
    }

    static func mercureAvailabilityURL(
        serviceKey: String, date: String, baseURL: URL = currentBaseURL
    ) -> URL {
        var components = URLComponents(
            url: endpoint("/api/booking/availability", baseURL: baseURL),
            resolvingAgainstBaseURL: false
        )!
        components.queryItems = [
            URLQueryItem(name: "service", value: serviceKey),
            URLQueryItem(name: "date", value: date),
        ]
        return components.url!
    }

    /// First-party entry point for the in-app booking journey: the authenticated
    /// passage page (vehicle + contact), which then continues to the in-site
    /// Mercure summary and the hosted checkout, all inside the app's own
    /// signed-in WebKit view. The scoped browser cookie is used, never the
    /// native bearer, and no second login is ever presented.
    static func inAppBookingEntryURL(
        serviceLabel: String, date: String, time: String, baseURL: URL = currentBaseURL
    ) -> URL? {
        guard !serviceLabel.isEmpty, serviceLabel.count <= 100,
              date.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil,
              time.range(of: #"^\d{2}:\d{2}$"#, options: .regularExpression) != nil else {
            return nil
        }
        var unreserved = CharacterSet.alphanumerics
        unreserved.insert(charactersIn: "-._~")
        func enc(_ value: String) -> String {
            value.addingPercentEncoding(withAllowedCharacters: unreserved) ?? ""
        }
        // Raw inner target, percent-encoded once as the single returnTo value.
        let inner = "/go/booking?service=\(serviceLabel)"
            + "&preferredDate=\(date)&preferredTime=\(time)"
            + "&utmSource=app:ios&device=mobile"
        let base = baseURL.absoluteString
        let prefix = base.hasSuffix("/") ? base : base + "/"
        return URL(string: prefix + "compte/reserver?returnTo=" + enc(inner))
    }

    /// Only the external card-payment page (Payline) and the legacy Mercure
    /// reservation host may leave the in-app journey into the system payment
    /// sheet. Everything else stays first-party inside the app.
    static func isHostedPaymentURL(_ url: URL) -> Bool {
        guard url.scheme?.lowercased() == "https", let host = url.host?.lowercased() else {
            return false
        }
        if host == "rdv.checkupauto.fr" { return true }
        return host == "payline.com" || host.hasSuffix(".payline.com")
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
