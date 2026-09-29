#if DEBUG
import ActivityKit
import SwiftUI

/// Diagnostic launch route for recording the real SwiftUI scene and system island.
/// It never loads a customer vehicle or creates a real appointment.
struct ControlJourneyVisualReview: View {
    @State private var seed = 0
    @State private var reviewError: String?
    private let endsAt = Date().addingTimeInterval(120)

    var body: some View {
        VStack(spacing: 24) {
            Text("Vérification du trajet Checkup Auto").font(.headline)
            VStack(spacing: 4) {
                Text("CHECKUP AUTO · DÉMO LOCALE").font(.caption.bold()).foregroundStyle(.mint)
                CheckupControlJourneyScene(state: .init(moment: .localTest, appointmentAt: endsAt, animationSeed: seed))
                    .frame(height: 102)
                Text("Aucun rendez-vous réel").font(.caption).foregroundStyle(.gray)
            }
            .padding(8)
            .background(.black, in: RoundedRectangle(cornerRadius: 24))
            .padding(.horizontal, 8)
            Text(CheckupControlJourneyMotion.isParked(for: seed) ? "Arrêt devant le centre" : "Trajet en cours")
            if let reviewError { Text(reviewError).font(.caption).foregroundStyle(.red) }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(red: 0.965, green: 0.970, blue: 0.945).ignoresSafeArea())
        .task {
            if #available(iOS 26.0, *) {
                do { _ = try await CheckupControlLiveActivityCoordinator.startLocalTest() }
                catch { reviewError = error.localizedDescription }
            }
            for phase in 1...CheckupControlJourneyMotion.arrivalPhase {
                do { try await Task.sleep(for: .seconds(2)) } catch { return }
                seed = phase
                if #available(iOS 26.0, *) {
                    await CheckupControlLiveActivityCoordinator.advanceLocalTestAnimation()
                }
            }
        }
    }
}
#endif
