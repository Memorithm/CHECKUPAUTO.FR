import SwiftUI

/// First screen for customers without a native session.
/// Uses the same lavis vehicle illustration as the public website.
struct PremiumWelcomeView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack(spacing: 9) {
                    Image(systemName: "checkmark.seal.fill")
                        .font(.title2)
                        .foregroundStyle(CheckupTheme.accent)
                    Text("CHECKUP AUTO")
                        .font(.caption.weight(.bold))
                        .tracking(2.6)
                        .foregroundStyle(CheckupTheme.ink)
                    Spacer()
                    Text("ESPACE CLIENT")
                        .font(.caption2.monospaced().weight(.semibold))
                        .tracking(1)
                        .foregroundStyle(CheckupTheme.muted)
                }

                VStack(alignment: .leading, spacing: 8) {
                    Text("Votre voiture mérite\nplus d’attention.")
                        .font(.system(size: 43, weight: .regular, design: .serif))
                        .tracking(-1.5)
                        .foregroundStyle(CheckupTheme.ink)
                        .minimumScaleFactor(0.8)
                        .fixedSize(horizontal: false, vertical: true)

                    Text("Le contrôle technique, les échéances et vos rendez-vous dans un seul espace.")
                        .font(.subheadline)
                        .foregroundStyle(CheckupTheme.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }

                ZStack {
                    RoundedRectangle(cornerRadius: 32, style: .continuous)
                        .fill(
                            LinearGradient(
                                colors: [.white, CheckupTheme.soft, .white],
                                startPoint: .topLeading, endPoint: .bottomTrailing
                            )
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 32, style: .continuous)
                                .stroke(CheckupTheme.line)
                        )

                    AsyncImage(url: MobileAPI.premiumVehicleArtworkURL()) { phase in
                        switch phase {
                        case .success(let image):
                            image
                                .resizable()
                                .scaledToFit()
                                .padding(8)
                        case .empty:
                            ProgressView().tint(CheckupTheme.accent)
                        case .failure:
                            Image(systemName: "car.side.fill")
                                .resizable()
                                .scaledToFit()
                                .foregroundStyle(CheckupTheme.accent)
                                .padding(48)
                        @unknown default:
                            EmptyView()
                        }
                    }
                    .accessibilityLabel("Voiture Checkup Auto illustrée à l’encre et au lavis")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
                .frame(height: 290)
                .accessibilityIdentifier("premium-welcome-vehicle")

                Label("Réservation simplifiée · Rappels personnalisés", systemImage: "checkmark.circle.fill")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(CheckupTheme.accent)
            }
            .padding(.horizontal, 24)
            .padding(.top, 22)
            .padding(.bottom, 24)
            .frame(maxWidth: 570)
            .frame(maxWidth: .infinity)
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            VStack(spacing: 12) {
                Text("ACCÉDEZ À VOTRE ESPACE")
                    .font(.caption2.monospaced().weight(.semibold))
                    .tracking(1.5)
                    .foregroundStyle(CheckupTheme.muted)

                CustomerAuthenticationOptions()

                if let message = model.errorMessage {
                    Text(message)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .multilineTextAlignment(.center)
                        .accessibilityAddTraits(.updatesFrequently)
                }

                Text("Connexion sécurisée. Vos données restent associées à votre compte.")
                    .font(.caption2)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(CheckupTheme.muted)
            }
            .padding(.horizontal, 24)
            .padding(.top, 18)
            .padding(.bottom, 8)
            .frame(maxWidth: 570)
            .frame(maxWidth: .infinity)
            .background(CheckupTheme.paper)
            .overlay(alignment: .top) {
                Rectangle()
                    .fill(CheckupTheme.line)
                    .frame(height: 1)
            }
        }
        .background(CheckupTheme.paper.ignoresSafeArea())
        .accessibilityIdentifier("premium-welcome-screen")
    }
}
