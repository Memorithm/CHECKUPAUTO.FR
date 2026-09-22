import Foundation

struct ReferralWalletSnapshot: Codable, Equatable, Sendable {
    let verifiedAt: Date
    let wallets: [ReferralWalletProductStatus]

    func validated() throws -> ReferralWalletSnapshot {
        guard verifiedAt.timeIntervalSince1970 > 0 else {
            throw ReferralWalletClaimError.invalidResponse
        }
        for wallet in wallets {
            _ = try wallet.validated()
        }
        return self
    }
}

enum ReferralWalletSnapshotStore {
    static let storageKey = "checkupauto.referral.wallet.snapshot.v1"

    static func load(defaults: UserDefaults = .standard) -> ReferralWalletSnapshot? {
        guard let data = defaults.data(forKey: storageKey),
              let snapshot = try? JSONDecoder().decode(ReferralWalletSnapshot.self, from: data),
              let validated = try? snapshot.validated() else {
            return nil
        }
        return validated
    }

    static func save(
        _ wallets: [ReferralWalletProductStatus],
        verifiedAt: Date = Date(),
        defaults: UserDefaults = .standard
    ) {
        let snapshot = ReferralWalletSnapshot(verifiedAt: verifiedAt, wallets: wallets)
        guard let validated = try? snapshot.validated(),
              let data = try? JSONEncoder().encode(validated) else {
            return
        }
        defaults.set(data, forKey: storageKey)
    }

    static func clear(defaults: UserDefaults = .standard) {
        defaults.removeObject(forKey: storageKey)
    }
}
