import Foundation

@main
struct ReminderPlanSmoke {
    static func main() {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let due = calendar.date(from: DateComponents(year: 2027, month: 1, day: 1))!
        let now = calendar.date(from: DateComponents(year: 2026, month: 10, day: 1))!
        let moments = ReminderPlan.moments(dueDate: due, now: now, calendar: calendar)
        precondition(moments.map(\.daysBefore) == [60, 30, 15, 7, 1])

        let late = calendar.date(from: DateComponents(year: 2026, month: 12, day: 20))!
        let remaining = ReminderPlan.moments(dueDate: due, now: late, calendar: calendar)
        precondition(remaining.map(\.daysBefore) == [7, 1])
        precondition(remaining.allSatisfy { $0.fireDate > late })
        print("REMINDER_PLAN_SMOKE_OK")
    }
}
