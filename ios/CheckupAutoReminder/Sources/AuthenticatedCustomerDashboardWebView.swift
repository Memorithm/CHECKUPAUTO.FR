import SwiftUI
import WebKit
#if canImport(UIKit)
import UIKit
#endif

/// Presents the actual /compte HTML/CSS/JS, so the vehicle cards, buttons,
/// sections and responsive layout always match the website byte-for-byte.
/// A private, short-lived cookie is installed before the first navigation.
struct AuthenticatedCustomerDashboardWebView: UIViewRepresentable {
    let cookie: HTTPCookie
    let onBooking: () -> Void
    let onSignOut: () -> Void
    let onClaim: (URL) -> Void
    let onSessionExpired: () -> Void
    let onNavigationBlocked: () -> Void
    let onReportDownload: (URL) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        config.defaultWebpagePreferences.allowsContentJavaScript = true
        config.allowsInlineMediaPlayback = false
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.isOpaque = false
        webView.backgroundColor = UIColor(
            red: 0.965, green: 0.970, blue: 0.945, alpha: 1
        )
        webView.scrollView.backgroundColor = webView.backgroundColor
        webView.scrollView.contentInsetAdjustmentBehavior = .automatic
        webView.accessibilityIdentifier = "native-account-identical-website"

        // Strictly await WebKit's own cookie-store callback; do not start a
        // request to /compte before the authenticated cookie is available.
        webView.configuration.websiteDataStore.httpCookieStore.setCookie(cookie) {
            var request = URLRequest(url: MobileAPI.endpoint("/compte"))
            request.cachePolicy = .reloadIgnoringLocalCacheData
            webView.load(request)
        }
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    static func dismantleUIView(_ uiView: WKWebView, coordinator: Coordinator) {
        uiView.stopLoading()
        uiView.navigationDelegate = nil
        uiView.uiDelegate = nil
        let store = uiView.configuration.websiteDataStore.httpCookieStore
        store.getAllCookies { cookies in
            cookies.forEach { store.delete($0) }
        }
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
        private let parent: AuthenticatedCustomerDashboardWebView
        private var reportFiles: [ObjectIdentifier: URL] = [:]

        init(parent: AuthenticatedCustomerDashboardWebView) {
            self.parent = parent
        }

        private func isFirstParty(_ url: URL) -> Bool {
            guard let root = MobileAPI.currentBaseURL.host?.lowercased() else { return false }
            return url.scheme?.lowercased() == "https" &&
                url.host?.lowercased() == root &&
                url.user == nil && url.password == nil &&
                url.port == MobileAPI.currentBaseURL.port
        }

        private func isBookingURL(_ url: URL) -> Bool {
            if url.scheme == "https", url.user == nil, url.password == nil,
               url.port == nil, url.host?.lowercased() == "rdv.checkupauto.fr" {
                return true
            }
            guard isFirstParty(url) else { return false }
            return url.path == "/go/booking" ||
                url.path == "/compte/reserver" ||
                (url.path == "/" && url.fragment == "reservation")
        }

        private func evaluateDestination(_ url: URL) -> WKNavigationActionPolicy {
            if url.scheme == "checkupauto", url.host == "auth" {
                // Native authentication callbacks never run inside WebKit.
                parent.onNavigationBlocked()
                return .cancel
            }
            if isFirstParty(url), url.path == "/app/claim" {
                parent.onClaim(url)
                return .cancel
            }
            if isFirstParty(url), url.path == "/compte/deconnexion" {
                parent.onSignOut()
                return .cancel
            }
            if isBookingURL(url) {
                parent.onBooking()
                return .cancel
            }
            if isFirstParty(url) {
                // Account, reports, customer POST actions, legal and support
                // pages all stay inside the isolated first-party WebKit view.
                return .allow
            }
            // No external browser, no OAuth inside WebKit, no arbitrary
            // redirect to a third party carrying the scoped session cookie.
            parent.onNavigationBlocked()
            return .cancel
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            guard let url = navigationAction.request.url else {
                decisionHandler(.cancel)
                return
            }
            decisionHandler(evaluateDestination(url))
        }

        func webView(
            _ webView: WKWebView,
            createWebViewWith configuration: WKWebViewConfiguration,
            for navigationAction: WKNavigationAction,
            windowFeatures: WKWindowFeatures
        ) -> WKWebView? {
            guard let url = navigationAction.request.url else { return nil }
            if evaluateDestination(url) == .allow {
                webView.load(navigationAction.request)
            }
            return nil
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationResponse: WKNavigationResponse,
            decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void
        ) {
            guard let http = navigationResponse.response as? HTTPURLResponse,
                  let url = http.url, isFirstParty(url) else {
                decisionHandler(.cancel)
                return
            }
            let attachment = http.value(forHTTPHeaderField: "Content-Disposition")?
                .lowercased().contains("attachment") == true
            if attachment, url.path.hasPrefix("/api/customer/reports/"),
               URLComponents(url: url, resolvingAgainstBaseURL: false)?
                .queryItems?.contains(where: { $0.name == "format" && $0.value == "md" }) == true {
                decisionHandler(.download)
            } else {
                decisionHandler(.allow)
            }
        }

        func webView(
            _ webView: WKWebView,
            navigationResponse: WKNavigationResponse,
            didBecome download: WKDownload
        ) {
            download.delegate = self
        }

        func webView(
            _ webView: WKWebView,
            navigationAction: WKNavigationAction,
            didBecome download: WKDownload
        ) {
            download.delegate = self
        }

        func download(
            _ download: WKDownload,
            decideDestinationUsing response: URLResponse,
            suggestedFilename: String,
            completionHandler: @escaping (URL?) -> Void
        ) {
            guard let source = response.url, isFirstParty(source),
                  source.path.hasPrefix("/api/customer/reports/"),
                  suggestedFilename.range(
                    of: #"^rapport-[0-9a-f-]{36}\.md$"#,
                    options: .regularExpression
                  ) != nil else {
                completionHandler(nil)
                parent.onNavigationBlocked()
                return
            }
            let folder = FileManager.default.temporaryDirectory
                .appendingPathComponent("checkupauto-report-" + UUID().uuidString, isDirectory: true)
            do {
                try FileManager.default.createDirectory(
                    at: folder, withIntermediateDirectories: false,
                    attributes: [.posixPermissions: 0o700]
                )
                let destination = folder.appendingPathComponent(suggestedFilename)
                reportFiles[ObjectIdentifier(download)] = destination
                completionHandler(destination)
            } catch {
                completionHandler(nil)
                parent.onNavigationBlocked()
            }
        }

        func downloadDidFinish(_ download: WKDownload) {
            guard let url = reportFiles.removeValue(forKey: ObjectIdentifier(download)) else {
                return
            }
            parent.onReportDownload(url)
        }

        func download(
            _ download: WKDownload,
            didFailWithError error: Error,
            resumeData: Data?
        ) {
            if let url = reportFiles.removeValue(forKey: ObjectIdentifier(download)) {
                try? FileManager.default.removeItem(at: url.deletingLastPathComponent())
            }
            parent.onNavigationBlocked()
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            guard let url = webView.url, isFirstParty(url),
                  url.path == "/compte" else { return }
            // /compte returns HTTP 200 for both authenticated dashboard and
            // login form. Fail visibly instead of silently showing a second login.
            webView.evaluateJavaScript(
                "Boolean(document.getElementById('vehicleList') && document.getElementById('vehicleEditor'))"
            ) { value, error in
                if error == nil, value as? Bool == false {
                    self.parent.onSessionExpired()
                }
            }
        }

        func webView(
            _ webView: WKWebView,
            didFail navigation: WKNavigation!,
            withError error: Error
        ) {
            parent.onSessionExpired()
        }

        func webView(
            _ webView: WKWebView,
            didFailProvisionalNavigation navigation: WKNavigation!,
            withError error: Error
        ) {
            // Cancelled navigation is expected for intercepted booking/GPS links.
            if (error as NSError).code != NSURLErrorCancelled {
                parent.onSessionExpired()
            }
        }

        // The website uses window.confirm for vehicle/report deletion. Without
        // a real WKUIDelegate the action silently fails on an iPhone.
        func webView(
            _ webView: WKWebView,
            runJavaScriptConfirmPanelWithMessage message: String,
            initiatedByFrame frame: WKFrameInfo,
            completionHandler: @escaping (Bool) -> Void
        ) {
            presentConfirmation(message, from: webView, completionHandler: completionHandler)
        }

        func webView(
            _ webView: WKWebView,
            runJavaScriptAlertPanelWithMessage message: String,
            initiatedByFrame frame: WKFrameInfo,
            completionHandler: @escaping () -> Void
        ) {
            guard let host = webView.window?.rootViewController else {
                completionHandler()
                return
            }
            let alert = UIAlertController(title: "Checkup Auto", message: message, preferredStyle: .alert)
            alert.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler() })
            topController(from: host).present(alert, animated: true)
        }

        private func presentConfirmation(
            _ message: String, from webView: WKWebView,
            completionHandler: @escaping (Bool) -> Void
        ) {
            guard let host = webView.window?.rootViewController else {
                completionHandler(false)
                return
            }
            let alert = UIAlertController(
                title: "Checkup Auto", message: message, preferredStyle: .alert
            )
            alert.addAction(UIAlertAction(title: "Annuler", style: .cancel) { _ in
                completionHandler(false)
            })
            alert.addAction(UIAlertAction(title: "Confirmer", style: .destructive) { _ in
                completionHandler(true)
            })
            topController(from: host).present(alert, animated: true)
        }

        private func topController(from root: UIViewController) -> UIViewController {
            var current = root
            while let presented = current.presentedViewController {
                current = presented
            }
            return current
        }
    }
}
