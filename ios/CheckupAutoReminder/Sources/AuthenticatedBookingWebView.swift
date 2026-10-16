import SwiftUI
import WebKit
#if canImport(UIKit)
import UIKit
#endif

/// Outcome reported by the in-site hosted checkout, observed from its own
/// status panels and surfaced natively.
enum BookingOutcome {
    case confirmed
    case cancelled
}

/// The signed-in booking journey — the passage page (vehicle + contact), the
/// in-site Mercure summary and the hosted-checkout status panels — rendered
/// inside the app with the same scoped, short-lived HttpOnly cookie as the
/// account dashboard. The customer never signs in a second time and never
/// leaves the app, except for the external Payline card page, which is handed
/// to the system payment sheet. Everything else stays strictly first-party.
struct AuthenticatedBookingWebView: UIViewRepresentable {
    let cookie: HTTPCookie
    let entryURL: URL
    let onPayment: (URL) -> Void
    let onResult: (BookingOutcome) -> Void
    let onModifySlot: () -> Void
    let onFinished: () -> Void
    let onSessionExpired: () -> Void
    let onBlocked: () -> Void

    func makeCoordinator() -> Coordinator { Coordinator(parent: self) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        config.defaultWebpagePreferences.allowsContentJavaScript = true
        config.allowsInlineMediaPlayback = false

        let observer = WKUserScript(
            source: Self.resultObserverScript,
            injectionTime: .atDocumentEnd,
            forMainFrameOnly: true
        )
        config.userContentController.addUserScript(observer)
        config.userContentController.add(context.coordinator, name: "bookingResult")

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.isOpaque = false
        webView.backgroundColor = UIColor(red: 0.965, green: 0.970, blue: 0.945, alpha: 1)
        webView.scrollView.backgroundColor = webView.backgroundColor
        webView.scrollView.contentInsetAdjustmentBehavior = .automatic
        webView.accessibilityIdentifier = "in-app-booking-journey"

        let destination = entryURL
        // Await WebKit's own cookie-store callback before the first request, so
        // the authenticated cookie is present and no login form can appear.
        webView.configuration.websiteDataStore.httpCookieStore.setCookie(cookie) {
            var request = URLRequest(url: destination)
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
        uiView.configuration.userContentController.removeScriptMessageHandler(forName: "bookingResult")
        coordinator.discardPaymentChild()
        let store = uiView.configuration.websiteDataStore.httpCookieStore
        store.getAllCookies { cookies in cookies.forEach { store.delete($0) } }
    }

    // Reports the hosted-checkout result the moment its panel becomes visible,
    // so the native layer can dismiss the payment sheet and show the outcome.
    private static let resultObserverScript = """
    (function(){
      function visible(el){ return !!el && el.hidden === false; }
      function report(){
        if (visible(document.getElementById('bjHostedDone'))) {
          try { window.webkit.messageHandlers.bookingResult.postMessage('confirmed'); } catch (e) {}
          return;
        }
        if (visible(document.getElementById('bjHostedCancelled'))) {
          try { window.webkit.messageHandlers.bookingResult.postMessage('cancelled'); } catch (e) {}
        }
      }
      try {
        var observer = new MutationObserver(report);
        observer.observe(document.documentElement, {
          subtree: true, attributes: true, attributeFilter: ['hidden'], childList: true
        });
      } catch (e) {}
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', report);
      } else {
        report();
      }
    })();
    """

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
        private let parent: AuthenticatedBookingWebView
        private var paymentChild: WKWebView?

        init(parent: AuthenticatedBookingWebView) {
            self.parent = parent
        }

        func discardPaymentChild() {
            paymentChild?.stopLoading()
            paymentChild?.navigationDelegate = nil
            paymentChild?.uiDelegate = nil
            paymentChild = nil
        }

        private func isFirstParty(_ url: URL) -> Bool {
            guard let root = MobileAPI.currentBaseURL.host?.lowercased() else { return false }
            return url.scheme?.lowercased() == "https"
                && url.host?.lowercased() == root
                && url.user == nil && url.password == nil
                && url.port == MobileAPI.currentBaseURL.port
        }

        private func classify(_ url: URL) -> WKNavigationActionPolicy {
            // The only navigation allowed to leave the app is the card payment.
            if MobileAPI.isHostedPaymentURL(url) {
                parent.onPayment(url)
                return .cancel
            }
            if url.scheme?.lowercased() == "checkupauto" {
                parent.onBlocked()
                return .cancel
            }
            guard isFirstParty(url) else {
                parent.onBlocked()
                return .cancel
            }
            // Back to the home planner anchor: return to the native planner.
            if url.path == "/" || url.path.isEmpty {
                parent.onModifySlot()
                return .cancel
            }
            if url.path == "/compte" {
                // A bounce to /compte carrying returnTo is the website login
                // redirect: the scoped cookie expired. Never show that form.
                if let comps = URLComponents(url: url, resolvingAgainstBaseURL: false),
                   comps.queryItems?.contains(where: { $0.name == "returnTo" }) == true {
                    parent.onSessionExpired()
                } else {
                    // The confirmed panel links to the dashboard: journey done.
                    parent.onFinished()
                }
                return .cancel
            }
            // passage (/compte/reserver), in-site summary (/go/booking),
            // confirmation (/compte/reservation), customer POST actions, assets
            // and legal pages all stay inside the signed-in booking view.
            return .allow
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
            if webView === paymentChild {
                // The checkout opens a blank tab then points it at Payline.
                if url.scheme?.lowercased() == "about" {
                    decisionHandler(.allow)
                    return
                }
                if MobileAPI.isHostedPaymentURL(url) {
                    parent.onPayment(url)
                }
                decisionHandler(.cancel)
                discardPaymentChild()
                return
            }
            decisionHandler(classify(url))
        }

        func webView(
            _ webView: WKWebView,
            createWebViewWith configuration: WKWebViewConfiguration,
            for navigationAction: WKNavigationAction,
            windowFeatures: WKWindowFeatures
        ) -> WKWebView? {
            if let url = navigationAction.request.url, MobileAPI.isHostedPaymentURL(url) {
                // Fallback path: the checkout link opened directly on Payline.
                parent.onPayment(url)
                return nil
            }
            // Capture the blank payment tab so its single navigation to Payline
            // can be intercepted and sent to the system payment sheet.
            let child = WKWebView(frame: .zero, configuration: configuration)
            child.navigationDelegate = self
            child.uiDelegate = self
            discardPaymentChild()
            paymentChild = child
            return child
        }

        func userContentController(
            _ userContentController: WKUserContentController,
            didReceive message: WKScriptMessage
        ) {
            guard message.name == "bookingResult", let body = message.body as? String else { return }
            switch body {
            case "confirmed": parent.onResult(.confirmed)
            case "cancelled": parent.onResult(.cancelled)
            default: break
            }
        }

        func webView(
            _ webView: WKWebView,
            didFail navigation: WKNavigation!,
            withError error: Error
        ) {
            if webView === paymentChild {
                discardPaymentChild()
                return
            }
            if (error as NSError).code != NSURLErrorCancelled {
                parent.onSessionExpired()
            }
        }

        func webView(
            _ webView: WKWebView,
            didFailProvisionalNavigation navigation: WKNavigation!,
            withError error: Error
        ) {
            if webView === paymentChild {
                discardPaymentChild()
                return
            }
            // Cancelled navigation is expected for intercepted payment/home links.
            if (error as NSError).code != NSURLErrorCancelled {
                parent.onSessionExpired()
            }
        }
    }
}
