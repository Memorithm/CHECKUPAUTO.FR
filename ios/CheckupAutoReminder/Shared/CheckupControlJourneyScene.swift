import SwiftUI
import UIKit

/// A fixed reminder shared by the expanded island, lock screen and native review.
struct CheckupControlJourneyScene: View {
    let state: CheckupControlActivityAttributes.ContentState
    var darkBackground = true

    var body: some View {
        HStack(alignment: .center, spacing: 6) {
            CheckupControlVehicleImage(presentation: .expanded)
            Text(state.reminderMessage)
                .font(.system(size: 22, weight: .bold))
                .fontWidth(.condensed)
                .foregroundStyle(CheckupControlReminderStyle.color(darkBackground: darkBackground))
                .lineLimit(1)
                .minimumScaleFactor(0.75)
                .allowsTightening(true)
                .layoutPriority(1)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(state.reminderMessage)
    }
}

/// Keep the car and its short reminder in one compact region: the camera
/// separates compactLeading and compactTrailing in the system presentation.
struct CheckupControlCompactReminder: View {
    static let compactLeadingWidth: CGFloat = 58

    let state: CheckupControlActivityAttributes.ContentState

    var body: some View {
        HStack(alignment: .center, spacing: 2) {
            CheckupControlVehicleImage(presentation: .compact)
            Text(state.moment == .acknowledged ? "Vu" : "CT")
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(CheckupControlReminderStyle.color(darkBackground: true))
                .multilineTextAlignment(.leading)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
                .frame(width: 30, alignment: .leading)
        }
        .frame(width: Self.compactLeadingWidth, height: 26)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(state.reminderMessage)
    }
}

enum CheckupControlReminderStyle {
    static func color(darkBackground: Bool) -> Color {
        darkBackground
            ? Color(red: 1.0, green: 0.76, blue: 0.20)
            : Color(red: 0.55, green: 0.25, blue: 0.02)
    }
}

/// The selected silver vehicle is bundled in both app and widget extension.
/// Bound thumbnail dimensions before SwiftUI receives the bitmap.
struct CheckupControlVehicleImage: View {
    enum Presentation: CaseIterable, Hashable {
        case expanded, compact, minimal

        var size: CGSize {
            switch self {
            case .expanded: return CGSize(width: 42, height: 34)
            case .compact: return CGSize(width: 26, height: 26)
            case .minimal: return CGSize(width: 32, height: 24)
            }
        }
    }

    let presentation: Presentation

    var body: some View {
        Group {
            if let image = Self.image(for: presentation) {
                Image(uiImage: image)
                    .renderingMode(.original)
                    .resizable()
                    .scaledToFit()
            }
        }
        .frame(width: presentation.size.width, height: presentation.size.height)
        .accessibilityLabel("Voiture argentée")
    }

    private static let images: [Presentation: UIImage] = {
        guard let path = Bundle.main.path(forResource: "checkupauto-silver-car", ofType: "png"),
              let source = UIImage(contentsOfFile: path) else { return [:] }
        let scale: CGFloat = 3
        return Dictionary(uniqueKeysWithValues: Presentation.allCases.compactMap { presentation in
            let pixels = CGSize(width: presentation.size.width * scale, height: presentation.size.height * scale)
            guard let thumbnail = source.preparingThumbnail(of: pixels), let bitmap = thumbnail.cgImage else { return nil }
            return (presentation, UIImage(cgImage: bitmap, scale: scale, orientation: .up))
        })
    }()

    static func image(for presentation: Presentation) -> UIImage? { images[presentation] }
}
