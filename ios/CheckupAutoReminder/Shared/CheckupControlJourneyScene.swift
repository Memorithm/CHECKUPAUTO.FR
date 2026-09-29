import SwiftUI

/// The same native scene is used by the expanded island, lock screen and debug review.
/// The car, hitch and trailer are one view, so the coupling never separates.
struct CheckupControlJourneyScene: View {
    let state: CheckupControlActivityAttributes.ContentState
    var darkBackground = true
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.isLuminanceReduced) private var luminanceReduced

    private var seed: Int {
        reduceMotion || luminanceReduced ? CheckupControlJourneyMotion.arrivalPhase : state.animationSeed
    }
    private var ink: Color { darkBackground ? .white : Color(red: 0.10, green: 0.25, blue: 0.20) }
    private var mint: Color { Color(red: 0.46, green: 0.91, blue: 0.71) }

    var body: some View {
        GeometryReader { geometry in
            let width = Double(geometry.size.width)
            let layout = CheckupControlJourneyMotion.layout(trackWidth: width)
            let scale = CGFloat(layout.scale)
            let roadY: CGFloat = 86
            let parked = CheckupControlJourneyMotion.isParked(for: seed)
            let rotation = CheckupControlJourneyMotion.wheelRotation(for: seed, trackWidth: width)

            ZStack(alignment: .topLeading) {
                RoundedRectangle(cornerRadius: 7)
                    .fill(ink.opacity(darkBackground ? 0.09 : 0.06))
                    .frame(height: 16)
                    .offset(y: roadY - 1)
                Rectangle().fill(ink.opacity(0.45)).frame(height: 1).offset(y: roadY)
                Path { path in
                    for x in stride(from: CGFloat(14), to: geometry.size.width, by: 34) {
                        path.move(to: CGPoint(x: x, y: roadY + 9))
                        path.addLine(to: CGPoint(x: x + 15, y: roadY + 9))
                    }
                }
                .stroke(ink.opacity(0.34), style: StrokeStyle(lineWidth: 1.4, lineCap: .round))

                ControlTechniqueBuilding(ink: ink, mint: mint, arrived: parked)
                    .frame(width: 72, height: 76)
                    .scaleEffect(scale, anchor: .topLeading)
                    .offset(x: 8, y: roadY - 76 * scale)

                HStack(alignment: .bottom, spacing: 0) {
                    ControlJourneyCar(mint: mint, rotation: rotation)
                        .frame(width: 64, height: 50)
                    Rectangle()
                        .fill(ink.opacity(0.85))
                        .frame(width: 12, height: 3)
                        .padding(.bottom, 16)
                        .frame(width: 12, height: 50, alignment: .bottom)
                    ControlJourneyTrailer(state: state, mint: mint, rotation: rotation)
                        .frame(width: 132, height: 50)
                }
                .frame(width: 208, height: 50, alignment: .bottomLeading)
                .scaleEffect(scale, anchor: .topLeading)
                .offset(
                    x: CGFloat(CheckupControlJourneyMotion.carOffset(for: seed, trackWidth: width)),
                    y: roadY - 50 * scale
                )
                .animation(
                    reduceMotion || luminanceReduced ? nil :
                        (parked ? .easeOut(duration: CheckupControlJourneyMotion.animationDuration)
                         : .linear(duration: CheckupControlJourneyMotion.animationDuration)),
                    value: CheckupControlJourneyMotion.phase(for: seed)
                )
            }
            .frame(width: geometry.size.width, height: 102, alignment: .topLeading)
            .clipped()
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(state.journeyMessage + (CheckupControlJourneyMotion.isParked(for: seed)
            ? ". La voiture et sa remorque sont arrêtées devant le centre de contrôle technique."
            : ". La voiture roule vers le centre de contrôle technique avec sa remorque."))
    }
}

private struct ControlJourneyCar: View {
    let mint: Color
    let rotation: Double

    var body: some View {
        ZStack(alignment: .topLeading) {
            ControlJourneyCarBody().fill(mint)
            ControlJourneyCarBody().stroke(Color.white.opacity(0.45), lineWidth: 0.8)
            Path { p in
                p.move(to: CGPoint(x: 19, y: 23))
                p.addLine(to: CGPoint(x: 27, y: 12))
                p.addLine(to: CGPoint(x: 37, y: 12))
                p.addLine(to: CGPoint(x: 37, y: 23))
                p.closeSubpath()
                p.move(to: CGPoint(x: 40, y: 12))
                p.addLine(to: CGPoint(x: 47, y: 14))
                p.addLine(to: CGPoint(x: 54, y: 23))
                p.addLine(to: CGPoint(x: 40, y: 23))
                p.closeSubpath()
            }
            .fill(Color(red: 0.07, green: 0.22, blue: 0.20))
            RoundedRectangle(cornerRadius: 1.5).fill(Color(red: 1, green: 0.94, blue: 0.66))
                .frame(width: 5, height: 5).offset(x: 2, y: 29)
            RoundedRectangle(cornerRadius: 1).fill(.red.opacity(0.85))
                .frame(width: 3, height: 5).offset(x: 60, y: 29)
            Capsule().fill(Color.black.opacity(0.3)).frame(width: 5, height: 1.5).offset(x: 42, y: 27)
            ControlJourneyWheel(rotation: rotation).frame(width: 13, height: 13).offset(x: 6, y: 37)
            ControlJourneyWheel(rotation: rotation).frame(width: 13, height: 13).offset(x: 47, y: 37)
        }
    }
}

private struct ControlJourneyCarBody: Shape {
    func path(in rect: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: 1, y: 38))
        p.addQuadCurve(to: CGPoint(x: 0, y: 30), control: CGPoint(x: -1, y: 34))
        p.addQuadCurve(to: CGPoint(x: 7, y: 25), control: CGPoint(x: 1, y: 25))
        p.addLine(to: CGPoint(x: 15, y: 24))
        p.addLine(to: CGPoint(x: 24, y: 11))
        p.addQuadCurve(to: CGPoint(x: 30, y: 9), control: CGPoint(x: 26, y: 9))
        p.addLine(to: CGPoint(x: 45, y: 10))
        p.addQuadCurve(to: CGPoint(x: 50, y: 13), control: CGPoint(x: 48, y: 10))
        p.addLine(to: CGPoint(x: 58, y: 24))
        p.addQuadCurve(to: CGPoint(x: 64, y: 30), control: CGPoint(x: 64, y: 25))
        p.addLine(to: CGPoint(x: 64, y: 38))
        p.addQuadCurve(to: CGPoint(x: 59, y: 41), control: CGPoint(x: 64, y: 41))
        p.addLine(to: CGPoint(x: 5, y: 41))
        p.addQuadCurve(to: CGPoint(x: 1, y: 38), control: CGPoint(x: 1, y: 41))
        p.closeSubpath()
        return p.applying(CGAffineTransform(scaleX: rect.width / 64, y: rect.height / 50))
    }
}

private struct ControlJourneyTrailer: View {
    let state: CheckupControlActivityAttributes.ContentState
    let mint: Color
    let rotation: Double

    var body: some View {
        ZStack(alignment: .topLeading) {
            RoundedRectangle(cornerRadius: 5)
                .fill(Color(red: 0.94, green: 0.98, blue: 0.91))
                .overlay(RoundedRectangle(cornerRadius: 5).stroke(mint, lineWidth: 1.5))
                .frame(width: 130, height: 37).offset(x: 1, y: 3)
            VStack(spacing: 1) {
                Text(state.journeyHeading)
                Text(state.journeyDetail)
            }
            .font(.system(size: 13, weight: .bold, design: .rounded))
            .foregroundStyle(Color(red: 0.08, green: 0.25, blue: 0.19))
            .lineLimit(1)
            .frame(width: 130, height: 35)
            .offset(x: 1, y: 4)
            Rectangle().fill(mint).frame(width: 128, height: 3).offset(x: 2, y: 39)
            ControlJourneyWheel(rotation: rotation).frame(width: 13, height: 13).offset(x: 74, y: 37)
        }
        .frame(width: 132, height: 50, alignment: .topLeading)
    }
}

private struct ControlJourneyWheel: View {
    let rotation: Double

    var body: some View {
        ZStack {
            Circle().fill(Color(red: 0.06, green: 0.09, blue: 0.08))
            Circle().stroke(Color.white.opacity(0.6), lineWidth: 1)
            ZStack {
                Capsule().fill(.white.opacity(0.9)).frame(width: 1.3, height: 8)
                Capsule().fill(.white.opacity(0.9)).frame(width: 8, height: 1.3)
            }
            .rotationEffect(.degrees(rotation))
            Circle().fill(.white).frame(width: 2.5, height: 2.5)
        }
    }
}

private struct ControlTechniqueBuilding: View {
    let ink: Color
    let mint: Color
    let arrived: Bool

    var body: some View {
        ZStack(alignment: .topLeading) {
            RoundedRectangle(cornerRadius: 4)
                .fill(ink.opacity(0.16))
                .overlay(RoundedRectangle(cornerRadius: 4).stroke(ink.opacity(0.7), lineWidth: 1))
                .frame(width: 68, height: 69).offset(x: 2, y: 7)
            RoundedRectangle(cornerRadius: 2).fill(mint).frame(width: 72, height: 6).offset(y: 4)
            Text("CONTRÔLE\nTECHNIQUE")
                .font(.system(size: 8.5, weight: .heavy, design: .rounded))
                .multilineTextAlignment(.center)
                .foregroundStyle(ink)
                .frame(width: 68, height: 25).offset(x: 2, y: 12)
            RoundedRectangle(cornerRadius: 2)
                .fill(ink.opacity(0.24))
                .overlay(RoundedRectangle(cornerRadius: 2).stroke(ink.opacity(0.6), lineWidth: 0.8))
                .frame(width: 27, height: 35).offset(x: 9, y: 40)
            Path { p in
                for y in stride(from: CGFloat(45), through: 69, by: 6) {
                    p.move(to: CGPoint(x: 11, y: y))
                    p.addLine(to: CGPoint(x: 34, y: y))
                }
            }
            .stroke(ink.opacity(0.35), lineWidth: 0.8)
            RoundedRectangle(cornerRadius: 2).fill(mint.opacity(0.65))
                .frame(width: 19, height: 19).offset(x: 43, y: 42)
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(mint)
                .offset(x: 46, y: 61)
                .opacity(arrived ? 1 : 0)
                .animation(.easeIn(duration: 0.3), value: arrived)
        }
    }
}
