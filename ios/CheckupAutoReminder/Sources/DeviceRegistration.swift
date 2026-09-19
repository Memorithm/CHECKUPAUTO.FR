import Foundation
import Security

struct DeviceRegistrationRequest: Codable, Equatable, Sendable {
    let installationId: String
    let registrationSecret: String
    let deviceToken: String
    let environment: String

    func validated() throws -> DeviceRegistrationRequest {
        guard UUID(uuidString: installationId)?.uuidString.lowercased() == installationId.lowercased() else {
            throw DeviceRegistrationError.invalidIdentity
        }
        let secretChars = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
        guard (32...128).contains(registrationSecret.count), registrationSecret.unicodeScalars.allSatisfy(secretChars.contains) else {
            throw DeviceRegistrationError.invalidIdentity
        }
        let token = deviceToken.lowercased()
        let hex = CharacterSet(charactersIn: "0123456789abcdef")
        guard (32...400).contains(token.count), token.count.isMultiple(of: 2), token.unicodeScalars.allSatisfy(hex.contains),
              environment == "sandbox" || environment == "production" else {
            throw DeviceRegistrationError.invalidToken
        }
        return self
    }
}

struct DeviceUnregistrationRequest: Codable, Equatable, Sendable {
    let installationId: String
    let registrationSecret: String

    func validated() throws -> DeviceUnregistrationRequest {
        guard UUID(uuidString: installationId)?.uuidString.lowercased() == installationId.lowercased() else {
            throw DeviceRegistrationError.invalidIdentity
        }
        let secretChars = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
        guard (32...128).contains(registrationSecret.count),
              registrationSecret.unicodeScalars.allSatisfy(secretChars.contains) else {
            throw DeviceRegistrationError.invalidIdentity
        }
        return self
    }
}

enum DeviceRegistrationState {
    static let defaultsKey = "checkupauto.remote-push.registered.v1"
    static let changedNotification = Notification.Name("CheckupAutoRemotePushRegistrationChanged")

    static func isRegistered(defaults: UserDefaults = .standard) -> Bool {
        defaults.bool(forKey: defaultsKey)
    }

    static func setRegistered(
        _ registered: Bool,
        defaults: UserDefaults = .standard,
        center: NotificationCenter = .default
    ) {
        let previous = defaults.bool(forKey: defaultsKey)
        defaults.set(registered, forKey: defaultsKey)
        if previous != registered {
            center.post(name: changedNotification, object: nil)
        }
    }
}

enum DeviceRegistrationError: Error {
    case invalidIdentity
    case invalidToken
    case keychainFailure
    case invalidResponse
}

enum DeviceRegistrationIdentity {
    private static let service = "fr.checkupauto.reminder.push"

    static func loadExisting() -> (installationId: String, secret: String)? {
        guard let install = read(account: "installation-id"),
              let secret = read(account: "registration-secret") else {
            return nil
        }
        return (install, secret)
    }

    static func loadOrCreate() throws -> (installationId: String, secret: String) {
        if let existing = loadExisting() {
            return existing
        }
        let install = UUID().uuidString.lowercased()
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
            throw DeviceRegistrationError.keychainFailure
        }
        let secret = Data(bytes).base64EncodedString().replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
        try write(install, account: "installation-id")
        try write(secret, account: "registration-secret")
        return (install, secret)
    }

    private static func read(account: String) -> String? {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service, kSecAttrAccount as String: account,
                                    kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func write(_ value: String, account: String) throws {
        let data = Data(value.utf8)
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                    kSecAttrService as String: service, kSecAttrAccount as String: account]
        SecItemDelete(query as CFDictionary)
        var add = query; add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        guard SecItemAdd(add as CFDictionary, nil) == errSecSuccess else { throw DeviceRegistrationError.keychainFailure }
    }
}

enum DeviceRegistrationClient {
    static var endpoint: URL { MobileAPI.endpoint("/api/mobile/devices/register") }
    static var unregisterEndpoint: URL { MobileAPI.endpoint("/api/mobile/devices/unregister") }

    static func register(deviceToken: Data, session: URLSession = .shared) async throws {
        DeviceRegistrationState.setRegistered(false)
        let identity = try DeviceRegistrationIdentity.loadOrCreate()
        let token = deviceToken.map { String(format: "%02x", $0) }.joined()
        #if DEBUG
        let environment = "sandbox"
        #else
        let environment = "production"
        #endif
        let payload = try DeviceRegistrationRequest(installationId: identity.installationId,
            registrationSecret: identity.secret, deviceToken: token, environment: environment).validated()
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"; request.timeoutInterval = 8
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONEncoder().encode(payload)
        let (_, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 201 else {
            throw DeviceRegistrationError.invalidResponse
        }
        DeviceRegistrationState.setRegistered(true)
    }

    @discardableResult
    static func unregister(session: URLSession = .shared) async throws -> Bool {
        guard let identity = DeviceRegistrationIdentity.loadExisting() else {
            DeviceRegistrationState.setRegistered(false)
            return false
        }
        let payload = try DeviceUnregistrationRequest(
            installationId: identity.installationId,
            registrationSecret: identity.secret
        ).validated()
        var request = URLRequest(url: unregisterEndpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = 8
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try JSONEncoder().encode(payload)
        let (_, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw DeviceRegistrationError.invalidResponse
        }
        DeviceRegistrationState.setRegistered(false)
        return true
    }
}
