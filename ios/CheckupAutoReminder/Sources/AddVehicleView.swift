import SwiftUI

struct AddVehicleView: View {
    @Binding var isPresented: Bool
    @State private var plate = ""
    @State private var label = ""
    @State private var dueDate = Date()
    @State private var customReminderEnabled = false
    @State private var reminderAt = LocalReminderPlan.testDate()
    let onSave: (String, String, Date, Date?) -> Void

    private let paper = Color(red: 0.965, green: 0.970, blue: 0.945)
    private let ink = Color(red: 0.115, green: 0.235, blue: 0.185)
    private let accent = Color(red: 0.12, green: 0.33, blue: 0.26)

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("NOUVEAU VÉHICULE")
                            .font(.caption2.monospaced().weight(.semibold))
                            .tracking(1.1)
                            .foregroundStyle(accent)
                        Text("Ajoutez une échéance en quelques secondes.")
                            .font(.system(size: 34, weight: .regular, design: .serif))
                            .tracking(-1.2)
                            .foregroundStyle(ink)
                        Text("L’immatriculation reste sur cet iPhone pour les véhicules ajoutés manuellement.")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.bottom, 4)

                    fieldCard {
                        Label("Véhicule", systemImage: "car.side.fill")
                            .font(.headline)
                            .foregroundStyle(ink)

                        TextField("Immatriculation", text: $plate)
                            .textInputAutocapitalization(.characters)
                            .autocorrectionDisabled()
                            .font(.title3.monospaced().weight(.semibold))
                            .padding(14)
                            .background(Color.black.opacity(0.035), in: RoundedRectangle(cornerRadius: 14))

                        TextField("Nom facultatif — ex. 208, Utilitaire", text: $label)
                            .padding(14)
                            .background(Color.black.opacity(0.035), in: RoundedRectangle(cornerRadius: 14))
                    }

                    fieldCard {
                        Label("Prochain contrôle technique", systemImage: "calendar.badge.clock")
                            .font(.headline)
                            .foregroundStyle(ink)

                        DatePicker(
                            "Échéance",
                            selection: $dueDate,
                            in: Date()...,
                            displayedComponents: .date
                        )
                        .datePickerStyle(.graphical)
                        .tint(accent)
                    }

                    fieldCard {
                        Toggle("Rappel à une date et une heure précises", isOn: $customReminderEnabled)
                            .tint(accent)
                        if customReminderEnabled {
                            DatePicker("Me rappeler le", selection: $reminderAt, in: Date()...,
                                       displayedComponents: [.date, .hourAndMinute])
                            Text("Heure locale de cet iPhone. Ce rappel fonctionne sans Internet et ne change pas la date du contrôle.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }

                    Button {
                        onSave(plate, label, dueDate, customReminderEnabled ? reminderAt : nil)
                        isPresented = false
                    } label: {
                        HStack {
                            Text("Enregistrer le véhicule")
                                .fontWeight(.semibold)
                            Spacer()
                            Image(systemName: "arrow.right")
                        }
                        .foregroundStyle(.white)
                        .padding(16)
                        .background(accent, in: RoundedRectangle(cornerRadius: 16))
                    }
                    .disabled(plate.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || (customReminderEnabled && reminderAt <= Date()))
                    .opacity(plate.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? 0.45 : 1)
                }
                .padding(20)
            }
            .background(paper.ignoresSafeArea())
            .navigationTitle("Ajouter")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(paper, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Annuler") { isPresented = false }
                }
            }
        }
    }

    private func fieldCard<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 14, content: content)
            .padding(18)
            .background(.white, in: RoundedRectangle(cornerRadius: 22))
            .overlay(
                RoundedRectangle(cornerRadius: 22)
                    .stroke(Color.black.opacity(0.08))
            )
    }
}
