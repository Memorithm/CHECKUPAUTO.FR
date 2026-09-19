import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: AppModel
    @State private var showingAddVehicle = false

    var body: some View {
        NavigationStack {
            List {
                if !model.notificationAuthorized {
                    Section {
                        Button("Activer les rappels") {
                            model.requestNotifications()
                        }
                    } footer: {
                        Text(model.mobileConfig.notifications.remotePushActive
                             ? "Les rappels sont envoyés par Checkup Auto via notifications push."
                             : "Les rappels sont programmés localement sur l’iPhone.")
                    }
                }

                Section("Mes véhicules") {
                    if model.vehicles.isEmpty {
                        ContentUnavailableView(
                            "Aucun véhicule",
                            systemImage: "car",
                            description: Text("Ajoutez un véhicule et la date de son prochain contrôle technique.")
                        )
                    } else {
                        ForEach(model.vehicles) { vehicle in
                            VStack(alignment: .leading, spacing: 6) {
                                Text(vehicle.displayName.isEmpty ? vehicle.registration : vehicle.displayName)
                                    .font(.headline)
                                Text(vehicle.registration)
                                    .font(.caption.monospaced())
                                    .foregroundStyle(.secondary)
                                HStack {
                                    Text("Contrôle technique")
                                    Spacer()
                                    Text(vehicle.controlDueDate, style: .date)
                                        .fontWeight(.semibold)
                                }
                                .font(.subheadline)
                            }
                            .padding(.vertical, 4)
                        }
                        .onDelete(perform: model.delete)
                    }
                }

                Section("Réserver") {
                    Link("Voir les créneaux Checkup Auto", destination: model.bookingURL)
                }

                if let message = model.errorMessage {
                    Section {
                        Text(message)
                            .foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("Checkup Auto")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showingAddVehicle = true
                    } label: {
                        Label("Ajouter", systemImage: "plus")
                    }
                }
            }
            .sheet(isPresented: $showingAddVehicle) {
                AddVehicleView(isPresented: $showingAddVehicle) { registration, name, dueDate in
                    model.add(registration: registration, name: name, dueDate: dueDate)
                }
            }
        }
    }
}

#Preview {
    ContentView()
        .environmentObject(AppModel())
}
