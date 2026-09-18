import SwiftUI

struct AddVehicleView: View {
    @Binding var isPresented: Bool
    @State private var plate = ""
    @State private var label = ""
    @State private var dueDate = Date()
    let onSave: (String, String, Date) -> Void

    var body: some View {
        NavigationStack {
            Form {
                Section("Véhicule") {
                    TextField("Immatriculation", text: $plate)
                    TextField("Nom facultatif", text: $label)
                }
                Section("Prochain contrôle technique") {
                    DatePicker("Échéance", selection: $dueDate, in: Date()..., displayedComponents: .date)
                }
            }
            .navigationTitle("Ajouter un véhicule")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Annuler") { isPresented = false }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Enregistrer") {
                        onSave(plate, label, dueDate)
                        isPresented = false
                    }
                    .disabled(plate.isEmpty)
                }
            }
        }
    }
}
