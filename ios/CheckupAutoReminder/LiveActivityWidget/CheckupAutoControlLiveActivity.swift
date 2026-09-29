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
            lockScreen(context)
                .activityBackgroundTint(Color(red: 0.965, green: 0.970, blue: 0.945))
                .activitySystemActionForegroundColor(Color(red: 0.12, green: 0.33, blue: 0.26))
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.trailing) {
                    Text(context.state.shortLabel)
                        .font(.caption2.bold())
                        .foregroundStyle(.mint)
                }
                DynamicIslandExpandedRegion(.center) {
                    VStack(spacing: 2) {
                        Text(context.state.primaryMessage).font(.headline)
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
                    VStack(spacing: 4) {
                        CarReminderScene(state: context.state, tint: .white, carTint: .mint)
                            .frame(height: 50)
                        activityTime(context.state)
                    }
                }
            } compactLeading: {
                CompactConvoyActor(state: context.state)
            } compactTrailing: {
                CompactConvoyMessage(state: context.state)
            } minimal: {
                Image(systemName: "car.side.fill").foregroundStyle(.mint)
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

    @ViewBuilder
    private func activityTime(_ state: CheckupControlActivityAttributes.ContentState) -> some View {
        if state.moment == .localTest {
            Text(
                timerInterval: min(Date.now, state.appointmentAt)...state.appointmentAt,
                pauseTime: state.appointmentAt,
                countsDown: true,
                showsHours: false
            )
            .font(.caption.monospacedDigit())
        } else {
            Text(state.appointmentAt, style: .time).font(.caption.monospacedDigit())
        }
    }

    private func lockScreen(_ context: ActivityViewContext<CheckupControlActivityAttributes>) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(context.state.primaryMessage).font(.headline)
            CarReminderScene(
                state: context.state,
                tint: Color(red: 0.12, green: 0.33, blue: 0.26),
                carTint: Color(red: 0.12, green: 0.48, blue: 0.34)
            )
            .frame(height: 50)
            Text(
                context.state.moment == .localTest
                    ? "Animation locale de démonstration"
                    : CheckupControlActivityPolicy.cardReminder
            )
            .font(.caption)
            .foregroundStyle(.secondary)
            activityTime(context.state)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 6)
    }
}

/// One moving HStack attaches the reminder to the car until the character exits.
private struct CarReminderScene: View {
    let state: CheckupControlActivityAttributes.ContentState
    let tint: Color
    let carTint: Color
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.isLuminanceReduced) private var luminanceReduced

    private var still: Bool { reduceMotion || luminanceReduced }
    private var seed: Int { still ? 4 : state.animationSeed }

    var body: some View {
        GeometryReader { geometry in
            let width = geometry.size.width
            let departed = CheckupControlConvoyMotion.carFacesRight(for: seed)
            let trainWidth: CGFloat = 142
            let carX = CGFloat(CheckupControlConvoyMotion.carOffset(for: seed, trackWidth: Double(width)))
            let characterX = max(0, width - 36) * CGFloat(CheckupControlConvoyMotion.characterProgress(for: seed))

            ZStack(alignment: .topLeading) {
                Rectangle()
                    .fill(tint.opacity(0.32))
                    .frame(height: 1)
                    .offset(y: 47)

                HStack(spacing: 3) {
                    Image(systemName: "car.side.fill")
                        .font(.system(size: 18, weight: .semibold))
                        .scaleEffect(x: departed ? 1 : -1, y: 1)
                        .frame(width: 24)
                        .foregroundStyle(carTint)
                    Capsule()
                        .fill(tint)
                        .frame(width: 8, height: 2)
                        .opacity(departed ? 0 : 1)
                    Text(state.trailerMessage)
                        .font(.system(size: 12, weight: .bold, design: .rounded))
                        .lineLimit(1)
                        .minimumScaleFactor(0.85)
                        .frame(width: 104, alignment: .leading)
                        .foregroundStyle(tint)
                        .opacity(departed ? 0 : 1)
                }
                .frame(width: trainWidth, height: 26, alignment: .leading)
                .offset(x: carX, y: 21)

                LineaCharacter(
                    stride: CheckupControlConvoyMotion.stride(for: seed),
                    gesture: CheckupControlConvoyMotion.gesture(for: seed),
                    facingRight: CheckupControlConvoyMotion.characterFacesCar(for: seed),
                    tint: tint
                )
                .frame(width: 36, height: 44)
                .offset(x: characterX, y: 6)
                .opacity(CheckupControlConvoyMotion.characterIsVisible(for: seed) ? 1 : 0)

                Text(state.trailerMessage)
                    .font(.system(size: 10, weight: .bold, design: .rounded))
                    .foregroundStyle(tint)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 3)
                    .overlay(RoundedRectangle(cornerRadius: 7).stroke(tint, lineWidth: 1))
                    .offset(x: characterX + 35, y: 0)
                    .opacity(CheckupControlConvoyMotion.characterFacesCar(for: seed) ? 1 : 0)
            }
            .frame(width: width, height: 50, alignment: .topLeading)
            .clipped()
            .animation(
                still || !CheckupControlConvoyMotion.animatesTransition(for: seed)
                    ? nil : .linear(duration: CheckupControlConvoyMotion.animationDuration),
                value: state.animationSeed
            )
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(state.trailerMessage + ". Le personnage sort de la voiture et lui rappelle l’échéance du contrôle technique.")
    }
}

/// Camera-separated compact regions use the same offset during the convoy pass.
private struct CompactConvoyActor: View {
    let state: CheckupControlActivityAttributes.ContentState
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.isLuminanceReduced) private var luminanceReduced

    private var still: Bool { reduceMotion || luminanceReduced }
    private var seed: Int { still ? 4 : state.animationSeed }

    var body: some View {
        Group {
            if CheckupControlConvoyMotion.characterIsVisible(for: seed) {
                LineaCharacter(
                    stride: CheckupControlConvoyMotion.stride(for: seed),
                    gesture: CheckupControlConvoyMotion.gesture(for: seed),
                    facingRight: CheckupControlConvoyMotion.characterFacesCar(for: seed),
                    tint: .white
                )
                .frame(width: 20, height: 26)
            } else {
                Image(systemName: "car.side.fill")
                    .font(.system(size: 14, weight: .semibold))
                    .scaleEffect(x: -1, y: 1)
                    .foregroundStyle(.mint)
            }
        }
        .offset(x: still ? 0 : CGFloat(CheckupControlConvoyMotion.compactOffset(for: seed)))
        .frame(width: 52, height: 28)
        .clipped()
        .animation(
            still || !CheckupControlConvoyMotion.animatesTransition(for: seed)
                ? nil : .linear(duration: CheckupControlConvoyMotion.animationDuration),
            value: state.animationSeed
        )
        .accessibilityLabel("Voiture et personnage du rappel Checkup Auto")
    }
}

private struct CompactConvoyMessage: View {
    let state: CheckupControlActivityAttributes.ContentState
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.isLuminanceReduced) private var luminanceReduced

    private var still: Bool { reduceMotion || luminanceReduced }
    private var seed: Int { still ? 4 : state.animationSeed }
    private var offset: CGFloat {
        still || CheckupControlConvoyMotion.carFacesRight(for: seed)
            ? 0 : CGFloat(CheckupControlConvoyMotion.compactOffset(for: seed))
    }

    var body: some View {
        VStack(spacing: 0) {
            Text(state.trailerHeading).font(.system(size: 9, weight: .heavy, design: .rounded))
            Text(state.trailerDetail).font(.system(size: 9, weight: .bold, design: .rounded))
        }
        .foregroundStyle(.white)
        .fixedSize()
        .offset(x: offset)
        .frame(width: 52, height: 28)
        .clipped()
        .animation(
            still || !CheckupControlConvoyMotion.animatesTransition(for: seed)
                ? nil : .linear(duration: CheckupControlConvoyMotion.animationDuration),
            value: state.animationSeed
        )
        .accessibilityLabel(state.trailerMessage)
    }
}
