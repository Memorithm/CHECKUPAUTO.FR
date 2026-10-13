import Foundation

enum CustomerAccountAPIError: Error {
    case sessionExpired
    case invalidResponse
    case vehicleRejected(String)
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

struct CustomerVehicleReferenceOption: Decodable, Hashable, Identifiable {
    let id: String
    let label: String
}

struct CustomerVehicleReferencesResponse: Decodable {
    let ok: Bool
    let brands: [CustomerVehicleReferenceOption]
    let energies: [CustomerVehicleReferenceOption]
    let models: [CustomerVehicleReferenceOption]?
}

struct CustomerVehicleCharacteristics: Encodable {
    let brand: String
    let model: String
    let energy: String
}

struct CustomerVehicleRegistrationDraft: Encodable {
    let registrationSystem: String
    let registration: String
    let formulaNumber: String
    let cardIssueDate: String
    let characteristics: CustomerVehicleCharacteristics
}

private struct SavedCustomerVehicleResponse: Decodable {
    let ok: Bool
    let vehicle: CustomerAccountVehicle
}

private struct CustomerVehicleErrorResponse: Decodable {
    let error: String?
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

    static func fetchVehicleReferences(
        brandId: String? = nil, session: URLSession = .shared
    ) async throws -> CustomerVehicleReferencesResponse {
        guard let token = CustomerSessionKeychain.load() else {
            throw CustomerAccountAPIError.sessionExpired
        }
        let query = brandId.map { [URLQueryItem(name: "brandId", value: $0)] } ?? []
        let data = try await request(
            "/api/mobile/account/vehicle-references", token: token,
            session: session, queryItems: query
        )
        let refs = try JSONDecoder().decode(CustomerVehicleReferencesResponse.self, from: data)
        guard refs.ok, refs.brands.count <= 2000, refs.energies.count <= 100,
              (refs.models?.count ?? 0) <= 2000,
              refs.brands.allSatisfy({ !$0.id.isEmpty && !$0.label.isEmpty }),
              refs.energies.allSatisfy({ !$0.id.isEmpty && !$0.label.isEmpty }),
              (refs.models ?? []).allSatisfy({ !$0.id.isEmpty && !$0.label.isEmpty }) else {
            throw CustomerAccountAPIError.invalidResponse
        }
        return refs
    }

    static func saveVehicle(
        _ payload: CustomerVehicleRegistrationDraft,
        session: URLSession = .shared
    ) async throws -> CustomerAccountVehicle {
        guard let token = CustomerSessionKeychain.load(),
              token.range(of: #"^[A-Za-z0-9_-]{32,128}$"#, options: .regularExpression) != nil else {
            throw CustomerAccountAPIError.sessionExpired
        }
        var request = URLRequest(url: MobileAPI.endpoint("/api/mobile/account/vehicles/save"))
        request.httpMethod = "POST"
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.timeoutInterval = 18
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONEncoder().encode(payload)
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw CustomerAccountAPIError.invalidResponse
        }
        if http.statusCode == 401 { throw CustomerAccountAPIError.sessionExpired }
        if http.statusCode == 422 {
            let code = (try? JSONDecoder().decode(CustomerVehicleErrorResponse.self, from: data))?.error ?? ""
            throw CustomerAccountAPIError.vehicleRejected(code)
        }
        guard http.statusCode == 201,
              let saved = try? JSONDecoder().decode(SavedCustomerVehicleResponse.self, from: data),
              saved.ok, !saved.vehicle.vehicleId.isEmpty else {
            throw CustomerAccountAPIError.invalidResponse
        }
        return saved.vehicle
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
        _ path: String, token: String, session: URLSession,
        queryItems: [URLQueryItem] = []
    ) async throws -> Data {
        guard token.range(
            of: #"^[A-Za-z0-9_-]{32,128}$"#, options: .regularExpression
        ) != nil else {
            throw CustomerAccountAPIError.sessionExpired
        }
        var url = MobileAPI.endpoint(path)
        if !queryItems.isEmpty {
            guard var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
                throw CustomerAccountAPIError.invalidResponse
            }
            components.queryItems = queryItems
            guard let resolved = components.url else {
                throw CustomerAccountAPIError.invalidResponse
            }
            url = resolved
        }
        var request = URLRequest(url: url)
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
