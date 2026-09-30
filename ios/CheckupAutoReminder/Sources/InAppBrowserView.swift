#if canImport(SafariServices) && canImport(UIKit)
import SafariServices
import SwiftUI

struct InAppBrowserView: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> SFSafariViewController {
        let configuration = SFSafariViewController.Configuration()
        configuration.entersReaderIfAvailable = false
        configuration.barCollapsingEnabled = false
        let controller = SFSafariViewController(url: url, configuration: configuration)
        controller.dismissButtonStyle = .close
        controller.preferredControlTintColor = UIColor(
            red: 0.12,
            green: 0.33,
            blue: 0.26,
            alpha: 1
        )
        return controller
    }

    func updateUIViewController(_ uiViewController: SFSafariViewController, context: Context) {}
}
#endif
