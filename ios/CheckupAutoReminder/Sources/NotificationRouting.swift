import Foundation

enum NotificationRouting {
    static let controlDueCategory = "CHECKUPAUTO_CT_DUE"
    static let bookAction = "CHECKUPAUTO_BOOK"
}

extension Notification.Name {
    /// Posted when the customer taps "Réserver" on a control-due reminder, so
    /// the signed-in app presents the in-app booking journey instead of leaving
    /// for the website.
    static let checkupBookingRequested = Notification.Name("CheckupAutoBookingRequested")
}
