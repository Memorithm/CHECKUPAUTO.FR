import AuthenticationServices
import Foundation

@MainActor
final class GoogleCustomerSignIn: NSObject, ASWebAuthenticationPresentationContextProviding {
    private var session: ASWebAuthenticationSession?

    func start() async throws {
        let url = MobileAPI.endpoint("/auth/customer/google")
        try await withCheckedThrowingContinuation { continuation in
            let auth = ASWebAuthenticationSession(url: url, callbackURLScheme: nil) { callback, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                guard let callback,
                      callback.scheme == "https",
                      callback.host == MobileAPI.currentBaseURL.host,
                      callback.path == "/compte" else {
                    continuation.resume(throwing: URLError(.userAuthenticationRequired))
                    return
                }
                continuation.resume(returning: ())
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
