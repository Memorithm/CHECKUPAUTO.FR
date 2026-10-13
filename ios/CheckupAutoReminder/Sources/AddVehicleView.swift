import SwiftUI

/// Native equivalent of the authenticated /compte vehicle editor.
/// The registration and document fields are validated again on the server.
/// Formula numbers are never stored in local preferences or displayed back.
struct AddVehicleView: View {
    @EnvironmentObject private var model: AppModel
    @Binding var isPresented: Bool

    @State private var plate = ""
    @State private var label = ""
    @State private var registrationSystem: VehicleRegistrationSystem = .siv
    @State private var formulaNumber = ""
    @State private var cardIssueDate = Date()
    @State private var fniDateVerified = false
    @State private var guideExpanded = false

    @State private var brands: [CustomerVehicleReferenceOption] = []
    @State private var energies: [CustomerVehicleReferenceOption] = []
    @State private var models: [CustomerVehicleReferenceOption] = []
    @State private var brandId = ""
    @State private var modelId = ""
    @State private var energyId = ""
    @State private var referencesLoading = false
    @State private var modelsLoading = false
    @State private var saving = false
    @State private var message: String?

    @State private var scheduleReminder = false
    @State private var dueDate = Date()
    @State private var customReminderEnabled = false
    @State private var reminderAt = LocalReminderPlan.testDate()

    /// Called only when an optional device-local CT reminder is requested.
    let onSave: (String, String, Date, Date?) -> Void

    private var normalizedPlate: String? {
        VehicleRegistrationRules.normalizedRegistration(plate, system: registrationSystem)
    }

    private var documentValid: Bool {
        VehicleRegistrationRules.validDocument(
            system: registrationSystem,
            formula: registrationSystem == .siv ? formulaNumber : "",
            issueDate: registrationSystem == .fni && fniDateVerified ? cardIssueDate : nil
        )
    }

    private var selectedBrand: CustomerVehicleReferenceOption? {
        brands.first { $0.id == brandId }
    }
    private var selectedModel: CustomerVehicleReferenceOption? {
        models.first { $0.id == modelId }
    }
    private var selectedEnergy: CustomerVehicleReferenceOption? {
        energies.first { $0.id == energyId }
    }

    private var canSave: Bool {
        normalizedPlate != nil && documentValid &&
        selectedBrand != nil && selectedModel != nil && selectedEnergy != nil &&
        !referencesLoading && !modelsLoading && !saving &&
        (!scheduleReminder || (!customReminderEnabled || reminderAt > Date()))
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("MON ESPACE · VÉHICULE")
                            .font(.caption2.monospaced().weight(.semibold))
                            .tracking(1.1)
                            .foregroundStyle(CheckupTheme.accent)
                        Text("Ajoutez votre véhicule.")
                            .font(.system(size: 35, weight: .regular, design: .serif))
                            .foregroundStyle(CheckupTheme.ink)
                        Text("Le véhicule sera enregistré dans votre compte Checkup Auto. Les indications du certificat d’immatriculation sont nécessaires pour identifier votre véhicule.")
                            .font(.subheadline)
                            .foregroundStyle(CheckupTheme.muted)
                    }

                    fieldCard {
                        Label("Immatriculation", systemImage: "car.side.fill")
                            .font(.headline).foregroundStyle(CheckupTheme.ink)
                        Picker("Type d’immatriculation", selection: $registrationSystem) {
                            ForEach(VehicleRegistrationSystem.allCases) { type in
                                Text(type.title).tag(type)
                            }
                        }
                        .pickerStyle(.segmented)
                        .accessibilityIdentifier("vehicle-registration-system")

                        TextField(registrationSystem == .siv ? "AA-123-AA" : "1234 AB 78", text: $plate)
                            .textInputAutocapitalization(.characters)
                            .autocorrectionDisabled()
                            .textContentType(.none)
                            .font(.title3.monospaced().weight(.semibold))
                            .padding(14)
                            .background(CheckupTheme.soft, in: RoundedRectangle(cornerRadius: 14))
                            .accessibilityIdentifier("vehicle-registration")

                        if !plate.isEmpty && normalizedPlate == nil {
                            Text(registrationSystem == .siv
                                 ? "SIV : deux lettres, trois chiffres, deux lettres (AA-123-AA). Vérifiez les caractères et les groupes interdits."
                                 : "FNI : 1 à 4 chiffres, 1 à 3 lettres, puis le département (1234 AB 78, 123 AB 2A, 123 AB 971).")
                                .font(.caption)
                                .foregroundStyle(.red)
                                .accessibilityIdentifier("vehicle-plate-error")
                        } else {
                            Text("La mise en forme et le contrôle du numéro suivent les mêmes règles que sur le site.")
                                .font(.caption)
                                .foregroundStyle(CheckupTheme.muted)
                        }
                    }

                    fieldCard {
                        Label("Carte grise", systemImage: "doc.text.viewfinder")
                            .font(.headline)
                            .foregroundStyle(CheckupTheme.ink)

                        if registrationSystem == .siv {
                            TextField("2020AB12345", text: $formulaNumber)
                                .textInputAutocapitalization(.characters)
                                .autocorrectionDisabled()
                                .textContentType(.none)
                                .font(.body.monospaced())
                                .padding(14)
                                .background(CheckupTheme.soft, in: RoundedRectangle(cornerRadius: 14))
                                .accessibilityIdentifier("vehicle-formula-number")
                            Text("Numéro de formule obligatoire : quatre chiffres pour l’année, deux lettres, cinq chiffres. Ex. 2020AB12345.")
                                .font(.caption)
                                .foregroundStyle(documentValid || formulaNumber.isEmpty ? CheckupTheme.muted : .red)
                        } else {
                            DatePicker(
                                "Date d’établissement du certificat",
                                selection: $cardIssueDate,
                                in: earliestCardIssueDate...Date(),
                                displayedComponents: .date
                            )
                            .datePickerStyle(.compact)
                            .accessibilityIdentifier("vehicle-card-issue-date")
                            Toggle("J’ai vérifié cette date sur la carte grise", isOn: $fniDateVerified)
                                .font(.subheadline)
                                .tint(CheckupTheme.accent)
                        }

                        DisclosureGroup(isExpanded: $guideExpanded) {
                            VStack(alignment: .leading, spacing: 10) {
                                if registrationSystem == .siv {
                                    Text("Le numéro de formule à 11 caractères est visible sous « Certificat d’immatriculation », sur le coupon détachable ou dans la zone de lecture automatique.")
                                        .font(.caption)
                                    cardGuide(url: MobileAPI.vehicleFormulaGuideURL(),
                                              caption: "Trois emplacements possibles du numéro de formule.")
                                } else {
                                    Text("Relevez la date d’établissement de la carte grise (rubrique I), et non la première immatriculation du véhicule (rubrique B).")
                                        .font(.caption)
                                    cardGuide(url: MobileAPI.vehicleCardDateGuideURL(),
                                              caption: "Date du certificat à la rubrique I.")
                                }
                                Text("Photographies indicatives : © Service-Public / Direction de l’information légale et administrative. Ne photographiez pas votre carte grise.")
                                    .font(.caption2)
                                    .foregroundStyle(CheckupTheme.muted)
                            }
                            .padding(.top, 10)
                        } label: {
                            Text(registrationSystem == .siv
                                 ? "Où trouver le numéro de formule ?"
                                 : "Où trouver la date d’établissement ?")
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(CheckupTheme.accent)
                        }
                        .accessibilityIdentifier("vehicle-card-grise-guide")
                    }

                    fieldCard {
                        Label("Caractéristiques", systemImage: "steeringwheel")
                            .font(.headline).foregroundStyle(CheckupTheme.ink)
                        if referencesLoading {
                            ProgressView("Chargement des marques et énergies…")
                        }
                        Picker("Marque", selection: $brandId) {
                            Text("Sélectionnez une marque").tag("")
                            ForEach(brands) { item in Text(item.label).tag(item.id) }
                        }
                        .accessibilityIdentifier("vehicle-brand")
                        Picker("Modèle", selection: $modelId) {
                            Text(modelsLoading ? "Chargement…" : "Sélectionnez un modèle").tag("")
                            ForEach(models) { item in Text(item.label).tag(item.id) }
                        }
                        .disabled(brandId.isEmpty || modelsLoading)
                        .accessibilityIdentifier("vehicle-model")
                        Picker("Énergie", selection: $energyId) {
                            Text("Sélectionnez une énergie").tag("")
                            ForEach(energies) { item in Text(item.label).tag(item.id) }
                        }
                        .accessibilityIdentifier("vehicle-energy")
                        if brands.isEmpty || energies.isEmpty {
                            Button("Réessayer de charger les listes") {
                                Task { await loadReferences() }
                            }
                            .disabled(referencesLoading)
                            .font(.caption.weight(.semibold))
                        }
                    }

                    fieldCard {
                        Toggle("Programmer une échéance CT sur cet iPhone", isOn: $scheduleReminder)
                            .tint(CheckupTheme.accent)
                            .font(.subheadline.weight(.semibold))

                        if scheduleReminder {
                            TextField("Nom facultatif — ex. Ma Peugeot", text: $label)
                                .textFieldStyle(.roundedBorder)
                            DatePicker(
                                "Prochain contrôle technique",
                                selection: $dueDate,
                                in: Date()...,
                                displayedComponents: .date
                            )
                            .datePickerStyle(.graphical)
                            .tint(CheckupTheme.accent)
                            Toggle("Rappel à une date et heure précises", isOn: $customReminderEnabled)
                                .tint(CheckupTheme.accent)
                            if customReminderEnabled {
                                DatePicker("Me rappeler le", selection: $reminderAt,
                                           in: Date()..., displayedComponents: [.date, .hourAndMinute])
                            }
                            Text("L’échéance CT est différente de la date d’établissement de la carte grise. Les rappels restent stockés sur cet iPhone.")
                                .font(.caption)
                                .foregroundStyle(CheckupTheme.muted)
                        }
                    }

                    if let message {
                        Label(message, systemImage: "exclamationmark.circle")
                            .font(.subheadline)
                            .foregroundStyle(.red)
                            .accessibilityIdentifier("vehicle-save-error")
                    }

                    Button {
                        Task { await save() }
                    } label: {
                        HStack {
                            if saving { ProgressView().tint(.white) }
                            Text(saving ? "Enregistrement…" : "Enregistrer dans mon compte")
                                .fontWeight(.semibold)
                            Spacer()
                            Image(systemName: "arrow.right")
                        }
                        .foregroundStyle(.white)
                        .padding(16)
                        .background(CheckupTheme.accent, in: RoundedRectangle(cornerRadius: 16))
                    }
                    .disabled(!canSave)
                    .opacity(canSave ? 1 : 0.5)
                    .accessibilityIdentifier("vehicle-account-save")
                }
                .padding(20)
                .frame(maxWidth: 580)
                .frame(maxWidth: .infinity)
            }
            .background(CheckupTheme.paper.ignoresSafeArea())
            .navigationTitle("Ajouter un véhicule")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Annuler") { isPresented = false }
                }
            }
            .task { await loadReferences() }
            .onChange(of: brandId) { _, value in
                modelId = ""
                models = []
                if !value.isEmpty {
                    Task { await loadModels(for: value) }
                }
            }
            .onChange(of: registrationSystem) { _, _ in
                formulaNumber = ""
                fniDateVerified = false
                guideExpanded = false
            }
            .onChange(of: plate) { _, value in
                if let detected = VehicleRegistrationRules.detectedSystem(value),
                   detected != registrationSystem {
                    registrationSystem = detected
                }
                if let normalized = VehicleRegistrationRules.normalizedRegistration(
                    value, system: registrationSystem
                ), value != normalized {
                    plate = normalized
                }
            }
            .onChange(of: formulaNumber) { _, value in
                let compact = VehicleRegistrationRules.compact(value)
                if value != compact { formulaNumber = compact }
            }
        }
        .tint(CheckupTheme.accent)
    }

    private var earliestCardIssueDate: Date {
        Calendar(identifier: .gregorian).date(
            from: DateComponents(year: 1900, month: 1, day: 1)
        )!
    }

    private func cardGuide(url: URL, caption: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            AsyncImage(url: url) { phase in
                switch phase {
                case .success(let image):
                    image.resizable().scaledToFit()
                        .accessibilityLabel(caption)
                case .failure:
                    Label("Illustration temporairement indisponible", systemImage: "photo")
                        .font(.caption)
                case .empty:
                    ProgressView()
                @unknown default:
                    EmptyView()
                }
            }
            .frame(maxWidth: .infinity)
            Text(caption)
                .font(.caption)
                .foregroundStyle(CheckupTheme.muted)
        }
        .accessibilityIdentifier("vehicle-official-card-image")
    }

    @MainActor
    private func loadReferences() async {
        guard !referencesLoading else { return }
        referencesLoading = true
        defer { referencesLoading = false }
        do {
            let result = try await CustomerAccountAPI.fetchVehicleReferences()
            brands = result.brands
            energies = result.energies
            message = nil
        } catch {
            message = "Les listes de véhicules sont momentanément indisponibles. Réessayez."
        }
    }

    @MainActor
    private func loadModels(for selectedBrandId: String) async {
        modelsLoading = true
        defer {
            if brandId == selectedBrandId { modelsLoading = false }
        }
        do {
            let result = try await CustomerAccountAPI.fetchVehicleReferences(
                brandId: selectedBrandId
            )
            guard brandId == selectedBrandId else { return }
            models = result.models ?? []
            message = nil
        } catch {
            guard brandId == selectedBrandId else { return }
            message = "Impossible de charger les modèles. Choisissez de nouveau la marque."
        }
    }

    @MainActor
    private func save() async {
        guard !saving, canSave, let plate = normalizedPlate,
              let brand = selectedBrand, let vehicleModel = selectedModel,
              let energy = selectedEnergy else { return }
        saving = true
        message = nil
        defer { saving = false }
        let components = Calendar.current.dateComponents([.year, .month, .day], from: cardIssueDate)
        let issueDate = String(format: "%04d-%02d-%02d", components.year ?? 0,
                               components.month ?? 0, components.day ?? 0)
        let payload = CustomerVehicleRegistrationDraft(
            registrationSystem: registrationSystem.rawValue,
            registration: plate,
            formulaNumber: registrationSystem == .siv ? VehicleRegistrationRules.compact(formulaNumber) : "",
            cardIssueDate: registrationSystem == .fni ? issueDate : "",
            characteristics: CustomerVehicleCharacteristics(
                brand: brand.label, model: vehicleModel.label, energy: energy.label
            )
        )
        do {
            let saved = try await CustomerAccountAPI.saveVehicle(payload)
            // The certificate identifier is only submitted to the server, never
            // copied into on-device reminder storage or logs.
            formulaNumber = ""
            if scheduleReminder {
                let displayName = label.isEmpty ? brand.label + " " + vehicleModel.label : label
                onSave(saved.registration, displayName, dueDate,
                       customReminderEnabled ? reminderAt : nil)
            }
            await model.refreshNativeAccount()
            isPresented = false
        } catch CustomerAccountAPIError.sessionExpired {
            model.signOutCustomer()
            message = "Session expirée. Reconnectez-vous pour enregistrer votre véhicule."
        } catch CustomerAccountAPIError.vehicleRejected(let code) {
            switch code {
            case "customer_vehicle_duplicate":
                message = "Ce véhicule figure déjà dans votre compte."
            case "customer_vehicle_limit_reached":
                message = "La limite de 12 véhicules enregistrés est atteinte."
            case "customer_vehicle_formula_number_invalid":
                message = "Vérifiez le numéro de formule sur votre certificat."
            case "customer_vehicle_card_issue_date_invalid":
                message = "Vérifiez la date d’établissement du certificat."
            case "customer_vehicle_registration_invalid":
                message = "Vérifiez le format de l’immatriculation."
            default:
                message = "Enregistrement refusé. Vérifiez les champs et réessayez."
            }
        } catch {
            message = "Impossible de confirmer l’enregistrement. Vérifiez la connexion avant de réessayer."
        }
    }

    private func fieldCard<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 14, content: content)
            .padding(18)
            .background(CheckupTheme.card, in: RoundedRectangle(cornerRadius: 22))
            .overlay(RoundedRectangle(cornerRadius: 22).stroke(CheckupTheme.line))
    }
}
