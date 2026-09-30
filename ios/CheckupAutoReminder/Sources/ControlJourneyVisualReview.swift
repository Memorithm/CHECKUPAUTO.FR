#if DEBUG
import ActivityKit
import SwiftUI

/// Diagnostic launch route for recording the real SwiftUI scene and system island.
/// It never loads a customer vehicle or creates a real appointment.
struct ControlJourneyVisualReview: View {
    @State private var reviewError: String?
    @State private var activityStatus = ""
    private let endsAt = Date().addingTimeInterval(120)

    var body: some View {
        VStack(spacing: 24) {
            Text("Vérification du rappel Checkup Auto").font(.headline)
            VStack(spacing: 4) {
                Text("CHECKUP AUTO · DÉMO LOCALE").font(.caption.bold()).foregroundStyle(.mint)
                CheckupControlJourneyScene(state: .init(moment: .localTest, appointmentAt: endsAt, animationSeed: 0))
                    .frame(height: 116)
                Text("Aucun rendez-vous réel").font(.caption).foregroundStyle(.gray)
            }
            .padding(8)
            .background(.black, in: RoundedRectangle(cornerRadius: 24))
            .padding(.horizontal, 8)

            VStack(alignment: .leading, spacing: 8) {
                Text("Présentation compacte").font(.caption).foregroundStyle(.gray)
                CheckupControlCompactReminder(state: .init(moment: .localTest, appointmentAt: endsAt, animationSeed: 0))
                    .padding(8)
                    .background(.black, in: Capsule())
            }

            Text(activityStatus).font(.caption).foregroundStyle(.gray)
            if let reviewError { Text(reviewError).font(.caption).foregroundStyle(.red) }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(red: 0.965, green: 0.970, blue: 0.945).ignoresSafeArea())
        .task {
            if #available(iOS 17.0, *) {
                do {
                    _ = try await CheckupControlLiveActivityCoordinator.startLocalTest()
                    let activities = Activity<CheckupControlActivityAttributes>.activities
                    activityStatus = "Activité système : " + (activities.first.map { String(describing: $0.activityState) } ?? "absente")
                }
                catch { reviewError = error.localizedDescription }
            }
        }
    }
}
#endif
