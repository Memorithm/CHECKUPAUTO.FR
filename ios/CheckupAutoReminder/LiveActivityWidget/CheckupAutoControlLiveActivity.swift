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
                CompactControlConvoy(state: context.state)
            } compactTrailing: {
                VStack(spacing: 0) {
                    Text("CT").font(.system(size: 10, weight: .heavy, design: .rounded))
                    Text(context.state.trailerDetail)
                        .font(.system(size: 8, weight: .semibold, design: .rounded))
                }
                .foregroundStyle(.white)
                .accessibilityLabel(context.state.journeyMessage)
            } minimal: {
                Image(systemName: "car.side.fill").foregroundStyle(.mint)
            }
            .contentMargins(.horizontal, 8, for: .expanded)
            .contentMargins(.bottom, 6, for: .expanded)
            .widgetURL(context.attributes.kind == .localTest ? nil : liveActivityURL(context.attributes.reminderId))
            .keylineTint(.mint)
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

private struct CompactControlConvoy: View {
    let state: CheckupControlActivityAttributes.ContentState
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.isLuminanceReduced) private var luminanceReduced

    var body: some View {
        HStack(spacing: 1) {
            Image(systemName: "car.side.fill").font(.system(size: 14)).scaleEffect(x: -1, y: 1)
            Capsule().frame(width: 3, height: 1)
            RoundedRectangle(cornerRadius: 2).frame(width: 12, height: 8)
        }
        .foregroundStyle(.mint)
        .offset(x: reduceMotion || luminanceReduced ? 0 : 6 - 12 * CheckupControlJourneyMotion.progress(for: state.animationSeed))
        .frame(width: 48, height: 25)
        .animation(reduceMotion || luminanceReduced ? nil : .linear(duration: 1.95), value: state.animationSeed)
        .accessibilityLabel("Voiture avec remorque vers le centre de contrôle technique")
    }
}
