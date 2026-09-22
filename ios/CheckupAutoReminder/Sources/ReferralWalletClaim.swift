import Foundation
import Security

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

struct ReferralWalletProductStatus: Codable, Equatable, Sendable, Identifiable {
    let referralCode: String
    let active: Bool
    let currency: String
    let rewardCents: Int
    let balanceCents: Int
    let pendingCents: Int
    let earnedReferrals: Int
    let pendingReferrals: Int
    let cancelledReferrals: Int
    let reversedReferrals: Int

    var id: String { referralCode }

    func validated() throws -> ReferralWalletProductStatus {
        guard !referralCode.isEmpty,
              referralCode.count <= 120,
              currency.count == 3,
              rewardCents >= 0,
              pendingCents >= 0,
              earnedReferrals >= 0,
              pendingReferrals >= 0,
              cancelledReferrals >= 0,
              reversedReferrals >= 0 else {
            throw ReferralWalletClaimError.invalidResponse
        }
        return self
    }
}

struct ReferralWalletStatusResponse: Codable, Equatable, Sendable {
    let ok: Bool
    let walletCount: Int
    let wallets: [ReferralWalletProductStatus]
    let ownershipProvenance: String
    let shareCodeIsOwnershipProof: Bool
    let accountIdentifiersExposed: Bool
    let thirdPartyAppointmentIdentifiersExposed: Bool
    let ledgerReferencesExposed: Bool

    func validated() throws -> ReferralWalletStatusResponse {
        guard ok,
              walletCount >= 0,
              walletCount <= 16,
              walletCount == wallets.count,
              ownershipProvenance == "authenticated_mobile_wallet_claim",
              !shareCodeIsOwnershipProof,
              !accountIdentifiersExposed,
              !thirdPartyAppointmentIdentifiersExposed,
              !ledgerReferencesExposed else {
            throw ReferralWalletClaimError.invalidResponse
        }
        for wallet in wallets {
            _ = try wallet.validated()
        }
        return self
    }
}

struct ReferralWalletClaimResponse: Codable, Equatable, Sendable {
    let ok: Bool
    let claimType: String
    let claimedAt: String
    let provenance: String
    let walletStatus: ReferralWalletStatusResponse?

    func validated() throws -> ReferralWalletClaimResponse {
        guard ok,
              claimType == "referral_wallet",
              !claimedAt.isEmpty,
              ISO8601DateFormatter().date(from: claimedAt) != nil,
              provenance == "authenticated_mobile_wallet_claim" else {
            throw ReferralWalletClaimError.invalidResponse
        }
        if let walletStatus {
            _ = try walletStatus.validated()
        }
        return self
    }
}

struct ReferralWalletVerifiedSnapshot: Codable, Equatable, Sendable {
    let wallets: [ReferralWalletProductStatus]
    let verifiedAt: String

    func validated() throws -> ReferralWalletVerifiedSnapshot {
        guard wallets.count <= 16,
              ISO8601DateFormatter().date(from: verifiedAt) != nil else {
            throw ReferralWalletClaimError.invalidResponse
        }
        for wallet in wallets {
            _ = try wallet.validated()
        }
        return self
    }
}

enum ReferralWalletClaimError: Error {
    case invalidIdentity
    case invalidToken
    case invalidResponse
    case keychainFailure
}

enum ReferralWalletSnapshotStore {
    private static let service = "fr.checkupauto.reminder.referral-wallet"
    private static let account = "verified-snapshot-v1"

    static func load() -> ReferralWalletVerifiedSnapshot? {
        guard let data = readData() else { return nil }
        return try? decode(data)
    }

    static func save(_ snapshot: ReferralWalletVerifiedSnapshot) throws {
        let data = try encode(snapshot)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
        var add = query
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        guard SecItemAdd(add as CFDictionary, nil) == errSecSuccess else {
            throw ReferralWalletClaimError.keychainFailure
        }
    }

    static func clear() throws {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw ReferralWalletClaimError.keychainFailure
        }
    }

    static func encode(_ snapshot: ReferralWalletVerifiedSnapshot) throws -> Data {
        try JSONEncoder().encode(snapshot.validated())
    }

    static func decode(_ data: Data) throws -> ReferralWalletVerifiedSnapshot {
        try JSONDecoder().decode(ReferralWalletVerifiedSnapshot.self, from: data).validated()
    }

    private static func readData() -> Data? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else {
            return nil
        }
        return data
    }
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
