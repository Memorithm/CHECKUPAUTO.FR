import XCTest
@testable import CheckupAutoReminder

final class VehicleRegistrationRulesTests: XCTestCase {
    func testSIVNormalizationAndRejectedReservedCombinations() {
        XCTAssertEqual(VehicleRegistrationRules.normalizedRegistration("aa 123 aa", system: .siv), "AA-123-AA")
        XCTAssertEqual(VehicleRegistrationRules.normalizedRegistration("ab–123–cd", system: .siv), "AB-123-CD")
        for bad in ["SS-123-AA", "AA-123-SS", "AA-000-BB", "AI-123-AA",
                    "AO-123-CD", "AA-123-AU", "AB-123", "AB-123-CDE",
                    "ÄA-123-CD", "Aß-123-CD", "AA-123-CD💡"] {
            XCTAssertNil(VehicleRegistrationRules.normalizedRegistration(bad, system: .siv), bad)
        }
    }

    func testFNINormalizationIncludingCorsicaAndOverseas() {
        XCTAssertEqual(VehicleRegistrationRules.normalizedRegistration("1234 ab 78", system: .fni), "1234 AB 78")
        XCTAssertEqual(VehicleRegistrationRules.normalizedRegistration("123ab2a", system: .fni), "123 AB 2A")
        XCTAssertEqual(VehicleRegistrationRules.normalizedRegistration("123 AB 971", system: .fni), "123 AB 971")
        for bad in ["0 AB 75", "123 AB 00", "123 AB", "AA-123-AA", "123 ABCD 75"] {
            XCTAssertNil(VehicleRegistrationRules.normalizedRegistration(bad, system: .fni), bad)
        }
    }

    func testFormulaMustMatchWebGrammarAndYear() {
        XCTAssertTrue(VehicleRegistrationRules.isValidFormula("2020ab12345", currentYear: 2026))
        XCTAssertFalse(VehicleRegistrationRules.isValidFormula("2020ab1234", currentYear: 2026))
        XCTAssertFalse(VehicleRegistrationRules.isValidFormula("2008AB12345", currentYear: 2026))
        XCTAssertFalse(VehicleRegistrationRules.isValidFormula("2027AB12345", currentYear: 2026))
        XCTAssertFalse(VehicleRegistrationRules.isValidFormula("2020Aß12345", currentYear: 2026))
    }

    func testDocumentDependsOnSIVOrFNIWithoutConfusingCertificateAndCTDates() {
        let calendar = Calendar(identifier: .gregorian)
        let issueDate = calendar.date(from: DateComponents(year: 2020, month: 5, day: 15))!
        let today = calendar.date(from: DateComponents(year: 2026, month: 10, day: 14))!
        XCTAssertTrue(VehicleRegistrationRules.validDocument(system: .siv, formula: "2020AB12345", issueDate: nil, today: today))
        XCTAssertFalse(VehicleRegistrationRules.validDocument(system: .siv, formula: "", issueDate: issueDate, today: today))
        XCTAssertTrue(VehicleRegistrationRules.validDocument(system: .fni, formula: "", issueDate: issueDate, today: today))
        XCTAssertFalse(VehicleRegistrationRules.validDocument(system: .fni, formula: "2020AB12345", issueDate: issueDate, today: today))
        XCTAssertFalse(VehicleRegistrationRules.validDocument(system: .fni, formula: "", issueDate: today.addingTimeInterval(86400), today: today))
    }

    func testRegistrationSystemDetectionIsAsciiAndNeverGuesses() {
        XCTAssertEqual(VehicleRegistrationRules.detectedSystem("AA123AA"), .siv)
        XCTAssertEqual(VehicleRegistrationRules.detectedSystem("123AB75"), .fni)
        XCTAssertNil(VehicleRegistrationRules.detectedSystem("éé-123-aa"))
    }
}
