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
                        Text(CheckupControlActivityPolicy.cardReminder)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                DynamicIslandExpandedRegion(.bottom) {
                    Text(context.state.appointmentAt, style: .time)
                        .font(.caption.monospacedDigit())
                }
            } compactLeading: {
                CarJourneyMark(seed: context.state.animationSeed, compact: true)
            } compactTrailing: {
                Text(context.state.kindLabel)
                    .font(.caption2.bold())
                    .monospacedDigit()
            } minimal: {
                Image(systemName: "car.side.fill")
                    .foregroundStyle(.green)
            }
            .widgetURL(URL(string: "https://www.checkupauto.fr/app/live?source=dynamic-island"))
            .keylineTint(Color(red: 0.12, green: 0.33, blue: 0.26))
        }
    }

    private func lockScreen(_ context: ActivityViewContext<CheckupControlActivityAttributes>) -> some View {
        HStack(spacing: 14) {
            CarJourneyMark(seed: context.state.animationSeed, compact: false)
                .frame(width: 76)
            VStack(alignment: .leading, spacing: 4) {
                Text(context.state.primaryMessage)
                    .font(.headline)
                Text(CheckupControlActivityPolicy.cardReminder)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                Text(context.state.appointmentAt, format: .dateTime.weekday(.wide).hour().minute())
                    .font(.caption.monospacedDigit())
            }
            Spacer()
        }
        .padding(.horizontal, 14)
    }
}

private struct CarJourneyMark: View {
    let seed: Int
    let compact: Bool
    @Environment(\.isLuminanceReduced) private var luminanceReduced

    var body: some View {
        ZStack(alignment: .leading) {
            Capsule()
                .fill(Color.secondary.opacity(0.18))
                .frame(height: compact ? 2 : 3)
            Image(systemName: "building.2.fill")
                .font(.system(size: compact ? 9 : 12))
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .trailing)

            Image(systemName: "car.side.fill")
                .font(.system(size: compact ? 13 : 18, weight: .semibold))
                .foregroundStyle(Color(red: 0.12, green: 0.48, blue: 0.34))
                .id(seed)
                .transition(.asymmetric(insertion: .move(edge: .leading).combined(with: .opacity), removal: .opacity))
                .offset(x: luminanceReduced ? (compact ? 7 : 18) : (compact ? 14 : 34))
        }
        .frame(width: compact ? 34 : 72, height: compact ? 18 : 26)
        .accessibilityLabel("Voiture en route vers le centre Checkup Auto")
    }
}

private extension CheckupControlActivityAttributes.ContentState {
    var kindLabel: String {
        switch moment {
        case .tomorrow: return "J-1"
        case .approaching:
            let seconds = max(0, appointmentAt.timeIntervalSinceNow)
            let hours = max(1, Int((seconds / 3600).rounded(.up)))
            return "\(hours)h"
        case .acknowledged: return "✓"
        }
    }
}
