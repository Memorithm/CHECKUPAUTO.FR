import AuthenticationServices
import Foundation
import CryptoKit

struct AppleSignInCredentialPayload: Codable, Equatable {
    let authorizationCode: String
    let identityToken: String
    let userIdentifier: String
    let givenName: String?
    let familyName: String?
    let email: String?
    let nonce: String
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
    static func payload(from credential: ASAuthorizationAppleIDCredential, nonce: String) throws -> AppleSignInCredentialPayload {
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
            email: credential.email,
            nonce: nonce
        )
    }
}

struct AppleSignInSessionResponse: Decodable {
    let ok: Bool
    let accountId: String
    let sessionToken: String
    let expiresAt: String
}

enum AppleSignInNonce {
    static func make() -> String {
        UUID().uuidString.replacingOccurrences(of: "-", with: "") + UUID().uuidString.replacingOccurrences(of: "-", with: "")
    }

    static func sha256(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

/// Nonce émis par le serveur, à usage unique et valable 10 minutes (audit S-06).
struct AppleSignInServerNonce: Decodable {
    let ok: Bool
    let nonce: String
}

enum AppleSignInNonceClient {
    static func fetch() async throws -> String {
        var request = URLRequest(url: MobileAPI.endpoint("/api/mobile/auth/apple/nonce"))
        request.httpMethod = "POST"
        request.timeoutInterval = 8
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        let decoded = try JSONDecoder().decode(AppleSignInServerNonce.self, from: data)
        guard decoded.ok, decoded.nonce.count >= 32 else { throw URLError(.badServerResponse) }
        return decoded.nonce
    }
}

enum AppleSignInClient {
    static func authenticate(_ payload: AppleSignInCredentialPayload) async throws -> AppleSignInSessionResponse {
        var request = URLRequest(url: MobileAPI.endpoint("/api/mobile/auth/apple"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(payload)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw URLError(.userAuthenticationRequired)
        }
        let session = try JSONDecoder().decode(AppleSignInSessionResponse.self, from: data)
        guard session.ok, !session.sessionToken.isEmpty else {
            throw URLError(.userAuthenticationRequired)
        }
        try CustomerSessionKeychain.save(session.sessionToken)
        return session
    }
}
