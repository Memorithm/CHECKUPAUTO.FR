import MapKit
import SwiftUI
#if canImport(UIKit)
import UIKit
#endif

/// Exact destination used by the CheckupAuto website's GPS selector.
/// Keep all three GPS providers pointed at the same entrance.
enum CheckupAutoCentre {
    static let address = "1E rue Niépce, 78130 Les Mureaux"
    static let latitude = 48.980120
    static let longitude = 1.890251
    static let coordinates = "48.980120,1.890251"

    static let googleMapsURL = URL(
        string: "comgooglemaps://?daddr=48.980120,1.890251&directionsmode=driving"
    )!
    static let wazeURL = URL(
        string: "waze://?ll=48.980120,1.890251&navigate=yes"
    )!
    static let sharingURL = URL(
        string: "https://www.google.com/maps/dir/?api=1&destination=48.980120%2C1.890251&travelmode=driving"
    )!

    static func openAppleMaps() {
        let destination = MKMapItem(placemark: MKPlacemark(
            coordinate: CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
        ))
        destination.name = "Checkup Auto — Les Mureaux"
        destination.openInMaps(launchOptions: [
            MKLaunchOptionsDirectionsModeKey: MKLaunchOptionsDirectionsModeDriving
        ])
    }
}

/// Provider selection is native, explicit and unrelated to account tokens.
/// No tracking, location reading or automatic GPS launch.
struct CentreGPSChoiceModifier: ViewModifier {
    @Binding var isPresented: Bool
    @State private var showsShare = false

    func body(content: Content) -> some View {
        content
            .confirmationDialog(
                "Votre itinéraire vers Checkup Auto",
                isPresented: $isPresented,
                titleVisibility: .visible
            ) {
                Button("Plans d’Apple") { CheckupAutoCentre.openAppleMaps() }
                #if canImport(UIKit)
                if UIApplication.shared.canOpenURL(CheckupAutoCentre.googleMapsURL) {
                    Button("Google Maps") {
                        UIApplication.shared.open(CheckupAutoCentre.googleMapsURL)
                    }
                }
                if UIApplication.shared.canOpenURL(CheckupAutoCentre.wazeURL) {
                    Button("Waze") {
                        UIApplication.shared.open(CheckupAutoCentre.wazeURL)
                    }
                }
                #endif
                Button("Partager l’itinéraire avec une autre application…") {
                    showsShare = true
                }
                Button("Annuler", role: .cancel) {}
            } message: {
                Text("Checkup Auto · " + CheckupAutoCentre.address)
            }
            .sheet(isPresented: $showsShare) {
                CentreItineraryShareView()
            }
    }
}

extension View {
    func centreGPSChoice(isPresented: Binding<Bool>) -> some View {
        modifier(CentreGPSChoiceModifier(isPresented: isPresented))
    }
}

#if canImport(UIKit)
private struct CentreItineraryShareView: UIViewControllerRepresentable {
    func makeUIViewController(context: Context) -> UIActivityViewController {
        let controller = UIActivityViewController(
            activityItems: [
                "Checkup Auto · " + CheckupAutoCentre.address,
                CheckupAutoCentre.sharingURL
            ],
            applicationActivities: nil
        )
        controller.popoverPresentationController?.sourceView = controller.view
        return controller
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}
#else
private struct CentreItineraryShareView: View {
    var body: some View { EmptyView() }
}
#endif
