import AuthenticationServices
import SwiftUI

struct CustomerAuthenticationOptions: View {
    @EnvironmentObject private var model: AppModel
    @State private var emailMode: EmailAuthenticationMode?

    var body: some View {
        VStack(spacing: 10) {
            SignInWithAppleButton(.continue) { request in
                model.prepareAppleSignIn(request)
            } onCompletion: { result in
                model.completeAppleSignIn(result)
            }
            .signInWithAppleButtonStyle(.black)
            .frame(height: 50)
            .accessibilityIdentifier("premium-auth-apple")

            Button {
                model.signInWithGoogle()
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: "g.circle")
                        .font(.title3)
                    Text("Continuer avec Google")
                        .font(.subheadline.weight(.semibold))
                }
                .frame(maxWidth: .infinity, minHeight: 48)
                .foregroundStyle(CheckupTheme.ink)
                .background(.white, in: RoundedRectangle(cornerRadius: 12))
                .overlay(RoundedRectangle(cornerRadius: 12).stroke(CheckupTheme.line))
            }
            .accessibilityIdentifier("premium-auth-google")

            Text("Google utilise une fenêtre sécurisée iOS. La confirmation du domaine affichée par Apple est normale : après validation, vous revenez automatiquement dans Checkup Auto.")
                .font(.caption2)
                .foregroundStyle(CheckupTheme.muted)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("premium-auth-google-system-explanation")

            Button {
                emailMode = .signIn
            } label: {
                Label("Se connecter par e-mail", systemImage: "envelope")
                    .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity, minHeight: 48)
            }
            .buttonStyle(.borderedProminent)
            .tint(CheckupTheme.accent)
            .accessibilityIdentifier("premium-auth-email-login")

            Button("Créer un compte par e-mail") {
                emailMode = .register
            }
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(CheckupTheme.accent)
            .frame(minHeight: 38)
            .accessibilityIdentifier("premium-auth-email-register")
        }
        .sheet(item: $emailMode) { mode in
            EmailAccountView(mode: mode)
                .environmentObject(model)
        }
        .task { await model.prefetchAppleSignInNonce() }
    }
}
