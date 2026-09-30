import SwiftUI
import UIKit

/// A fixed reminder shared by the expanded island, lock screen and native review.
struct CheckupControlJourneyScene: View {
    let state: CheckupControlActivityAttributes.ContentState
    var darkBackground = true

    var body: some View {
        HStack(spacing: 12) {
            CheckupControlVehicleImage(presentation: .expanded)
            Text(state.reminderMessage)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(darkBackground ? Color.white : Color(red: 0.10, green: 0.25, blue: 0.20))
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(state.reminderMessage)
    }
}

/// The selected silver vehicle is bundled in both app and widget extension.
/// Bound thumbnail dimensions before SwiftUI receives the bitmap.
struct CheckupControlVehicleImage: View {
    enum Presentation: CaseIterable, Hashable {
        case expanded, compact, minimal

        var size: CGSize {
            switch self {
            case .expanded: return CGSize(width: 120, height: 64)
            case .compact: return CGSize(width: 52, height: 26)
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
