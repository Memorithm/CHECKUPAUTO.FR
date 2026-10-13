import Foundation

private struct EmailLoginResponse: Decodable {
    let ok: Bool
    let accountId: String
    let sessionToken: String
    let expiresAt: String
}

private struct EmailRegistrationResponse: Decodable {
    let ok: Bool
    let verificationRequired: Bool
}

enum EmailCustomerAuthError: LocalizedError {
    case invalidCredentials
    case registrationUnavailable
    case invalidRegistration
    case invalidServerResponse

    var errorDescription: String? {
        switch self {
        case .invalidCredentials:
            return "Connexion impossible. Vérifiez votre e-mail, votre mot de passe et la confirmation de votre adresse."
        case .registrationUnavailable:
            return "La création de compte par e-mail est momentanément indisponible."
        case .invalidRegistration:
            return "Vérifiez l’adresse e-mail et le mot de passe (12 caractères minimum)."
        case .invalidServerResponse:
            return "Le service Checkup Auto est momentanément indisponible."
        }
    }
}

enum EmailCustomerAuthClient {
    static func signIn(email: String, password: String) async throws {
        let (data, status) = try await submit(
            path: "/api/mobile/auth/email/login",
            fields: ["email": email, "password": password]
        )
        guard status == 200 else { throw EmailCustomerAuthError.invalidCredentials }
        guard let response = try? JSONDecoder().decode(EmailLoginResponse.self, from: data),
              response.ok, !response.accountId.isEmpty,
              !response.sessionToken.isEmpty else {
            throw EmailCustomerAuthError.invalidServerResponse
        }
        try CustomerSessionKeychain.save(response.sessionToken)
    }

    static func register(email: String, password: String, confirmation: String) async throws {
        let (data, status) = try await submit(
            path: "/api/mobile/auth/email/register",
            fields: ["email": email, "password": password, "passwordConfirm": confirmation]
        )
        if status == 503 { throw EmailCustomerAuthError.registrationUnavailable }
        guard status == 200 else { throw EmailCustomerAuthError.invalidRegistration }
        guard let response = try? JSONDecoder().decode(EmailRegistrationResponse.self, from: data),
              response.ok, response.verificationRequired else {
            throw EmailCustomerAuthError.invalidServerResponse
        }
    }

    private static func submit(path: String, fields: [String: String]) async throws -> (Data, Int) {
        var request = URLRequest(url: MobileAPI.endpoint(path))
        request.httpMethod = "POST"
        request.timeoutInterval = 20
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONSerialization.data(withJSONObject: fields)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw EmailCustomerAuthError.invalidServerResponse
        }
        return (data, http.statusCode)
    }
}
