import SwiftUI

private enum CheckupTheme {
    static let paper = Color(red: 0.965, green: 0.970, blue: 0.945)
    static let card = Color.white
    static let ink = Color(red: 0.115, green: 0.235, blue: 0.185)
    static let muted = Color(red: 0.39, green: 0.45, blue: 0.41)
    static let accent = Color(red: 0.12, green: 0.33, blue: 0.26)
    static let soft = Color(red: 0.91, green: 0.94, blue: 0.91)
    static let line = Color.black.opacity(0.08)
}

private struct BrowserDestination: Identifiable {
    let id = UUID()
    let url: URL
}

struct ContentView: View {
    @EnvironmentObject private var model: AppModel
    @State private var showingAddVehicle = false
    @State private var testReminderAt = LocalReminderPlan.testDate()
    @State private var showingDeleteConfirmation = false
    @State private var vehiclePendingDeletion: VehicleDeadline?
    @State private var browserDestination: BrowserDestination?
    @State private var preproductionClaimLink = ""

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(spacing: 16) {
                    hero
                    if MobileAPI.isPreproduction {
                        statusCard(title: "Préproduction — environnement de test", systemImage: "wrench.and.screwdriver.fill", tint: .orange)
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Rattacher un véhicule ou une cagnotte de test").font(.headline)
                            Text("Copiez le lien de rattachement depuis votre compte de test, puis collez-le ici.").font(.subheadline)
                            SecureField("Lien de rattachement", text: $preproductionClaimLink)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                            Button("Rattacher à cet iPhone") {
                                let link = preproductionClaimLink.trimmingCharacters(in: .whitespacesAndNewlines)
                                preproductionClaimLink = ""
                                if let url = URL(string: link) {
                                    model.consumeMobileClaim(url: url)
                                }
                            }.disabled(preproductionClaimLink.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        }.padding(16).background(CheckupTheme.card, in: RoundedRectangle(cornerRadius: 18))
                    }

                    if !model.notificationAuthorized || model.installationRegistrationSuppressed {
                        notificationCard
                    }

                    if let notice = model.claimNotice {
                        statusCard(
                            title: notice,
                            systemImage: "checkmark.shield.fill",
                            tint: CheckupTheme.accent
                        )
                    }

                    localReminderSection
                    quickActions
                    Text(MobileAPI.isPreproduction
                         ? "Réservation et paiement de test : aucun débit bancaire réel."
                         : "Réservez dans l’app. Le paiement s’effectue sur la page sécurisée du prestataire bancaire.")
                        .font(.caption).foregroundStyle(CheckupTheme.muted)
                    nextControlCard
                    loyaltySection
                    vehicleSection
                    privacySection

                    if let message = model.errorMessage {
                        statusCard(
                            title: message,
                            systemImage: "exclamationmark.triangle.fill",
                            tint: .red
                        )
                    }
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 36)
            }
            .background(CheckupTheme.paper.ignoresSafeArea())
            .navigationTitle("Checkup Auto")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(CheckupTheme.paper, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        openInApp(model.accountURL)
                    } label: {
                        Image(systemName: "person.crop.circle")
                            .font(.title3)
                            .foregroundStyle(CheckupTheme.ink)
                    }
                    .accessibilityLabel("Mon compte")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showingAddVehicle = true
                    } label: {
                        Image(systemName: "plus.circle.fill")
                            .font(.title3)
                            .foregroundStyle(CheckupTheme.accent)
                    }
                    .accessibilityLabel("Ajouter un véhicule")
                }
            }
            .onOpenURL { url in
                if url.scheme == "https" && url.host == MobileAPI.currentBaseURL.host && url.port == MobileAPI.currentBaseURL.port && url.user == nil && url.password == nil && url.path == "/app/live" {
                    let reminderId = URLComponents(url: url, resolvingAgainstBaseURL: false)?
                        .queryItems?
                        .first(where: { $0.name == "reminder" })?
                        .value
                    model.acknowledgeControlLiveActivity(reminderId: reminderId)
                } else {
                    model.consumeMobileClaim(url: url)
                }
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
            .confirmationDialog(
                "Supprimer ce véhicule de l’iPhone ?",
                isPresented: Binding(
                    get: { vehiclePendingDeletion != nil },
                    set: { if !$0 { vehiclePendingDeletion = nil } }
                ),
                titleVisibility: .visible
            ) {
                Button("Supprimer", role: .destructive) {
                    if let vehicle = vehiclePendingDeletion {
                        model.delete(vehicleID: vehicle.id)
                    }
                    vehiclePendingDeletion = nil
                }
                Button("Annuler", role: .cancel) {
                    vehiclePendingDeletion = nil
                }
            }
            .sheet(isPresented: $showingAddVehicle) {
                AddVehicleView(isPresented: $showingAddVehicle) { registration, name, dueDate, reminderAt in
                    model.add(registration: registration, name: name, dueDate: dueDate, reminderAt: reminderAt)
                }
            }
            .fullScreenCover(item: $browserDestination) { destination in
                InAppBrowserView(url: destination.url)
                    .ignoresSafeArea()
            }
        }
        .tint(CheckupTheme.accent)
    }

    private var localReminderSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("Tester les notifications", systemImage: "bell.badge")
                .font(.headline)
                .foregroundStyle(CheckupTheme.ink)
            Text("La popup ci-dessous teste les notifications locales. Le test Dynamic Island est séparé.")
                .font(.caption)
                .foregroundStyle(CheckupTheme.muted)
            DatePicker("Date et heure", selection: $testReminderAt, in: Date()...,
                       displayedComponents: [.date, .hourAndMinute])
            Button("Programmer à cette heure") {
                model.scheduleLocalTest(at: testReminderAt)
            }
            .buttonStyle(.borderedProminent)
            .disabled(model.schedulingLocalTest || testReminderAt <= Date())
            Button("Tester la popup dans 2 minutes") {
                let date = LocalReminderPlan.testDate()
                testReminderAt = date
                model.scheduleLocalTest(at: date)
            }
            .buttonStyle(.bordered)
            .disabled(model.schedulingLocalTest)
            if let notice = model.localReminderNotice {
                Text(notice)
                    .font(.subheadline)
                    .accessibilityAddTraits(.updatesFrequently)
            }
            Button("Annuler le test", role: .cancel) { model.cancelLocalTest() }
                .font(.caption)
                .disabled(model.schedulingLocalTest)
            Divider()
            Label("Tester la Dynamic Island", systemImage: "livephoto")
                .font(.headline)
                .foregroundStyle(CheckupTheme.ink)
            Text("La voiture argentée apparaît dans la Dynamic Island. Maintenez la barre pour lire « Pensez à votre contrôle technique ».")
                .font(.caption)
                .foregroundStyle(CheckupTheme.muted)
            if let notice = model.localActivityTestNotice {
                Text(notice).font(.caption.weight(.semibold)).foregroundStyle(CheckupTheme.accent)
            }
            if model.localActivityTestRunning {
                Button("Relancer le test") { model.startLocalActivityTest() }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.localActivityTestTransitionPending)
                Button("Arrêter le test Dynamic Island", role: .cancel) { model.stopLocalActivityTest() }
                    .buttonStyle(.bordered)
                    .disabled(model.localActivityTestTransitionPending)
            } else {
                Button("Démarrer le test Dynamic Island") { model.startLocalActivityTest() }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.localActivityTestTransitionPending)
            }
            Picker("Klaxon", selection: $model.selectedHorn) {
                ForEach(CheckupControlHornChoice.allCases) { choice in
                    Text(choice.label).tag(choice)
                }
            }
            .pickerStyle(.segmented)
            .accessibilityLabel("Choix du klaxon")
            Button("Écouter le klaxon choisi") { model.previewControlHorn() }
                .buttonStyle(.bordered)
            Text("Le klaxon du test est programmé après cinq secondes. Les notifications et leurs sons doivent être autorisés ; le mode silencieux et les réglages Concentration de l’iPhone peuvent empêcher l’alerte sonore.")
                .font(.caption2)
                .foregroundStyle(CheckupTheme.muted)
            Text("Le test se termine après environ deux minutes si l’app reste active. Revenez dans l’app pour nettoyer un test expiré. Nécessite un iPhone compatible, iOS 17 ou ultérieur, et les Activités en direct activées.")
                .font(.caption2)
                .foregroundStyle(CheckupTheme.muted)
        }
        .padding(20)
        .background(CheckupTheme.card, in: RoundedRectangle(cornerRadius: 22))
        .overlay(RoundedRectangle(cornerRadius: 22).stroke(CheckupTheme.line))
    }

    private var hero: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("MOBILITÉ · CONTRÔLE · PRÉVENTION")
                    .font(.caption2.monospaced().weight(.semibold))
                    .tracking(1.1)
                    .foregroundStyle(CheckupTheme.accent)
                Spacer()
                Circle()
                    .fill(model.remotePushActiveForDevice ? CheckupTheme.accent : CheckupTheme.soft)
                    .frame(width: 10, height: 10)
                    .accessibilityLabel(model.remotePushActiveForDevice ? "Push actif" : "Mode local")
            }

            Text("Votre véhicule,\nsous contrôle.")
                .font(.system(size: 42, weight: .regular, design: .serif))
                .tracking(-1.8)
                .foregroundStyle(CheckupTheme.ink)

            Text("Échéances, fidélité, rapports de contrôle technique et réservation dans un seul espace.")
                .font(.subheadline)
                .foregroundStyle(CheckupTheme.muted)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 10) {
                infoPill(
                    model.remotePushActiveForDevice ? "PUSH VÉRIFIÉ" : "RAPPELS LOCAUX",
                    systemImage: model.remotePushActiveForDevice ? "bell.badge.fill" : "iphone"
                )
                if !model.authoritativeVehicles.isEmpty {
                    infoPill("MERCURE LIÉ", systemImage: "checkmark.shield.fill")
                }
            }
        }
        .padding(24)
        .background(
            RoundedRectangle(cornerRadius: 28, style: .continuous)
                .fill(CheckupTheme.card)
                .overlay(alignment: .topTrailing) {
                    Circle()
                        .fill(CheckupTheme.soft)
                        .frame(width: 150, height: 150)
                        .offset(x: 52, y: -62)
                        .accessibilityHidden(true)
                }
        )
        .overlay(
            RoundedRectangle(cornerRadius: 28, style: .continuous)
                .stroke(CheckupTheme.line)
        )
        .padding(.top, 8)
    }

    private var quickActions: some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionLabel("ACCÈS RAPIDE")

            HStack(spacing: 12) {
                actionButton(
                    title: "Scanner mon CT",
                    subtitle: "Analyse & conseils",
                    systemImage: "doc.viewfinder",
                    destination: model.reportScanURL
                )
                actionButton(
                    title: "Réserver",
                    subtitle: "Créneaux en direct",
                    systemImage: "calendar.badge.plus",
                    destination: model.bookingURL
                )
            }

            Button {
                openInApp(model.accountURL)
            } label: {
                HStack(spacing: 14) {
                    Image(systemName: "person.text.rectangle")
                        .font(.title2)
                        .foregroundStyle(CheckupTheme.accent)
                        .frame(width: 42, height: 42)
                        .background(CheckupTheme.soft, in: RoundedRectangle(cornerRadius: 12))
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Espace client")
                            .font(.headline)
                            .foregroundStyle(CheckupTheme.ink)
                        Text("Compte particulier ou professionnel · historique · rapports")
                            .font(.caption)
                            .foregroundStyle(CheckupTheme.muted)
                    }
                    Spacer()
                    Image(systemName: "arrow.up.right")
                        .foregroundStyle(CheckupTheme.muted)
                }
                .padding(16)
                .background(CheckupTheme.card, in: RoundedRectangle(cornerRadius: 20))
                .overlay(
                    RoundedRectangle(cornerRadius: 20)
                        .stroke(CheckupTheme.line)
                )
            }
        }
    }

    private var nextControlCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            sectionLabel("PROCHAIN CONTRÔLE")
            HStack(alignment: .bottom) {
                VStack(alignment: .leading, spacing: 8) {
                    if let date = model.nextControlDueDate {
                        Text(date, format: .dateTime.day().month(.wide).year())
                            .font(.system(size: 28, weight: .regular, design: .serif))
                            .foregroundStyle(CheckupTheme.ink)
                        Text(daysLabel(until: date))
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(CheckupTheme.accent)
                    } else {
                        Text("Aucune échéance")
                            .font(.system(size: 28, weight: .regular, design: .serif))
                            .foregroundStyle(CheckupTheme.ink)
                        Text("Ajoutez un véhicule ou rattachez-le depuis le centre.")
                            .font(.caption)
                            .foregroundStyle(CheckupTheme.muted)
                    }
                }
                Spacer()
                Image(systemName: "gauge.with.dots.needle.67percent")
                    .font(.system(size: 34))
                    .foregroundStyle(CheckupTheme.accent)
            }
            .padding(20)
            .background(CheckupTheme.card, in: RoundedRectangle(cornerRadius: 22))
            .overlay(
                RoundedRectangle(cornerRadius: 22)
                    .stroke(CheckupTheme.line)
            )
        }
    }

    @ViewBuilder
    private var loyaltySection: some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionLabel("FIDÉLITÉ")

            if model.referralWallets.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    Label("Votre cagnotte Checkup Auto", systemImage: "eurosign.circle")
                        .font(.headline)
                        .foregroundStyle(CheckupTheme.ink)
                    Text("Rattachez la cagnotte depuis votre compte client ou le QR remis par Checkup Auto. Le solde reste calculé côté serveur.")
                        .font(.caption)
                        .foregroundStyle(CheckupTheme.muted)
                    Button("Ouvrir mon compte") {
                        openInApp(model.accountURL)
                    }
                    .font(.subheadline.weight(.semibold))
                }
                .padding(20)
                .background(CheckupTheme.card, in: RoundedRectangle(cornerRadius: 22))
                .overlay(RoundedRectangle(cornerRadius: 22).stroke(CheckupTheme.line))
            } else {
                VStack(alignment: .leading, spacing: 14) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(
                            (Double(model.totalReferralBalanceCents) / 100.0)
                                .formatted(.currency(code: "EUR"))
                        )
                        .font(.system(size: 38, weight: .regular, design: .serif))
                        .foregroundStyle(CheckupTheme.ink)
                        Spacer()
                        Label("Vérifiée", systemImage: "checkmark.shield.fill")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(CheckupTheme.accent)
                    }

                    if model.totalPendingReferralCents > 0 {
                        Text(
                            "En attente : " +
                            (Double(model.totalPendingReferralCents) / 100.0)
                                .formatted(.currency(code: "EUR"))
                        )
                        .font(.caption)
                        .foregroundStyle(CheckupTheme.muted)
                    }

                    ForEach(model.referralWallets) { wallet in
                        HStack {
                            Text(wallet.referralCode)
                                .font(.caption.monospaced().weight(.medium))
                            Spacer()
                            Text("\(wallet.earnedReferrals) acquis")
                                .font(.caption)
                                .foregroundStyle(CheckupTheme.muted)
                        }
                    }
                }
                .padding(20)
                .background(CheckupTheme.card, in: RoundedRectangle(cornerRadius: 22))
                .overlay(RoundedRectangle(cornerRadius: 22).stroke(CheckupTheme.line))
            }
        }
    }

    private var vehicleSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                sectionLabel("MES VÉHICULES")
                Spacer()
                Button {
                    showingAddVehicle = true
                } label: {
                    Label("Ajouter", systemImage: "plus")
                        .font(.caption.weight(.semibold))
                }
            }

            if model.authoritativeVehicles.isEmpty && model.vehicles.isEmpty {
                VStack(spacing: 12) {
                    Image(systemName: "car.side")
                        .font(.system(size: 34))
                        .foregroundStyle(CheckupTheme.accent)
                    Text("Ajoutez votre premier véhicule")
                        .font(.headline)
                        .foregroundStyle(CheckupTheme.ink)
                    Text("Vous pourrez suivre son échéance et recevoir les rappels Checkup Auto.")
                        .font(.caption)
                        .multilineTextAlignment(.center)
                        .foregroundStyle(CheckupTheme.muted)
                    Button("Ajouter un véhicule") {
                        showingAddVehicle = true
                    }
                    .buttonStyle(.borderedProminent)
                }
                .frame(maxWidth: .infinity)
                .padding(28)
                .background(CheckupTheme.card, in: RoundedRectangle(cornerRadius: 22))
                .overlay(RoundedRectangle(cornerRadius: 22).stroke(CheckupTheme.line))
            }

            ForEach(model.authoritativeVehicles) { vehicle in
                vehicleCard(
                    title: "Véhicule Checkup Auto",
                    registration: "Rattaché au centre",
                    dueDate: vehicle.dueDateValue,
                    appointmentAt: vehicle.appointmentAtValue,
                    reminderAt: nil,
                    verified: true,
                    remove: nil
                )
            }

            ForEach(model.vehicles) { vehicle in
                vehicleCard(
                    title: vehicle.displayName.isEmpty ? "Mon véhicule" : vehicle.displayName,
                    registration: vehicle.registration,
                    dueDate: vehicle.controlDueDate,
                    appointmentAt: nil,
                    reminderAt: vehicle.localReminderAt,
                    verified: false,
                    remove: { vehiclePendingDeletion = vehicle }
                )
            }
        }
    }

    private var notificationCard: some View {
        Button {
            model.requestNotifications()
        } label: {
            HStack(spacing: 14) {
                Image(systemName: model.installationRegistrationSuppressed ? "arrow.clockwise.circle.fill" : "bell.badge.fill")
                    .font(.title2)
                VStack(alignment: .leading, spacing: 4) {
                    Text(model.installationRegistrationSuppressed ? "Réactiver Checkup Auto" : "Activer les rappels")
                        .font(.headline)
                    Text(
                        model.installationRegistrationSuppressed
                            ? "La synchronisation de cet iPhone a été désactivée après l’effacement des données."
                            : "Recevez les échéances du contrôle technique sans dépendre d’un rappel manuel."
                    )
                    .font(.caption)
                    .multilineTextAlignment(.leading)
                }
                Spacer()
                Image(systemName: "chevron.right")
            }
            .foregroundStyle(CheckupTheme.ink)
            .padding(18)
            .background(CheckupTheme.soft, in: RoundedRectangle(cornerRadius: 20))
        }
        .buttonStyle(.plain)
    }

    private var privacySection: some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionLabel("DONNÉES & CONFIDENTIALITÉ")
            Button(role: .destructive) {
                showingDeleteConfirmation = true
            } label: {
                HStack {
                    Label(
                        model.deletingAllData ? "Suppression…" : "Effacer mes données de cet iPhone",
                        systemImage: "trash"
                    )
                    Spacer()
                    Image(systemName: "chevron.right")
                }
                .padding(16)
                .background(CheckupTheme.card, in: RoundedRectangle(cornerRadius: 18))
                .overlay(RoundedRectangle(cornerRadius: 18).stroke(CheckupTheme.line))
            }
            .disabled(model.deletingAllData)
        }
    }

    private func actionButton(
        title: String,
        subtitle: String,
        systemImage: String,
        destination: URL
    ) -> some View {
        Button {
            openInApp(destination)
        } label: {
            VStack(alignment: .leading, spacing: 14) {
                Image(systemName: systemImage)
                    .font(.title2)
                    .foregroundStyle(CheckupTheme.accent)
                    .frame(width: 44, height: 44)
                    .background(CheckupTheme.soft, in: RoundedRectangle(cornerRadius: 14))
                Spacer(minLength: 0)
                Text(title)
                    .font(.headline)
                    .foregroundStyle(CheckupTheme.ink)
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(CheckupTheme.muted)
            }
            .frame(maxWidth: .infinity, minHeight: 142, alignment: .leading)
            .padding(18)
            .background(CheckupTheme.card, in: RoundedRectangle(cornerRadius: 22))
            .overlay(RoundedRectangle(cornerRadius: 22).stroke(CheckupTheme.line))
        }
    }

    private func vehicleCard(
        title: String,
        registration: String,
        dueDate: Date?,
        appointmentAt: Date?,
        reminderAt: Date?,
        verified: Bool,
        remove: (() -> Void)?
    ) -> some View {
        HStack(spacing: 14) {
            Image(systemName: verified ? "checkmark.shield.fill" : "car.side.fill")
                .font(.title2)
                .foregroundStyle(CheckupTheme.accent)
                .frame(width: 44, height: 44)
                .background(CheckupTheme.soft, in: RoundedRectangle(cornerRadius: 14))

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.headline)
                    .foregroundStyle(CheckupTheme.ink)
                Text(registration)
                    .font(.caption.monospaced())
                    .foregroundStyle(CheckupTheme.muted)
                if let appointmentAt {
                    Label(
                        "Rendez-vous : " + appointmentAt.formatted(date: .abbreviated, time: .shortened),
                        systemImage: "calendar.badge.clock"
                    )
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(CheckupTheme.accent)
                }
                if let reminderAt {
                    Label("Rappel : " + reminderAt.formatted(date: .abbreviated, time: .shortened),
                          systemImage: "bell.badge")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(CheckupTheme.accent)
                }
                if let dueDate {
                    Text("Contrôle : \(dueDate.formatted(date: .abbreviated, time: .omitted))")
                        .font(.caption)
                        .foregroundStyle(CheckupTheme.muted)
                } else {
                    Text("Échéance en synchronisation")
                        .font(.caption)
                        .foregroundStyle(CheckupTheme.muted)
                }
            }

            Spacer()

            if let remove {
                Menu {
                    Button("Supprimer de l’iPhone", role: .destructive, action: remove)
                } label: {
                    Image(systemName: "ellipsis.circle")
                        .font(.title3)
                        .foregroundStyle(CheckupTheme.muted)
                }
            }
        }
        .padding(16)
        .background(CheckupTheme.card, in: RoundedRectangle(cornerRadius: 20))
        .overlay(RoundedRectangle(cornerRadius: 20).stroke(CheckupTheme.line))
    }

    private func statusCard(title: String, systemImage: String, tint: Color) -> some View {
        Label(title, systemImage: systemImage)
            .font(.subheadline)
            .foregroundStyle(tint)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
            .background(CheckupTheme.card, in: RoundedRectangle(cornerRadius: 18))
            .overlay(RoundedRectangle(cornerRadius: 18).stroke(CheckupTheme.line))
    }

    private func sectionLabel(_ title: String) -> some View {
        Text(title)
            .font(.caption2.monospaced().weight(.semibold))
            .tracking(1.0)
            .foregroundStyle(CheckupTheme.muted)
    }

    private func infoPill(_ title: String, systemImage: String) -> some View {
        Label(title, systemImage: systemImage)
            .font(.caption2.monospaced().weight(.semibold))
            .foregroundStyle(CheckupTheme.ink)
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(CheckupTheme.soft, in: Capsule())
    }

    private func openInApp(_ url: URL) {
        browserDestination = BrowserDestination(url: url)
    }

    private func daysLabel(until date: Date) -> String {
        let calendar = Calendar.current
        let start = calendar.startOfDay(for: Date())
        let end = calendar.startOfDay(for: date)
        let days = calendar.dateComponents([.day], from: start, to: end).day ?? 0
        if days < 0 { return "Échéance dépassée de \(-days) jour(s)" }
        if days == 0 { return "Échéance aujourd’hui" }
        if days == 1 { return "Échéance demain" }
        return "Dans \(days) jours"
    }
}

#Preview {
    ContentView()
        .environmentObject(AppModel())
}
