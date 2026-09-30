import Foundation

enum MobileClaimKind: Equatable, Sendable {
    case vehicle
    case referralWallet
}

struct MobileClaim: Equatable, Sendable {
    let kind: MobileClaimKind
    let token: String
}

enum MobileClaimToken {
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

    static func kind(of value: String) throws -> MobileClaimKind {
        let token = try validated(value)
        return token.hasPrefix("rw_") ? .referralWallet : .vehicle
    }
}

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
        let token = try VehicleClaimToken.validated(claimToken)
        return VehicleClaimRequest(
            installationId: installationId.lowercased(),
            registrationSecret: registrationSecret,
            claimToken: token
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
    static func validated(_ value: String) throws -> String {
        let token = try MobileClaimToken.validated(value)
        guard try MobileClaimToken.kind(of: token) == .vehicle else {
            throw VehicleClaimError.invalidToken
        }
        return token
    }
}

enum MobileClaimLink {
    static func token(from url: URL) throws -> String {
        guard url.scheme?.lowercased() == "https",
              url.host?.lowercased() == MobileAPI.currentBaseURL.host,
              url.port == MobileAPI.currentBaseURL.port,
              url.user == nil, url.password == nil,
              url.path == "/app/claim",
              url.query == nil,
              let fragment = url.fragment,
              let parts = URLComponents(string: "https://claim.invalid/?\(fragment)"),
              let raw = parts.queryItems?.first(where: { $0.name == "token" })?.value else {
            throw VehicleClaimError.invalidLink
        }
        return try MobileClaimToken.validated(raw)
    }

    static func claim(from url: URL) throws -> MobileClaim {
        let token = try token(from: url)
        return MobileClaim(kind: try MobileClaimToken.kind(of: token), token: token)
    }
}

enum VehicleClaimLink {
    static func token(from url: URL) throws -> String {
        try VehicleClaimToken.validated(MobileClaimLink.token(from: url))
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
