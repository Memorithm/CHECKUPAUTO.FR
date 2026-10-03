import AuthenticationServices
import Foundation

@MainActor
final class GoogleCustomerSignIn: NSObject, ASWebAuthenticationPresentationContextProviding {
    private var session: ASWebAuthenticationSession?

    func start() async throws {
        var components = URLComponents(url: MobileAPI.endpoint("/auth/customer/google"), resolvingAgainstBaseURL: false)!
        components.queryItems = [URLQueryItem(name: "mobile", value: "1")]
        let url = components.url!
        try await withCheckedThrowingContinuation { continuation in
            let auth = ASWebAuthenticationSession(url: url, callbackURLScheme: "checkupauto") { callback, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                guard let callback,
                      callback.scheme == "checkupauto",
                      callback.host == "auth",
                      callback.path == "/google" else {
                    continuation.resume(throwing: URLError(.userAuthenticationRequired))
                    return
                }
                guard let ticket = URLComponents(url: callback, resolvingAgainstBaseURL: false)?
                    .queryItems?.first(where: { $0.name == "ticket" })?.value,
                      !ticket.isEmpty else {
                    continuation.resume(throwing: URLError(.userAuthenticationRequired))
                    return
                }
                Task {
                    do {
                        var request = URLRequest(url: MobileAPI.endpoint("/api/mobile/auth/exchange"))
                        request.httpMethod = "POST"
                        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                        request.httpBody = try JSONSerialization.data(withJSONObject: ["ticket": ticket])
                        let (data, response) = try await URLSession.shared.data(for: request)
                        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode),
                              let body = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                              body["ok"] as? Bool == true,
                              let token = body["sessionToken"] as? String else {
                            throw URLError(.userAuthenticationRequired)
                        }
                        try CustomerSessionKeychain.save(token)
                        continuation.resume(returning: ())
                    } catch {
                        continuation.resume(throwing: error)
                    }
                }
            }
            auth.presentationContextProvider = self
            auth.prefersEphemeralWebBrowserSession = false
            self.session = auth
            guard auth.start() else {
                continuation.resume(throwing: URLError(.cannotLoadFromNetwork))
                return
            }
        }
    }

    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        #if canImport(UIKit)
        return UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .flatMap(\.windows)
            .first(where: \.isKeyWindow) ?? ASPresentationAnchor()
        #else
        return ASPresentationAnchor()
        #endif
    }
}
