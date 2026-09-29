import ActivityKit
import SwiftUI
import WidgetKit

@main
struct CheckupAutoLiveActivityBundle: WidgetBundle {
    var body: some Widget {
        CheckupAutoControlLiveActivity()
    }
}

struct CheckupAutoControlLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: CheckupControlActivityAttributes.self) { context in
            lockScreen(context)
                .activityBackgroundTint(Color(red: 0.965, green: 0.970, blue: 0.945))
                .activitySystemActionForegroundColor(Color(red: 0.12, green: 0.33, blue: 0.26))
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    CarJourneyMark(seed: context.state.animationSeed, compact: false)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    Text(context.state.shortLabel)
                        .font(.caption.bold())
                        .foregroundStyle(.green)
                }
                DynamicIslandExpandedRegion(.center) {
                    VStack(spacing: 2) {
                        Text(context.state.primaryMessage)
                            .font(.headline)
                        Text(
                            context.state.moment == .localTest
                                ? "Démo locale · aucun rendez-vous réel"
                                : CheckupControlActivityPolicy.cardReminder
                        )
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                DynamicIslandExpandedRegion(.bottom) {
                    if context.state.moment == .localTest {
                        Text(
                            timerInterval: min(Date.now, context.state.appointmentAt)...context.state.appointmentAt,
                            pauseTime: context.state.appointmentAt,
                            countsDown: true,
                            showsHours: false
                        )
                            .font(.caption.monospacedDigit())
                    } else {
                        Text(context.state.appointmentAt, style: .time)
                            .font(.caption.monospacedDigit())
                    }
                }
            } compactLeading: {
                CarJourneyMark(seed: context.state.animationSeed, compact: true)
            } compactTrailing: {
                context.state.compactStatus
                    .font(.caption2.bold())
                    .monospacedDigit()
            } minimal: {
                Image(systemName: "car.side.fill")
                    .foregroundStyle(.green)
            }
            .widgetURL(
                context.attributes.kind == .localTest
                    ? nil
                    : liveActivityURL(context.attributes.reminderId)
            )
            .keylineTint(Color(red: 0.12, green: 0.33, blue: 0.26))
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

    private func lockScreen(_ context: ActivityViewContext<CheckupControlActivityAttributes>) -> some View {
        HStack(spacing: 14) {
            CarJourneyMark(seed: context.state.animationSeed, compact: false)
                .frame(width: 76)
            VStack(alignment: .leading, spacing: 4) {
                Text(context.state.primaryMessage)
                    .font(.headline)
                Text(context.state.moment == .localTest ? "Animation locale de démonstration" : CheckupControlActivityPolicy.cardReminder)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                if context.state.moment == .localTest {
                    Text(
                        timerInterval: min(Date.now, context.state.appointmentAt)...context.state.appointmentAt,
                        pauseTime: context.state.appointmentAt,
                        countsDown: true,
                        showsHours: false
                    )
                        .font(.caption.monospacedDigit())
                } else {
                    Text(context.state.appointmentAt, format: .dateTime.weekday(.wide).hour().minute())
                        .font(.caption.monospacedDigit())
                }
            }
            Spacer()
        }
        .padding(.horizontal, 14)
    }
}

private struct CarJourneyMark: View {
    let seed: Int
    let compact: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var phase: Int {
        (seed % 3 + 3) % 3
    }

    private var carPosition: CGFloat {
        let positions: [CGFloat] = compact ? [0, 10, 20] : [0, 16, 32]
        return positions[phase]
    }

    var body: some View {
        ZStack(alignment: .leading) {
            Capsule()
                .fill(Color.secondary.opacity(0.22))
                .frame(height: compact ? 2 : 3)

            if !compact {
                Image(systemName: "building.2.fill")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .trailing)
                    .opacity(0.72)
            }

            Image(systemName: "car.side.fill")
                .font(.system(size: compact ? 13 : 18, weight: .semibold))
                .foregroundStyle(Color(red: 0.12, green: 0.48, blue: 0.34))
                .offset(x: reduceMotion ? (compact ? 10 : 16) : carPosition)
                .animation(
                    reduceMotion ? nil : .easeInOut(duration: 1.7),
                    value: phase
                )
        }
        .frame(width: compact ? 44 : 72, height: compact ? 18 : 26)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Voiture en route vers le centre Checkup Auto")
    }
}

private extension CheckupControlActivityAttributes.ContentState {
    var compactStatus: some View {
        Text(compactMessage)
            .lineLimit(1)
            .minimumScaleFactor(0.65)
    }
}
