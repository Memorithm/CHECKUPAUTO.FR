import Foundation

struct VehicleClaimRequest: Codable, Equatable, Sendable {
    let installationId: String
    let registrationSecret: String
    let claimToken: String

    func validated() throws -> VehicleClaimRequest {
        guard UUID(uuidString: installationId)?.uuidString.lowercased() == installationId.lowercased() else {
            throw VehicleClaimError.invalidIdentity
        }
        let identityChars = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
        guard (32...128).contains(registrationSecret.count),
              registrationSecret.unicodeScalars.allSatisfy(identityChars.contains) else {
            throw VehicleClaimError.invalidIdentity
        }
        return VehicleClaimRequest(
            installationId: installationId.lowercased(),
            registrationSecret: registrationSecret,
            claimToken: try VehicleClaimToken.validated(claimToken)
        )
    }
}

struct VehicleClaimResponse: Codable, Equatable, Sendable {
    let ok: Bool
    let bindingId: String
    let claimedAt: String

    func validated() throws -> VehicleClaimResponse {
        guard ok,
              UUID(uuidString: bindingId)?.uuidString.lowercased() == bindingId.lowercased(),
              !claimedAt.isEmpty else {
            throw VehicleClaimError.invalidResponse
        }
        return self
    }
}

enum VehicleClaimError: Error {
    case invalidIdentity
    case invalidToken
    case invalidLink
    case invalidResponse
}

enum VehicleClaimToken {
    private static let allowed = CharacterSet(
        charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
    )

    static func validated(_ value: String) throws -> String {
        let token = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard (32...128).contains(token.count),
              token.unicodeScalars.allSatisfy(allowed.contains) else {
            throw VehicleClaimError.invalidToken
        }
        return token
    }
}

enum VehicleClaimLink {
    static func token(from url: URL) throws -> String {
        guard url.scheme?.lowercased() == "https",
              url.host?.lowercased() == "www.checkupauto.fr",
              url.path == "/app/claim",
              url.query == nil,
              let fragment = url.fragment,
              let parts = URLComponents(string: "https://claim.invalid/?\(fragment)"),
              let raw = parts.queryItems?.first(where: { $0.name == "token" })?.value else {
            throw VehicleClaimError.invalidLink
        }
        return try VehicleClaimToken.validated(raw)
    }
}

enum VehicleClaimClient {
    static var endpoint: URL { MobileAPI.endpoint("/api/mobile/claims/consume") }

    static func consume(token: String, session: URLSession = .shared) async throws -> VehicleClaimResponse {
        try await DeviceRegistrationClient.registerInstallation(
            session: session,
            reactivate: true
        )
        let identity = try DeviceRegistrationIdentity.loadOrCreate()
        let payload = try VehicleClaimRequest(
            installationId: identity.installationId,
            registrationSecret: identity.secret,
            claimToken: token
        ).validated()
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = 8
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONEncoder().encode(payload)
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw VehicleClaimError.invalidResponse
        }
        return try JSONDecoder().decode(VehicleClaimResponse.self, from: data).validated()
    }
}
