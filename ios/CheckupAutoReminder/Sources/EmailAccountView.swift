import SwiftUI

private struct AccountHelpPage: Identifiable {
    let id = UUID()
    let url: URL
}

enum EmailAuthenticationMode: String, Identifiable {
    case signIn
    case register

    var id: String { rawValue }
}

struct EmailAccountView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss

    @State private var registering: Bool
    @State private var email = ""
    @State private var password = ""
    @State private var confirmation = ""
    @State private var submitting = false
    @State private var registrationSubmitted = false
    @State private var message: String?
    @State private var helpPage: AccountHelpPage?

    init(mode: EmailAuthenticationMode) {
        _registering = State(initialValue: mode == .register)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(registering ? "Créez votre compte." : "Bienvenue à nouveau.")
                            .font(.system(size: 34, weight: .regular, design: .serif))
                            .foregroundStyle(CheckupTheme.ink)
                        Text(registering
                             ? "Votre compte Checkup Auto est protégé par une confirmation de votre adresse e-mail."
                             : "Connectez-vous pour accéder à votre espace Checkup Auto.")
                            .font(.subheadline)
                            .foregroundStyle(CheckupTheme.muted)
                    }

                    VStack(alignment: .leading, spacing: 14) {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Adresse e-mail").font(.caption.weight(.semibold))
                            TextField("vous@exemple.fr", text: $email)
                                .keyboardType(.emailAddress)
                                .textContentType(.username)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .textFieldStyle(.roundedBorder)
                                .submitLabel(.next)
                                .accessibilityIdentifier("email-account-address")
                        }

                        VStack(alignment: .leading, spacing: 6) {
                            Text("Mot de passe").font(.caption.weight(.semibold))
                            SecureField("Mot de passe", text: $password)
                                .textContentType(registering ? .newPassword : .password)
                                .textFieldStyle(.roundedBorder)
                                .accessibilityIdentifier("email-account-password")
                        }

                        if registering {
                            VStack(alignment: .leading, spacing: 6) {
                                Text("Confirmer le mot de passe").font(.caption.weight(.semibold))
                                SecureField("Confirmation", text: $confirmation)
                                    .textContentType(.newPassword)
                                    .textFieldStyle(.roundedBorder)
                            }
                            Text("Au moins 12 caractères. Un lien de confirmation sera envoyé par e-mail.")
                                .font(.caption)
                                .foregroundStyle(CheckupTheme.muted)
                            Text("En créant un compte, vous acceptez le traitement des données nécessaires à sa gestion.")
                                .font(.caption)
                                .foregroundStyle(CheckupTheme.muted)
                            Button("Consulter la politique de confidentialité") {
                                helpPage = AccountHelpPage(url: MobileAPI.endpoint("/confidentialite"))
                            }
                            .font(.caption.weight(.medium))
                        }
                    }
                    .padding(20)
                    .background(.white, in: RoundedRectangle(cornerRadius: 22))

                    if let message {
                        Label(message, systemImage: registrationSubmitted
                              ? "envelope.badge.shield.half.filled" : "exclamationmark.circle")
                            .font(.subheadline)
                            .foregroundStyle(registrationSubmitted ? CheckupTheme.ink : .red)
                            .accessibilityAddTraits(.updatesFrequently)
                    }

                    if registrationSubmitted {
                        Button("J’ai confirmé mon e-mail · Se connecter") {
                            registering = false
                            registrationSubmitted = false
                            password = ""
                            confirmation = ""
                            message = nil
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(CheckupTheme.accent)
                        .frame(maxWidth: .infinity)
                    } else {
                        Button(action: submit) {
                            HStack {
                                Spacer()
                                if submitting { ProgressView().tint(.white) }
                                Text(registering ? "Créer mon compte" : "Se connecter")
                                    .font(.headline)
                                Spacer()
                            }
                            .frame(minHeight: 40)
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(CheckupTheme.accent)
                        .disabled(!canSubmit || submitting)
                        .accessibilityIdentifier("email-account-submit")
                    }

                    Button(registering ? "J’ai déjà un compte" : "Créer un compte par e-mail") {
                        registering.toggle()
                        password = ""
                        confirmation = ""
                        registrationSubmitted = false
                        message = nil
                    }
                    .font(.subheadline.weight(.semibold))
                    .frame(maxWidth: .infinity)

                    if !registering {
                        Button("Mot de passe oublié ?") {
                            helpPage = AccountHelpPage(url: MobileAPI.endpoint("/compte"))
                        }
                        .font(.footnote)
                        .frame(maxWidth: .infinity)
                    }
                }
                .padding(24)
                .frame(maxWidth: 550)
                .frame(maxWidth: .infinity)
            }
            .background(CheckupTheme.paper.ignoresSafeArea())
            .navigationTitle(registering ? "Créer un compte" : "Connexion par e-mail")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Fermer") { dismiss() }
                }
            }
        }
        .tint(CheckupTheme.accent)
        .sheet(item: $helpPage) { destination in
            InAppBrowserView(url: destination.url)
                .ignoresSafeArea()
        }
    }

    private var canSubmit: Bool {
        let validEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
        return validEmail.contains("@") && !password.isEmpty
            && (!registering || (password.count >= 12 && password == confirmation))
    }

    @MainActor
    private func submit() {
        let address = email.trimmingCharacters(in: .whitespacesAndNewlines)
        submitting = true
        message = nil
        Task {
            defer { submitting = false }
            do {
                if registering {
                    try await EmailCustomerAuthClient.register(
                        email: address, password: password, confirmation: confirmation
                    )
                    password = ""
                    confirmation = ""
                    registrationSubmitted = true
                    message = "Un message de vérification vous a été envoyé. Ouvrez le lien reçu, puis connectez-vous."
                } else {
                    try await model.signInWithEmail(address, password: password)
                    password = ""
                    dismiss()
                }
            } catch {
                message = (error as? LocalizedError)?.errorDescription
                    ?? "Opération indisponible. Veuillez réessayer."
            }
        }
    }
}
