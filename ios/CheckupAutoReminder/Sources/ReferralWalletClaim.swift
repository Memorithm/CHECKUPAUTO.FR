import Foundation

struct ReferralWalletClaimRequest: Codable, Equatable, Sendable {
    let installationId: String
    let registrationSecret: String
    let claimToken: String

    func validated() throws -> ReferralWalletClaimRequest {
        guard UUID(uuidString: installationId)?.uuidString.lowercased() == installationId.lowercased() else {
            throw ReferralWalletClaimError.invalidIdentity
        }
        let identityChars = CharacterSet(
            charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
        )
        guard (32...128).contains(registrationSecret.count),
              registrationSecret.unicodeScalars.allSatisfy(identityChars.contains) else {
            throw ReferralWalletClaimError.invalidIdentity
        }
        let token = try MobileClaimToken.validated(claimToken)
        guard try MobileClaimToken.kind(of: token) == .referralWallet else {
            throw ReferralWalletClaimError.invalidToken
        }
        return ReferralWalletClaimRequest(
            installationId: installationId.lowercased(),
            registrationSecret: registrationSecret,
            claimToken: token
        )
    }
}

struct ReferralWalletClaimResponse: Codable, Equatable, Sendable {
    let ok: Bool
    let claimType: String
    let claimedAt: String
    let provenance: String

    func validated() throws -> ReferralWalletClaimResponse {
        guard ok,
              claimType == "referral_wallet",
              !claimedAt.isEmpty,
              provenance == "authenticated_mobile_wallet_claim" else {
            throw ReferralWalletClaimError.invalidResponse
        }
        return self
    }
}

enum ReferralWalletClaimError: Error {
    case invalidIdentity
    case invalidToken
    case invalidResponse
}

enum ReferralWalletClaimClient {
    static var endpoint: URL { MobileAPI.endpoint("/api/mobile/claims/consume") }

    static func consume(
        token: String,
        session: URLSession = .shared
    ) async throws -> ReferralWalletClaimResponse {
        try await DeviceRegistrationClient.registerInstallation(
            session: session,
            reactivate: true
        )
        let identity = try DeviceRegistrationIdentity.loadOrCreate()
        let payload = try ReferralWalletClaimRequest(
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
            throw ReferralWalletClaimError.invalidResponse
        }
        return try JSONDecoder().decode(ReferralWalletClaimResponse.self, from: data).validated()
    }
}
