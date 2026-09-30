import ActivityKit
import SwiftUI
import WidgetKit

@main
struct CheckupAutoLiveActivityBundle: WidgetBundle {
    var body: some Widget { CheckupAutoControlLiveActivity() }
}

struct CheckupAutoControlLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: CheckupControlActivityAttributes.self) { context in
            VStack(spacing: 4) {
                HStack {
                    Text("Checkup Auto").font(.subheadline.bold())
                    Spacer()
                    activityTime(context.state)
                }
                CheckupControlJourneyScene(state: context.state, darkBackground: false)
                    .frame(height: 102)
                Text(context.state.moment == .localTest
                     ? "Démo locale · aucun rendez-vous réel"
                     : CheckupControlActivityPolicy.cardReminder)
                    .font(.system(size: 11))
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .activityBackgroundTint(Color(red: 0.965, green: 0.970, blue: 0.945))
            .activitySystemActionForegroundColor(Color(red: 0.12, green: 0.33, blue: 0.26))
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    Text("CHECKUP AUTO")
                        .font(.system(size: 10, weight: .bold, design: .rounded))
                        .foregroundStyle(.mint)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    Text(context.state.moment == .localTest ? "DÉMO" : context.state.shortLabel)
                        .font(.system(size: 10, weight: .semibold))
                }
                DynamicIslandExpandedRegion(.bottom, priority: 1) {
                    VStack(spacing: 3) {
                        CheckupControlJourneyScene(state: context.state)
                            .frame(height: 102)
                        HStack {
                            Text(context.state.moment == .localTest
                                 ? "Démo locale · aucun rendez-vous réel"
                                 : CheckupControlActivityPolicy.cardReminder)
                                .font(.system(size: 10))
                            Spacer(minLength: 4)
                            activityTime(context.state)
                        }
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 4)
                    }
                    .frame(maxWidth: .infinity)
                }
            } compactLeading: {
                CheckupControlCompactReminder(state: context.state)
            } compactTrailing: {
                EmptyView()
            } minimal: {
                CheckupControlVehicleImage(presentation: .minimal)
            }
            .contentMargins(.horizontal, 8, for: .expanded)
            .contentMargins(.bottom, 6, for: .expanded)
            .widgetURL(context.attributes.kind == .localTest ? nil : liveActivityURL(context.attributes.reminderId))
            .keylineTint(CheckupControlReminderStyle.color(darkBackground: true))
        }
    }

    @ViewBuilder
    private func activityTime(_ state: CheckupControlActivityAttributes.ContentState) -> some View {
        if state.moment == .localTest {
            Text(timerInterval: min(Date.now, state.appointmentAt)...state.appointmentAt,
                 pauseTime: state.appointmentAt, countsDown: true, showsHours: false)
                .font(.system(size: 10).monospacedDigit())
        } else {
            Text(state.appointmentAt, style: .time).font(.caption.monospacedDigit())
        }
    }

    private func liveActivityURL(_ reminderId: String) -> URL? {
        var components = URLComponents(string: "https://www.checkupauto.fr/app/live")
        components?.queryItems = [
            URLQueryItem(name: "source", value: "dynamic-island"),
            URLQueryItem(name: "reminder", value: reminderId),
        ]
        return components?.url
    }
}

