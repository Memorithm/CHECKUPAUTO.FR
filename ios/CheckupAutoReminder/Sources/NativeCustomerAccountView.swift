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
    @State private var loading = false
    @State private var connectError: String?
    @State private var cookieValidUntil: Date = .distantPast
    @State private var showGPSPicker = false
    @State private var showBlockedExternalNavigation = false

    var body: some View {
        NavigationStack {
            Group {
                if let browserCookie, connectError == nil {
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
                            connectError = "La page du compte n’est plus accessible. Actualisez votre session sans vous reconnecter."
                        },
                        onNavigationBlocked: {
                            showBlockedExternalNavigation = true
                        }
                    )
                    .id(browserIdentity)
                    .accessibilityIdentifier("native-customer-website-dashboard")
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
            .task { await openAccountWebsite() }
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
        #if canImport(UIKit)
        UIApplication.shared.open(MobileAPI.directMercureBookingURL)
        #endif
    }
}
