import Foundation

enum CheckupControlHornChoice: String, CaseIterable, Identifiable {
    case short, double, low

    var id: String { rawValue }
    var label: String {
        switch self {
        case .short: return "Court"
        case .double: return "Double"
        case .low: return "Grave"
        }
    }
    var soundName: String {
        switch self {
        case .short: return "checkupauto-horn.wav"
        case .double: return "checkupauto-horn-double.wav"
        case .low: return "checkupauto-horn-low.wav"
        }
    }
    private static let defaultsKey = "checkupauto.horn-choice.v1"
    static var current: Self { load() }
    static func load(defaults: UserDefaults = .standard) -> Self {
        defaults.string(forKey: defaultsKey).flatMap(Self.init(rawValue:)) ?? .short
    }
    func save(defaults: UserDefaults = .standard) {
        defaults.set(rawValue, forKey: Self.defaultsKey)
    }
}
