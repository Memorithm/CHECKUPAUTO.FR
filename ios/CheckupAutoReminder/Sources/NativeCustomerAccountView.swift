import SwiftUI
import WebKit
#if canImport(UIKit)
import UIKit
#endif

/// The customer's actual site dashboard, not a lower-fidelity SwiftUI clone.
/// Authentication is native once; the website receives a distinct short-lived
/// HttpOnly cookie without presenting another login form to the customer.
struct NativeCustomerAccountView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase

    @State private var browserCookie: HTTPCookie?
    @State private var browserIdentity = UUID()
    @State private var websiteReady = false
    @State private var loading = false
    @State private var connectError: String?
    @State private var cookieValidUntil: Date = .distantPast
    @State private var showGPSPicker = false
    @State private var showBlockedExternalNavigation = false
    @State private var reportToShare: CustomerReportFile?
    @State private var showingBooking = false

    var body: some View {
        NavigationStack {
            Group {
                if let browserCookie, connectError == nil {
                    ZStack {
                    AuthenticatedCustomerDashboardWebView(
                        cookie: browserCookie,
                        onBooking: openBooking,
                        onSignOut: {
                            model.signOutCustomer()
                            dismiss()
                        },
                        onClaim: { url in
                            model.consumeMobileClaim(url: url)
                            dismiss()
                        },
                        onSessionExpired: {
                            NativeDashboardBridge.invalidate()
                            cookieValidUntil = .distantPast
                            websiteReady = false
                            connectError = "La page du compte n’est plus accessible. Actualisez votre session sans vous reconnecter."
                        },
                        onDashboardReady: {
                            websiteReady = true
                        },
                        onNavigationBlocked: {
                            showBlockedExternalNavigation = true
                        },
                        onReportDownload: { url in
                            reportToShare = CustomerReportFile(url: url)
                        }
                    )
                    .id(browserIdentity)
                    .opacity(websiteReady ? 1 : 0)
                    .accessibilityHidden(!websiteReady)
                    .accessibilityIdentifier("native-customer-website-dashboard")
                    if !websiteReady {
                        VStack(spacing: 14) {
                            ProgressView()
                            Text("Chargement de votre espace client…")
                                .font(.subheadline)
                                .foregroundStyle(CheckupTheme.muted)
                        }
                        .accessibilityIdentifier("native-account-website-loading")
                    }
                    }
                } else {
                    VStack(spacing: 20) {
                        Spacer()
                        if loading {
                            ProgressView()
                                .controlSize(.large)
                            Text("Ouverture de votre espace client…")
                                .font(.subheadline)
                                .foregroundStyle(CheckupTheme.muted)
                        } else {
                            Image(systemName: "person.crop.rectangle.stack")
                                .font(.system(size: 46, weight: .light))
                                .foregroundStyle(CheckupTheme.accent)
                            Text("Votre espace client")
                                .font(.system(size: 34, weight: .regular, design: .serif))
                                .foregroundStyle(CheckupTheme.ink)
                            Text(connectError ?? "Préparation de votre session sécurisée…")
                                .multilineTextAlignment(.center)
                                .font(.subheadline)
                                .foregroundStyle(CheckupTheme.muted)
                            Button {
                                Task { await openAccountWebsite() }
                            } label: {
                                Label("Rouvrir mon compte", systemImage: "arrow.clockwise")
                                    .frame(maxWidth: .infinity, minHeight: 48)
                            }
                            .buttonStyle(.borderedProminent)
                            .tint(CheckupTheme.accent)
                            .accessibilityIdentifier("native-account-cookie-retry")
                        }
                        Spacer()
                    }
                    .frame(maxWidth: 430)
                    .padding(24)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(CheckupTheme.paper)
                }
            }
            .background(CheckupTheme.paper.ignoresSafeArea())
            .navigationTitle("Mon espace client")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        showGPSPicker = true
                    } label: {
                        Label("Itinéraire", systemImage: "location.north.line")
                    }
                    .accessibilityIdentifier("native-account-gps")
                }
                ToolbarItemGroup(placement: .topBarTrailing) {
                    Button {
                        Task { await openAccountWebsite() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .disabled(loading)
                    .accessibilityLabel("Actualiser mon espace client")
                    .accessibilityIdentifier("native-account-refresh")
                    Button("Fermer") { dismiss() }
                }
            }
            .alert("Lien non ouvert", isPresented: $showBlockedExternalNavigation) {
                Button("Compris", role: .cancel) {}
            } message: {
                Text("Votre compte reste dans Checkup Auto. Seuls le planning Mercure et l’application GPS que vous choisissez s’ouvrent séparément.")
            }
            .centreGPSChoice(isPresented: $showGPSPicker)
            .sheet(item: $reportToShare) { item in
                CustomerReportShareSheet(url: item.url)
                    .onDisappear {
                        try? FileManager.default.removeItem(at: item.url.deletingLastPathComponent())
                    }
            }
            .fullScreenCover(isPresented: $showingBooking) {
                BookingJourneyView(onWebFallback: openBookingInWeb)
                    .environmentObject(model)
            }
            .task { await openAccountWebsite() }
            .onDisappear {
                // Website edits and deletions must also update the native home list.
                Task { await model.refreshNativeAccount() }
            }
            .onChange(of: scenePhase) { _, phase in
                guard phase == .active, Date() >= cookieValidUntil.addingTimeInterval(-90) else { return }
                Task { await openAccountWebsite() }
            }
        }
        .tint(CheckupTheme.accent)
        .accessibilityIdentifier("native-customer-account")
    }

    @MainActor
    private func openAccountWebsite() async {
        guard !loading, model.customerSignedIn else { return }
        loading = true
        websiteReady = false
        connectError = nil
        defer { loading = false }
        do {
            let fresh = try await NativeDashboardBridge.createBrowserCookie()
            browserCookie = fresh
            browserIdentity = UUID()
            cookieValidUntil = fresh.expiresDate ?? Date().addingTimeInterval(3300)
        } catch NativeDashboardBridgeError.expiredNativeSession {
            model.signOutCustomer()
            dismiss()
        } catch {
            browserCookie = nil
            connectError = "La connexion au site est momentanément indisponible. Votre compte iOS reste connecté ; réessayez."
        }
    }

    private func openBooking() {
        // Booking happens inside the app, reusing the current session, so the
        // customer is never asked to sign in again.
        showingBooking = true
    }

    private func openBookingInWeb() {
        // Degraded fallback only: used when the in-app journey cannot prepare
        // the scoped session. The environment-aware web journey never leaves
        // for the legacy rdv.checkupauto.fr site.
        #if canImport(UIKit)
        UIApplication.shared.open(MobileAPI.bookingJourneyURL())
        #endif
    }
}

private struct CustomerReportFile: Identifiable {
    let id = UUID()
    let url: URL
}

#if canImport(UIKit)
private struct CustomerReportShareSheet: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> UIActivityViewController {
        let controller = UIActivityViewController(
            activityItems: [url], applicationActivities: nil
        )
        controller.popoverPresentationController?.sourceView = controller.view
        return controller
    }

    func updateUIViewController(
        _ uiViewController: UIActivityViewController,
        context: Context
    ) {}
}
#else
private struct CustomerReportShareSheet: View {
    let url: URL
    var body: some View { EmptyView() }
}
#endif
