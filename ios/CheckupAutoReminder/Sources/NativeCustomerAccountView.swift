import SwiftUI

/// Authenticated customer account. Do not open /compte: the website's cookie
/// and the native Keychain bearer session are intentionally different.
struct NativeCustomerAccountView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    VStack(alignment: .leading, spacing: 12) {
                        Label("ESPACE CLIENT CHECKUP AUTO", systemImage: "checkmark.shield.fill")
                            .font(.caption.monospaced().weight(.semibold))
                            .foregroundStyle(CheckupTheme.accent)

                        Text(model.accountProfile?.displayName ?? "Votre compte")
                            .font(.system(size: 36, weight: .regular, design: .serif))
                            .foregroundStyle(CheckupTheme.ink)

                        if let account = model.accountProfile {
                            Label(account.email, systemImage: "envelope")
                                .font(.subheadline)
                                .foregroundStyle(CheckupTheme.muted)
                                .textSelection(.enabled)
                            if !account.phone.isEmpty {
                                Label(account.phone, systemImage: "phone")
                                    .font(.subheadline)
                                    .foregroundStyle(CheckupTheme.muted)
                            }
                            Text(account.kind == "professional" ? "COMPTE PROFESSIONNEL" : "COMPTE PARTICULIER")
                                .font(.caption2.monospaced().weight(.semibold))
                                .foregroundStyle(CheckupTheme.accent)
                        } else {
                            Text("Session native connectée. Informations en cours de chargement.")
                                .font(.subheadline)
                                .foregroundStyle(CheckupTheme.muted)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(24)
                    .background(CheckupTheme.card, in: RoundedRectangle(cornerRadius: 24))

                    VStack(alignment: .leading, spacing: 14) {
                        Label("Mes véhicules", systemImage: "car.side.fill")
                            .font(.headline)
                            .foregroundStyle(CheckupTheme.ink)
                        Text("\(model.accountVehicles.count) véhicule(s) associé(s) à ce compte")
                            .font(.caption)
                            .foregroundStyle(CheckupTheme.muted)

                        if model.accountVehicles.isEmpty {
                            Text("Aucun véhicule enregistré sur votre compte. Utilisez Ajouter un véhicule dans le tableau de bord.")
                                .font(.subheadline)
                                .foregroundStyle(CheckupTheme.muted)
                        }
                        ForEach(model.accountVehicles) { vehicle in
                            HStack {
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(vehicle.displayName.isEmpty ? "Mon véhicule" : vehicle.displayName)
                                        .font(.subheadline.weight(.semibold))
                                    Text(vehicle.registration).font(.caption.monospaced())
                                }
                                Spacer()
                                Image(systemName: "checkmark.shield")
                                    .foregroundStyle(CheckupTheme.accent)
                            }
                            .foregroundStyle(CheckupTheme.ink)
                            .padding(12)
                            .background(CheckupTheme.soft, in: RoundedRectangle(cornerRadius: 14))
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(22)
                    .background(CheckupTheme.card, in: RoundedRectangle(cornerRadius: 24))

                    Button {
                        Task { await model.refreshNativeAccount() }
                    } label: {
                        Label("Actualiser mon compte", systemImage: "arrow.clockwise")
                            .frame(maxWidth: .infinity, minHeight: 48)
                    }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("native-account-refresh")

                    Button(role: .destructive) {
                        model.signOutCustomer()
                        dismiss()
                    } label: {
                        Label("Se déconnecter", systemImage: "rectangle.portrait.and.arrow.right")
                            .frame(maxWidth: .infinity, minHeight: 48)
                    }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("native-account-signout")
                }
                .frame(maxWidth: 560)
                .padding(20)
                .frame(maxWidth: .infinity)
            }
            .background(CheckupTheme.paper.ignoresSafeArea())
            .navigationTitle("Mon compte")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Fermer") { dismiss() }
                }
            }
            .task { await model.refreshNativeAccount() }
        }
        .tint(CheckupTheme.accent)
        .accessibilityIdentifier("native-customer-account")
    }
}
