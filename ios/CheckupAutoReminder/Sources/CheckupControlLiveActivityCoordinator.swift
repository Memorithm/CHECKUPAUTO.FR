import ActivityKit
import BackgroundTasks
import Foundation

@available(iOS 26.0, *)
enum CheckupControlLiveActivityCoordinator {
    static func schedule(
        appointmentAt: Date,
        reference: UUID,
        leadHours: Int = CheckupControlActivityPolicy.dayOfLeadHours
    ) async throws {
        let now = Date()
        guard ActivityAuthorizationInfo().areActivitiesEnabled, appointmentAt > now else { return }

        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Europe/Paris") ?? .current
        let appointmentToken = Int(appointmentAt.timeIntervalSince1970.rounded())
        let prefix = reference.uuidString + "-"
        let expectedPrefix = prefix + String(appointmentToken) + "-"

        for activity in Activity<CheckupControlActivityAttributes>.activities
        where activity.attributes.reminderId.hasPrefix(prefix)
            && !activity.attributes.reminderId.hasPrefix(expectedPrefix) {
            await activity.end(nil, dismissalPolicy: .immediate)
        }

        let existing = Set(
            Activity<CheckupControlActivityAttributes>.activities.map { $0.attributes.reminderId }
        )

        if let start = CheckupControlActivityPolicy.dayBeforeStart(for: appointmentAt, calendar: calendar) {
            let reminderId = expectedPrefix + "j1"
            let sameDay = calendar.isDate(now, inSameDayAs: start)
            if (start > now || sameDay),
               CheckupControlActivityPolicy.isInsideSchedulingLookahead(start, now: now),
               !existing.contains(reminderId),
               !Acknowledgements.contains(reminderId) {
                try scheduleOne(
                    appointmentAt: appointmentAt,
                    requestedStart: start,
                    allowImmediate: sameDay,
                    kind: .dayBefore,
                    moment: .tomorrow,
                    reminderId: reminderId
                )
            }
        }

        if let start = CheckupControlActivityPolicy.dayOfStart(for: appointmentAt, leadHours: leadHours, calendar: calendar) {
            let reminderId = expectedPrefix + "j0"
            let insideLeadWindow = now >= start && now < appointmentAt
            if (start > now || insideLeadWindow),
               CheckupControlActivityPolicy.isInsideSchedulingLookahead(start, now: now),
               !existing.contains(reminderId),
               !Acknowledgements.contains(reminderId) {
                try scheduleOne(
                    appointmentAt: appointmentAt,
                    requestedStart: start,
                    allowImmediate: insideLeadWindow,
                    kind: .dayOf,
                    moment: .approaching,
                    reminderId: reminderId
                )
            }
        }
    }

    static func cancel(reference: UUID) async {
        let prefix = reference.uuidString + "-"
        for activity in Activity<CheckupControlActivityAttributes>.activities
        where activity.attributes.reminderId.hasPrefix(prefix) {
            await activity.end(nil, dismissalPolicy: .immediate)
        }
    }

    static func acknowledge(reminderId: String?) async {
        guard let reminderId, !reminderId.isEmpty else { return }
        Acknowledgements.insert(reminderId)
        for activity in Activity<CheckupControlActivityAttributes>.activities
        where activity.attributes.reminderId == reminderId {
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

    static func clearAll() async {
        Acknowledgements.clear()
        for activity in Activity<CheckupControlActivityAttributes>.activities {
            await activity.end(nil, dismissalPolicy: .immediate)
        }
    }

    private static func scheduleOne(
        appointmentAt: Date,
        requestedStart: Date,
        allowImmediate: Bool,
        kind: CheckupControlActivityAttributes.ReminderKind,
        moment: CheckupControlActivityAttributes.ContentState.Moment,
        reminderId: String
    ) throws {
        let attributes = CheckupControlActivityAttributes(reminderId: reminderId, kind: kind)
        let state = CheckupControlActivityAttributes.ContentState(
            moment: moment,
            appointmentAt: appointmentAt,
            animationSeed: Int(requestedStart.timeIntervalSince1970.rounded())
        )
        let now = Date()
        let effectiveStart = requestedStart > now ? requestedStart : now
        let content = ActivityContent(
            state: state,
            staleDate: min(appointmentAt, effectiveStart.addingTimeInterval(60 * 60 * 4)),
            relevanceScore: kind == .dayOf ? 100 : 70
        )
        let alert = AlertConfiguration(
            title: moment == .tomorrow ? "Contrôle technique demain" : "Contrôle technique aujourd’hui",
            body: LocalizedStringResource(stringLiteral: CheckupControlActivityPolicy.cardReminder),
            sound: .default
        )
        if requestedStart > now {
            _ = try Activity<CheckupControlActivityAttributes>.request(
                attributes: attributes,
                content: content,
                pushType: nil,
                style: .standard,
                alertConfiguration: alert,
                start: requestedStart
            )
        } else if allowImmediate {
            _ = try Activity<CheckupControlActivityAttributes>.request(
                attributes: attributes,
                content: content,
                pushType: nil,
                style: .standard
            )
        }
    }
}

@available(iOS 26.0, *)
private enum Acknowledgements {
    private static let key = "checkupauto.live-activity.acknowledged.v1"

    static func contains(_ reminderId: String, defaults: UserDefaults = .standard) -> Bool {
        (defaults.stringArray(forKey: key) ?? []).contains(reminderId)
    }

    static func insert(_ reminderId: String, defaults: UserDefaults = .standard) {
        var ids = defaults.stringArray(forKey: key) ?? []
        ids.removeAll { $0 == reminderId }
        ids.append(reminderId)
        if ids.count > 64 {
            ids.removeFirst(ids.count - 64)
        }
        defaults.set(ids, forKey: key)
    }

    static func clear(defaults: UserDefaults = .standard) {
        defaults.removeObject(forKey: key)
    }
}


@available(iOS 26.0, *)
enum CheckupControlLiveActivityRetryScheduler {
    static let taskIdentifier = "fr.checkupauto.reminder.live-activity-refresh"

    @discardableResult
    static func register() -> Bool {
        BGTaskScheduler.shared.register(forTaskWithIdentifier: taskIdentifier, using: nil) { task in
            guard let refreshTask = task as? BGAppRefreshTask else {
                task.setTaskCompleted(success: false)
                return
            }
            handle(refreshTask)
        }
    }

    static func submit(
        for vehicles: [AuthoritativeVehicleDeadline],
        retryFailed: Bool = false,
        now: Date = Date()
    ) {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Europe/Paris") ?? .current
        var candidateDates = vehicles.compactMap { vehicle -> Date? in
            guard let appointmentAt = vehicle.appointmentAtValue, appointmentAt > now else {
                return nil
            }
            return CheckupControlActivityPolicy.retryDate(
                for: appointmentAt,
                now: now,
                calendar: calendar
            )
        }
        if retryFailed {
            candidateDates.append(now.addingTimeInterval(60 * 60))
        }

        BGTaskScheduler.shared.cancel(taskRequestWithIdentifier: taskIdentifier)
        guard let earliest = candidateDates.min() else { return }
        let request = BGAppRefreshTaskRequest(identifier: taskIdentifier)
        request.earliestBeginDate = earliest
        try? BGTaskScheduler.shared.submit(request)
    }

    private static func handle(_ backgroundTask: BGAppRefreshTask) {
        let work = Task {
            let previous = AuthoritativeInventoryStore.load()
            let response: AuthoritativeInventoryResponse
            do {
                response = try await AuthoritativeInventoryClient.fetch(
                    requireFreshAppointments: true
                )
            } catch {
                submit(for: previous, retryFailed: true)
                backgroundTask.setTaskCompleted(success: false)
                return
            }
            if Task.isCancelled {
                submit(for: previous, retryFailed: true)
                backgroundTask.setTaskCompleted(success: false)
                return
            }

            let vehicles = response.vehicles
            let currentBindings = Set(vehicles.map(\.bindingId))
            for stale in previous where !currentBindings.contains(stale.bindingId) {
                if let reference = stale.bindingUUID {
                    await CheckupControlLiveActivityCoordinator.cancel(reference: reference)
                }
            }
            AuthoritativeInventoryStore.save(vehicles)

            var retryFailed = false
            for vehicle in vehicles {
                if Task.isCancelled { break }
                guard let reference = vehicle.bindingUUID else { continue }
                guard let appointmentAt = vehicle.appointmentAtValue,
                      appointmentAt > Date() else {
                    await CheckupControlLiveActivityCoordinator.cancel(reference: reference)
                    continue
                }
                do {
                    try await CheckupControlLiveActivityCoordinator.schedule(
                        appointmentAt: appointmentAt,
                        reference: reference
                    )
                } catch {
                    retryFailed = true
                }
            }

            if Task.isCancelled {
                submit(for: vehicles, retryFailed: true)
                backgroundTask.setTaskCompleted(success: false)
                return
            }
            submit(for: vehicles, retryFailed: retryFailed)
            backgroundTask.setTaskCompleted(success: !retryFailed)
        }
        backgroundTask.expirationHandler = {
            work.cancel()
        }
    }
}
