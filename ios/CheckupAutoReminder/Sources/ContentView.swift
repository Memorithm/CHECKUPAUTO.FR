import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: AppModel
    @State private var showingAddVehicle = false
    @State private var showingDeleteConfirmation = false

    var body: some View {
        NavigationStack {
            List {
                if !model.notificationAuthorized || model.installationRegistrationSuppressed {
                    Section {
                        Button {
                            model.requestNotifications()
                        } label: {
                            Text(
                                model.installationRegistrationSuppressed
                                    ? "Réactiver Checkup Auto"
                                    : "Activer les rappels"
                            )
                        }
                    } footer: {
                        Text(model.installationRegistrationSuppressed
                             ? "La synchronisation Checkup Auto est désactivée sur cet iPhone après l’effacement des données."
                             : "Les rappels restent programmés localement sur l’iPhone tant que le push distant n’est pas confirmé.")
                    }
                }

                if let notice = model.claimNotice {
                    Section("Rattachement") {
                        Label(notice, systemImage: "checkmark.shield.fill")
                            .foregroundStyle(.green)
                    }
                }

                if !model.referralWallets.isEmpty {
                    Section {
                        ForEach(model.referralWallets) { wallet in
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    Label("Cagnotte vérifiée", systemImage: "eurosign.circle.fill")
                                    Spacer()
                                    Text(
                                        (Double(wallet.balanceCents) / 100.0)
                                            .formatted(.currency(code: wallet.currency))
                                    )
                                    .fontWeight(.semibold)
                                }
                                Text("Code de parrainage : \(wallet.referralCode)")
                                    .font(.caption.monospaced())
                                    .foregroundStyle(.secondary)
                                if wallet.pendingReferrals > 0 || wallet.pendingCents > 0 {
                                    Text(
                                        "En attente : \(wallet.pendingReferrals) parrainage(s) · " +
                                        (Double(wallet.pendingCents) / 100.0)
                                            .formatted(.currency(code: wallet.currency))
                                    )
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                }
                            }
                            .padding(.vertical, 4)
                        }
                    } header: {
                        Text("Cagnotte")
                    } footer: {
                        Text("Solde issu de la dernière preuve vérifiée par Checkup Auto ; il peut évoluer depuis cette vérification.")
                    }
                }

                if !model.authoritativeVehicles.isEmpty {
                    Section("Véhicules Checkup Auto") {
                        ForEach(model.authoritativeVehicles) { vehicle in
                            HStack {
                                Label("Véhicule rattaché", systemImage: "checkmark.shield")
                                Spacer()
                                if let dueDate = vehicle.dueDateValue {
                                    Text(dueDate, style: .date)
                                        .fontWeight(.semibold)
                                } else {
                                    Text("Synchronisation…")
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .font(.subheadline)
                        }
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

                Section {
                    Button("Effacer mes données Checkup Auto", role: .destructive) {
                        showingDeleteConfirmation = true
                    }
                    .disabled(model.deletingAllData)
                } header: {
                    Text("Données")
                } footer: {
                    Text("Supprime l’installation, ses rattachements véhicule et cagnotte, les véhicules enregistrés sur cet iPhone et les rappels programmés.")
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
            .onOpenURL { url in
                model.consumeMobileClaim(url: url)
            }
            .onReceive(NotificationCenter.default.publisher(for: DeviceRegistrationState.changedNotification)) { _ in
                model.refreshRegistrationState()
            }
            .confirmationDialog(
                "Effacer toutes les données Checkup Auto de cet iPhone ?",
                isPresented: $showingDeleteConfirmation,
                titleVisibility: .visible
            ) {
                Button("Effacer définitivement", role: .destructive) {
                    model.deleteAllData()
                }
                Button("Annuler", role: .cancel) {}
            } message: {
                Text("Cette action supprime aussi les rattachements véhicule et cagnotte de cet iPhone côté Checkup Auto. Elle ne modifie pas les données réglementaires conservées dans Mercure.")
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
