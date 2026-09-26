import ActivityKit
import Foundation

@available(iOS 26.0, *)
enum CheckupControlLiveActivityCoordinator {
    static func schedule(appointmentAt: Date, reference: UUID = UUID(), leadHours: Int = CheckupControlActivityPolicy.dayOfLeadHours) throws {
        guard ActivityAuthorizationInfo().areActivitiesEnabled else { return }

        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Europe/Paris") ?? .current

        if let start = CheckupControlActivityPolicy.dayBeforeStart(for: appointmentAt, calendar: calendar),
           start > Date() {
            try scheduleOne(
                appointmentAt: appointmentAt,
                start: start,
                kind: .dayBefore,
                moment: .tomorrow,
                reminderId: reference.uuidString + "-j1"
            )
        }

        if let start = CheckupControlActivityPolicy.dayOfStart(for: appointmentAt, leadHours: leadHours, calendar: calendar),
           start > Date() {
            try scheduleOne(
                appointmentAt: appointmentAt,
                start: start,
                kind: .dayOf,
                moment: .approaching,
                reminderId: reference.uuidString + "-j0"
            )
        }
    }

    static func acknowledgeAll() async {
        for activity in Activity<CheckupControlActivityAttributes>.activities {
            let state = CheckupControlActivityAttributes.ContentState(
                moment: .acknowledged,
                appointmentAt: activity.content.state.appointmentAt,
                animationSeed: activity.content.state.animationSeed + 1
            )
            await activity.end(
                ActivityContent(state: state, staleDate: Date()),
                dismissalPolicy: .immediate
            )
        }
    }

    private static func scheduleOne(
        appointmentAt: Date,
        start: Date,
        kind: CheckupControlActivityAttributes.ReminderKind,
        moment: CheckupControlActivityAttributes.ContentState.Moment,
        reminderId: String
    ) throws {
        let attributes = CheckupControlActivityAttributes(reminderId: reminderId, kind: kind)
        let state = CheckupControlActivityAttributes.ContentState(
            moment: moment,
            appointmentAt: appointmentAt,
            animationSeed: Int(start.timeIntervalSince1970.rounded())
        )
        let content = ActivityContent(
            state: state,
            staleDate: min(appointmentAt, start.addingTimeInterval(60 * 60 * 4)),
            relevanceScore: kind == .dayOf ? 100 : 70
        )
        let alert = AlertConfiguration(
            title: moment == .tomorrow ? "Contrôle technique demain" : "Contrôle technique aujourd’hui",
            body: CheckupControlActivityPolicy.cardReminder,
            sound: .default
        )
        _ = try Activity<CheckupControlActivityAttributes>.request(
            attributes: attributes,
            content: content,
            pushType: nil,
            style: .standard,
            alertConfiguration: alert,
            start: start
        )
    }
}
