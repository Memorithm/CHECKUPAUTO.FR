import AuthenticationServices
import Foundation

struct AppleSignInCredentialPayload: Codable, Equatable {
    let authorizationCode: String
    let identityToken: String
    let userIdentifier: String
    let givenName: String?
    let familyName: String?
    let email: String?
}

enum AppleSignInError: LocalizedError {
    case missingAuthorizationCode
    case missingIdentityToken

    var errorDescription: String? {
        switch self {
        case .missingAuthorizationCode: return "Apple n’a pas fourni de code d’autorisation."
        case .missingIdentityToken: return "Apple n’a pas fourni de jeton d’identité."
        }
    }
}

enum AppleSignInCredentialMapper {
    static func payload(from credential: ASAuthorizationAppleIDCredential) throws -> AppleSignInCredentialPayload {
        guard let codeData = credential.authorizationCode,
              let code = String(data: codeData, encoding: .utf8),
              !code.isEmpty else { throw AppleSignInError.missingAuthorizationCode }
        guard let tokenData = credential.identityToken,
              let token = String(data: tokenData, encoding: .utf8),
              !token.isEmpty else { throw AppleSignInError.missingIdentityToken }
        return AppleSignInCredentialPayload(
            authorizationCode: code,
            identityToken: token,
            userIdentifier: credential.user,
            givenName: credential.fullName?.givenName,
            familyName: credential.fullName?.familyName,
            email: credential.email
        )
    }
}

enum AppleSignInClient {
    static func authenticate(_ payload: AppleSignInCredentialPayload) async throws {
        var request = URLRequest(url: MobileAPI.endpoint("/api/mobile/auth/apple"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(payload)
        let (_, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw URLError(.userAuthenticationRequired)
        }
    }
}
