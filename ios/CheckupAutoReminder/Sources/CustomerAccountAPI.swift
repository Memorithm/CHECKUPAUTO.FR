import Foundation

enum CustomerAccountAPIError: Error {
    case sessionExpired
    case invalidResponse
}

/// Scoped to the authenticated native customer session. No browser cookie.
struct CustomerAccountProfile: Decodable, Equatable {
    let ok: Bool
    let accountId: String
    let displayName: String
    let email: String
    let kind: String
    let phone: String
}

struct CustomerAccountVehicle: Decodable, Identifiable, Hashable {
    let vehicleId: String
    let registration: String
    let registrationSystem: String
    let brand: String
    let model: String

    var id: String { vehicleId }

    var displayName: String {
        [brand, model].filter { !$0.isEmpty }.joined(separator: " ")
    }
}

private struct AccountSessionResponse: Decodable {
    let ok: Bool
    let accountId: String
}

private struct AccountVehiclesResponse: Decodable {
    let ok: Bool
    let vehicles: [CustomerAccountVehicle]
}

/// Does not use the installation inventory: that is scoped to the physical
/// device, not the authenticated customer account.
enum CustomerAccountAPI {
    static func validateStoredSession(session: URLSession = .shared) async throws -> Bool {
        guard let token = CustomerSessionKeychain.load() else { return false }
        do {
            let data = try await request("/api/mobile/auth/session", token: token, session: session)
            let result = try JSONDecoder().decode(AccountSessionResponse.self, from: data)
            return result.ok && !result.accountId.isEmpty
        } catch CustomerAccountAPIError.sessionExpired {
            CustomerSessionKeychain.clear(ifMatching: token)
            return false
        }
    }

    static func fetchProfile(session: URLSession = .shared) async throws -> CustomerAccountProfile {
        guard let token = CustomerSessionKeychain.load() else {
            throw CustomerAccountAPIError.sessionExpired
        }
        let data = try await request("/api/mobile/account/profile", token: token, session: session)
        let profile = try JSONDecoder().decode(CustomerAccountProfile.self, from: data)
        guard profile.ok, !profile.accountId.isEmpty,
              !profile.displayName.isEmpty, !profile.email.isEmpty else {
            throw CustomerAccountAPIError.invalidResponse
        }
        return profile
    }

    static func fetchOwnedVehicles(session: URLSession = .shared) async throws -> [CustomerAccountVehicle] {
        guard let token = CustomerSessionKeychain.load() else {
            throw CustomerAccountAPIError.sessionExpired
        }
        let data = try await request("/api/mobile/account/vehicles", token: token, session: session)
        let result = try JSONDecoder().decode(AccountVehiclesResponse.self, from: data)
        guard result.ok, result.vehicles.count <= 100 else {
            throw CustomerAccountAPIError.invalidResponse
        }
        return result.vehicles
    }

    private static func request(
        _ path: String, token: String, session: URLSession
    ) async throws -> Data {
        guard token.range(
            of: #"^[A-Za-z0-9_-]{32,128}$"#, options: .regularExpression
        ) != nil else {
            throw CustomerAccountAPIError.sessionExpired
        }
        var request = URLRequest(url: MobileAPI.endpoint(path))
        request.httpMethod = "GET"
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.timeoutInterval = 12
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw CustomerAccountAPIError.invalidResponse
        }
        if http.statusCode == 401 { throw CustomerAccountAPIError.sessionExpired }
        guard http.statusCode == 200 else { throw CustomerAccountAPIError.invalidResponse }
        return data
    }
}
