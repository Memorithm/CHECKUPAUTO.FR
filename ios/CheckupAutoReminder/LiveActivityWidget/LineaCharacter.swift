import SwiftUI

/// A vector interpretation of La Linea for the short car-and-reminder sequence.
/// The outline grows out of the ground line: it stays readable without film
/// frames, raster assets, or a continuously running widget animation.
///
/// `stride` ranges from -1...1 and `gesture` from 0...1. The caller supplies the
/// animation and frame (36×44 pt in the expanded view, 18×24 pt when compact).
struct LineaCharacter: View {
    var stride: Double
    var gesture: Double
    var facingRight: Bool
    var tint: Color

    var body: some View {
        GeometryReader { geometry in
            let scale = min(geometry.size.width / 36, geometry.size.height / 44)
            LineaCharacterOutline(
                stride: stride,
                gesture: gesture,
                facingRight: facingRight
            )
            .stroke(
                tint,
                style: StrokeStyle(
                    lineWidth: max(0.8, 1.55 * scale),
                    lineCap: .round,
                    lineJoin: .round
                )
            )
        }
        .aspectRatio(36.0 / 44.0, contentMode: .fit)
        .accessibilityHidden(true)
    }
}

/// One continuous body contour, joined to its baseline at both feet. Small
/// interior strokes provide an eye and an expressive brow at larger sizes.
private struct LineaCharacterOutline: Shape {
    var stride: Double
    var gesture: Double
    var facingRight: Bool

    var animatableData: AnimatablePair<Double, Double> {
        get { AnimatablePair(stride, gesture) }
        set {
            stride = newValue.first
            gesture = newValue.second
        }
    }

    func path(in rect: CGRect) -> Path {
        let step = CGFloat(min(1, max(-1, stride)))
        let talk = CGFloat(min(1, max(0, gesture)))
        let bounce = abs(step) * 0.65
        let scale = min(rect.width / 36, rect.height / 44)
        let origin = CGPoint(
            x: rect.midX - 18 * scale,
            y: rect.midY - 22 * scale
        )

        func point(_ x: CGFloat, _ y: CGFloat, lifted: Bool = true) -> CGPoint {
            CGPoint(
                x: origin.x + (facingRight ? x : 36 - x) * scale,
                y: origin.y + (y - (lifted ? bounce : 0)) * scale
            )
        }

        let handX: CGFloat = 28.2 + 2.0 * talk
        let handY: CGFloat = 28.4 - 13.0 * talk
        let elbowX: CGFloat = 23.8 + 0.5 * talk
        let elbowY: CGFloat = 23.2 - 3.2 * talk

        var path = Path()

        // Ground → rear foot → back → bald, rounded head.
        path.move(to: point(0.5, 41, lifted: false))
        path.addLine(to: point(5.8 + 2.2 * step, 41, lifted: false))
        path.addQuadCurve(
            to: point(10.0 + 1.8 * step, 39.6, lifted: false),
            control: point(9.2 + 2.0 * step, 41, lifted: false)
        )
        path.addLine(to: point(12.1 + 1.5 * step, 32.3))
        path.addCurve(
            to: point(11.8, 17.7),
            control1: point(9.3, 29.5),
            control2: point(8.7, 21.2)
        )
        path.addQuadCurve(to: point(11.5, 15.3), control: point(13.1, 16.3))
        path.addCurve(
            to: point(9.7, 6.9),
            control1: point(8.0, 13.3),
            control2: point(8.5, 9.1)
        )
        path.addCurve(
            to: point(18.8, 3.2),
            control1: point(10.8, 1.5),
            control2: point(16.3, 1.1)
        )
        path.addQuadCurve(to: point(19.8, 5.5), control: point(19.8, 4.1))

        // The oversized nose and little lower lip make the profile distinctive.
        path.addCurve(
            to: point(29.8, 6.4),
            control1: point(22.2, 4.8),
            control2: point(27.4, 4.6)
        )
        path.addCurve(
            to: point(23.0, 10.3),
            control1: point(34.0, 9.1),
            control2: point(28.1, 11.0)
        )
        path.addQuadCurve(to: point(22.9, 11.5), control: point(22.1, 10.9))
        path.addLine(to: point(24.1 + 0.7 * talk, 11.8))
        path.addQuadCurve(to: point(22.4, 14.7), control: point(25.0, 14.2))
        path.addQuadCurve(to: point(18.6, 17.1), control: point(18.8, 14.8))

        // Shoulder → pointing hand → chest. The hand rises toward the car.
        path.addCurve(
            to: point(elbowX, elbowY),
            control1: point(21.4, 18.1),
            control2: point(22.3, 21.4 - 2.0 * talk)
        )
        path.addLine(to: point(handX, handY))
        path.addLine(to: point(handX + 2.7, handY - 2.6))
        path.addQuadCurve(
            to: point(handX + 3.4, handY - 1.1),
            control: point(handX + 3.8, handY - 2.4)
        )
        path.addLine(to: point(handX + 1.8, handY + 0.2))
        path.addQuadCurve(
            to: point(handX + 2.6, handY + 2.1),
            control: point(handX + 4.1, handY + 1.1)
        )
        path.addQuadCurve(
            to: point(handX - 1.7, handY + 2.4),
            control: point(handX + 0.2, handY + 3.5)
        )
        path.addLine(to: point(elbowX - 2.1, elbowY + 2.5))
        path.addQuadCurve(to: point(18.7, 23.4), control: point(19.3, 25.1))
        path.addCurve(
            to: point(19.4, 32.1),
            control1: point(20.6, 26.7),
            control2: point(21.0, 30.2)
        )

        // Front leg → rounded foot → ground. Opposing feet create the stride.
        path.addLine(to: point(16.8 - 1.8 * step, 38.6, lifted: false))
        path.addQuadCurve(
            to: point(22.6 - 2.0 * step, 41, lifted: false),
            control: point(20.2 - 2.0 * step, 38.7, lifted: false)
        )
        path.addLine(to: point(35.5, 41, lifted: false))

        // Facial detail remains part of the same stroked vector drawing.
        path.move(to: point(20.8, 7.0))
        path.addQuadCurve(to: point(20.9, 8.3), control: point(21.4, 7.5))
        path.move(to: point(19.6, 6.0 - 0.4 * talk))
        path.addLine(to: point(21.4, 6.0 + 0.3 * talk))

        return path
    }
}
