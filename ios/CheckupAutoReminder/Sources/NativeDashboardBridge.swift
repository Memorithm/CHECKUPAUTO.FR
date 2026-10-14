import Foundation
import WebKit

enum NativeDashboardBridgeError: Error {
    case noNativeSession
    case expiredNativeSession
    case invalidServerResponse
    case untrustedCookie
}

/// The native bearer stays in iOS Keychain. Only a separately minted, bounded
/// browser cookie is copied into an *ephemeral*, same-origin WKWebView store.
/// Neither the token nor the cookie ever enters JavaScript or a URL parameter.
@MainActor
enum NativeDashboardBridge {
    static let cookieName = "checkupauto_customer"

    private struct BridgeResponse: Decodable {
        let ok: Bool
        let expiresIn: Int
    }

    static func createBrowserCookie() async throws -> HTTPCookie {
        guard let nativeToken = CustomerSessionKeychain.load(), !nativeToken.isEmpty else {
            throw NativeDashboardBridgeError.noNativeSession
        }
        let endpoint = MobileAPI.endpoint("/api/mobile/auth/web-session")
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.httpBody = Data("{}".utf8)
        request.httpShouldHandleCookies = false
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.timeoutInterval = 12
        request.setValue("Bearer " + nativeToken, forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")

        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieAcceptPolicy = .never
        configuration.httpShouldSetCookies = false
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        let delegate = NativeDashboardNoRedirects()
        let session = URLSession(configuration: configuration, delegate: delegate, delegateQueue: nil)
        defer { session.invalidateAndCancel() }

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw NativeDashboardBridgeError.invalidServerResponse
        }
        if http.statusCode == 401 {
            throw NativeDashboardBridgeError.expiredNativeSession
        }
        guard http.statusCode == 200,
              http.url == endpoint,
              let parsed = try? JSONDecoder().decode(BridgeResponse.self, from: data),
              parsed.ok, (60...3600).contains(parsed.expiresIn),
              let rawCookie = http.value(forHTTPHeaderField: "Set-Cookie") else {
            throw NativeDashboardBridgeError.invalidServerResponse
        }
        let cookies = HTTPCookie.cookies(
            withResponseHeaderFields: ["Set-Cookie": rawCookie],
            for: MobileAPI.currentBaseURL
        )
        let expectedHost = MobileAPI.currentBaseURL.host?.lowercased()
        guard cookies.count == 1, let cookie = cookies.first,
              cookie.name == cookieName, cookie.value != nativeToken,
              cookie.value.range(
                of: #"^[A-Za-z0-9_-]{32,128}$"#, options: .regularExpression
              ) != nil,
              cookie.domain.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: ".")) == expectedHost,
              cookie.path == "/", cookie.isSecure, cookie.isHTTPOnly else {
            throw NativeDashboardBridgeError.untrustedCookie
        }
        return cookie
    }
}

/// Never follow a redirect with a native bearer, even if the app domain is
/// temporarily misconfigured or compromised.
private final class NativeDashboardNoRedirects: NSObject, URLSessionTaskDelegate {
    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }
}
