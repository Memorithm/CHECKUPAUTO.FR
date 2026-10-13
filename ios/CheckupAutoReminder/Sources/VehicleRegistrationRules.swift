import Foundation

enum VehicleRegistrationSystem: String, CaseIterable, Identifiable {
    case siv
    case fni

    var id: String { rawValue }

    var title: String {
        switch self {
        case .siv: "SIV — AA-123-AA"
        case .fni: "Ancien format FNI"
        }
    }
}

/// Mirrors customer_vehicle_inputs.py / customer_accounts.py; the server
/// revalidates all values before they are saved encrypted in the account.
enum VehicleRegistrationRules {
    private static let siv = "[A-HJ-NP-TV-Z]{2}[0-9]{3}[A-HJ-NP-TV-Z]{2}"
    private static let fni = "([0-9]{1,4})([A-Z]{1,3})([0-9]{2,3}|2[AB])"
    private static let formula = "[0-9]{4}[A-Z]{2}[0-9]{5}"

    static func compact(_ value: String) -> String {
        var result = ""
        for scalar in value.unicodeScalars {
            let code = scalar.value
            if CharacterSet.whitespacesAndNewlines.contains(scalar) ||
                code == 45 || (0x2010...0x2015).contains(code) || code == 0x2212 {
                continue
            }
            // ASCII-only case mapping; Unicode expansions (e.g. ß -> SS)
            // must never transform an invalid input into a valid plate.
            if (97...122).contains(code), let upper = UnicodeScalar(code - 32) {
                result.append(String(upper))
            } else {
                result.append(String(scalar))
            }
        }
        return result
    }

    private static func match(_ pattern: String, _ value: String) -> NSTextCheckingResult? {
        guard let regex = try? NSRegularExpression(pattern: "^(?:" + pattern + ")$") else {
            return nil
        }
        let range = NSRange(location: 0, length: (value as NSString).length)
        guard let result = regex.firstMatch(in: value, range: range),
              result.range == range else { return nil }
        return result
    }

    static func detectedSystem(_ value: String) -> VehicleRegistrationSystem? {
        guard let first = compact(value).unicodeScalars.first else { return nil }
        if (48...57).contains(first.value) { return .fni }
        if (65...90).contains(first.value) { return .siv }
        return nil
    }

    static func normalizedRegistration(
        _ value: String, system: VehicleRegistrationSystem
    ) -> String? {
        guard !value.isEmpty, value.utf8.count <= 64 else { return nil }
        let raw = compact(value)
        switch system {
        case .siv:
            guard match(siv, raw) != nil,
                  String(raw.prefix(2)) != "SS",
                  String(raw.suffix(2)) != "SS",
                  String(raw.dropFirst(2).prefix(3)) != "000" else { return nil }
            return String(raw.prefix(2)) + "-" + String(raw.dropFirst(2).prefix(3)) + "-" + String(raw.suffix(2))
        case .fni:
            guard let m = match(fni, raw) else { return nil }
            let source = raw as NSString
            let number = source.substring(with: m.range(at: 1))
            let letters = source.substring(with: m.range(at: 2))
            let department = source.substring(with: m.range(at: 3))
            guard Int(number) != 0, department.contains(where: { $0 != "0" }) else { return nil }
            return number + " " + letters + " " + department
        }
    }

    static func isValidFormula(_ value: String, currentYear: Int) -> Bool {
        guard value.utf8.count <= 64 else { return false }
        let raw = compact(value)
        guard match(formula, raw) != nil,
              let year = Int(raw.prefix(4)) else { return false }
        return (2009...currentYear).contains(year)
    }

    static func isValidCardIssueDate(_ date: Date, today: Date = .now) -> Bool {
        let calendar = Calendar(identifier: .gregorian)
        let start = calendar.date(from: DateComponents(year: 1900, month: 1, day: 1))!
        return date >= start && calendar.startOfDay(for: date) <= calendar.startOfDay(for: today)
    }

    static func validDocument(
        system: VehicleRegistrationSystem,
        formula: String,
        issueDate: Date?,
        today: Date = .now
    ) -> Bool {
        switch system {
        case .siv:
            return issueDate == nil &&
                isValidFormula(formula, currentYear: Calendar.current.component(.year, from: today))
        case .fni:
            guard compact(formula).isEmpty, let issueDate else { return false }
            return isValidCardIssueDate(issueDate, today: today)
        }
    }
}
