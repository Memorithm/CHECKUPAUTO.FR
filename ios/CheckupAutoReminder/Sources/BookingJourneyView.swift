import SwiftUI
import WebKit
#if canImport(UIKit)
import UIKit
#endif

// MARK: - Planning model (public Mercure JSON, Cloudflare-cached)

struct BookingService: Decodable, Identifiable {
    let key: String
    let label: String
    let basePrice: Double
    var id: String { key }
}

struct BookingSlot: Decodable, Identifiable {
    let time: String
    let price: Double
    var id: String { time }
}

struct BookingDay: Decodable, Identifiable {
    let date: String
    let weekday: String
    let day: String
    let month: String
    let available: Bool
    let slots: [BookingSlot]
    var id: String { date }
}

private struct BookingServicesResponse: Decodable {
    let services: [BookingService]
    let businessDate: String
}

private struct BookingAvailabilityResponse: Decodable {
    let days: [BookingDay]
}

enum BookingPlannerLoader {
    static func services() async throws -> (services: [BookingService], businessDate: String) {
        let (data, response) = try await URLSession.shared.data(from: MobileAPI.mercureServicesURL())
        try validate(response)
        let decoded = try JSONDecoder().decode(BookingServicesResponse.self, from: data)
        let supported = decoded.services.filter { $0.key == "technical" || $0.key == "fitted" }
        return (supported, decoded.businessDate)
    }

    static func availability(serviceKey: String, date: String) async throws -> [BookingDay] {
        let (data, response) = try await URLSession.shared.data(
            from: MobileAPI.mercureAvailabilityURL(serviceKey: serviceKey, date: date)
        )
        try validate(response)
        return try JSONDecoder().decode(BookingAvailabilityResponse.self, from: data).days
    }

    private static func validate(_ response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }
    }
}

/// Keeps the services list warm so the first booking screen is instant.
@MainActor
enum BookingPlannerCache {
    private static var cached: (services: [BookingService], businessDate: String, at: Date)?

    static func store(services: [BookingService], businessDate: String) {
        cached = (services, businessDate, Date())
    }

    static func fresh() -> (services: [BookingService], businessDate: String)? {
        guard let cached, Date().timeIntervalSince(cached.at) < 300 else { return nil }
        return (cached.services, cached.businessDate)
    }

    static func prefetch() async {
        if fresh() != nil { return }
        if let result = try? await BookingPlannerLoader.services() {
            store(services: result.services, businessDate: result.businessDate)
        }
    }
}

// MARK: - Journey

private struct BookingPaymentPage: Identifiable {
    let id = UUID()
    let url: URL
}

/// The complete booking journey inside the app: a native planner for choosing
/// the slot, then the signed-in in-site Mercure summary and hosted checkout in
/// the app's own WebKit view with the existing session (no second login). Only
/// the Payline card page opens in a window, and it closes automatically once
/// the payment is confirmed or cancelled.
struct BookingJourneyView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss

    /// Degraded fallback to the web journey when the scoped session cannot be
    /// prepared. Kept deliberately so the booking button always leads somewhere.
    let onWebFallback: () -> Void

    private enum Phase: Equatable { case planner, journey }

    @State private var phase: Phase = .planner

    // Planner state
    @State private var services: [BookingService] = []
    @State private var selectedServiceKey = ""
    @State private var businessDate = ""
    @State private var days: [BookingDay] = []
    @State private var selectedDate = ""
    @State private var selectedTime = ""
    @State private var loadingServices = true
    @State private var loadingSlots = false
    @State private var plannerError: String?
    // Pagination: the public availability endpoint returns a single window per
    // request, bounded by the booking horizon, so the planner advances a cursor
    // to let the customer browse further days when the first window is full.
    @State private var canLoadMore = false
    @State private var loadingMore = false
    @State private var nextStart = ""
    @State private var loadMoreCount = 0

    // Journey state
    @State private var bookingCookie: HTTPCookie?
    @State private var entryURL: URL?
    @State private var webIdentity = UUID()
    @State private var preparing = false
    @State private var journeyError: String?
    @State private var payment: BookingPaymentPage?
    @State private var outcome: BookingOutcome?
    @State private var showGPSPicker = false

    private var selectedService: BookingService? {
        services.first { $0.key == selectedServiceKey }
    }

    private var canContinue: Bool {
        selectedService != nil && !selectedDate.isEmpty && !selectedTime.isEmpty
    }

    var body: some View {
        NavigationStack {
            ZStack {
                CheckupTheme.paper.ignoresSafeArea()
                switch phase {
                case .planner:
                    plannerContent
                case .journey:
                    journeyContent
                }
                if let outcome {
                    completionOverlay(outcome)
                }
            }
            .navigationTitle("Réserver un contrôle")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        showGPSPicker = true
                    } label: {
                        Label("Itinéraire", systemImage: "location.north.line")
                    }
                    .accessibilityIdentifier("booking-journey-gps")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Fermer") { dismiss() }
                        .accessibilityIdentifier("booking-journey-close")
                }
            }
            .centreGPSChoice(isPresented: $showGPSPicker)
            .fullScreenCover(item: $payment) { page in
                PaymentHandoffView(url: page.url, onClose: { payment = nil })
            }
            .task { await loadServices() }
        }
        .tint(CheckupTheme.accent)
        .accessibilityIdentifier("booking-journey")
    }

    // MARK: Planner

    private var plannerContent: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Disponibilités en direct du centre, paiement sécurisé sans quitter l’application.")
                    .font(.subheadline)
                    .foregroundStyle(CheckupTheme.muted)

                if loadingServices {
                    loadingRow("Chargement des prestations…")
                } else if let plannerError, services.isEmpty {
                    errorRow(plannerError) { Task { await loadServices() } }
                } else {
                    servicePicker
                    slotSection
                }
            }
            .padding(20)
            .frame(maxWidth: 560)
            .frame(maxWidth: .infinity)
        }
        .safeAreaInset(edge: .bottom) {
            if !services.isEmpty {
                continueBar
            }
        }
    }

    private var servicePicker: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("PRESTATION")
                .font(.caption.weight(.semibold))
                .foregroundStyle(CheckupTheme.muted)
            Picker("Prestation", selection: $selectedServiceKey) {
                ForEach(services) { service in
                    Text(service.label).tag(service.key)
                }
            }
            .pickerStyle(.segmented)
            .onChange(of: selectedServiceKey) { _, _ in
                Task { await loadSlots() }
            }
            if let service = selectedService {
                Text("À partir de \(priceText(service.basePrice)) · contrôle au centre des Mureaux")
                    .font(.footnote)
                    .foregroundStyle(CheckupTheme.muted)
            }
        }
    }

    @ViewBuilder
    private var slotSection: some View {
        if loadingSlots {
            loadingRow("Connexion à Mercure…")
        } else {
            let bookableDays = days.filter { $0.available && !$0.slots.isEmpty }
            if bookableDays.isEmpty && !canLoadMore {
                errorRow(plannerError ?? "Aucun créneau disponible pour le moment. Vous pouvez appeler le centre.") {
                    Task { await loadSlots() }
                }
            } else {
                VStack(alignment: .leading, spacing: 16) {
                    ForEach(bookableDays) { day in
                        dayCard(day)
                    }
                    if bookableDays.isEmpty {
                        Text("Aucun créneau sur cette période. Cherchez un peu plus loin :")
                            .font(.subheadline)
                            .foregroundStyle(CheckupTheme.muted)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    if canLoadMore {
                        loadMoreButton
                    }
                }
            }
        }
    }

    private var loadMoreButton: some View {
        Button {
            Task { await loadMore() }
        } label: {
            HStack(spacing: 8) {
                if loadingMore { ProgressView() }
                Text(loadingMore ? "Recherche de créneaux…" : "Afficher plus de créneaux")
                    .font(.subheadline.weight(.semibold))
            }
            .frame(maxWidth: .infinity, minHeight: 46)
        }
        .buttonStyle(.bordered)
        .tint(CheckupTheme.accent)
        .disabled(loadingMore)
        .accessibilityIdentifier("booking-load-more")
    }

    private func dayCard(_ day: BookingDay) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("\(day.weekday) \(day.day) \(day.month)")
                .font(.headline)
                .foregroundStyle(CheckupTheme.ink)
            LazyVGrid(
                columns: [GridItem(.adaptive(minimum: 84), spacing: 10)],
                alignment: .leading,
                spacing: 10
            ) {
                ForEach(day.slots) { slot in
                    slotButton(day: day, slot: slot)
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(CheckupTheme.card, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(CheckupTheme.line, lineWidth: 1)
        )
    }

    private func slotButton(day: BookingDay, slot: BookingSlot) -> some View {
        let isSelected = selectedDate == day.date && selectedTime == slot.time
        return Button {
            selectedDate = day.date
            selectedTime = slot.time
        } label: {
            Text(slot.time)
                .font(.subheadline.weight(.semibold))
                .frame(maxWidth: .infinity, minHeight: 44)
                .foregroundStyle(isSelected ? Color.white : CheckupTheme.ink)
                .background(
                    isSelected ? CheckupTheme.accent : CheckupTheme.soft,
                    in: RoundedRectangle(cornerRadius: 12, style: .continuous)
                )
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("booking-slot-\(day.date)-\(slot.time)")
    }

    private var continueBar: some View {
        VStack(spacing: 0) {
            Divider()
            Button {
                Task { await startJourney() }
            } label: {
                HStack {
                    if preparing {
                        ProgressView().tint(.white)
                    }
                    Text(continueTitle)
                        .font(.headline)
                }
                .frame(maxWidth: .infinity, minHeight: 52)
            }
            .buttonStyle(.borderedProminent)
            .tint(CheckupTheme.accent)
            .disabled(!canContinue || preparing)
            .padding(16)
            .accessibilityIdentifier("booking-continue")
        }
        .background(.ultraThinMaterial)
    }

    private var continueTitle: String {
        guard canContinue, let service = selectedService else {
            return "Choisissez un créneau"
        }
        return "Continuer · \(service.label) · \(selectedTime)"
    }

    // MARK: Journey (web)

    @ViewBuilder
    private var journeyContent: some View {
        if let journeyError {
            VStack(spacing: 18) {
                Spacer()
                Image(systemName: "arrow.clockwise.circle")
                    .font(.system(size: 46, weight: .light))
                    .foregroundStyle(CheckupTheme.accent)
                Text(journeyError)
                    .multilineTextAlignment(.center)
                    .font(.subheadline)
                    .foregroundStyle(CheckupTheme.muted)
                Button {
                    Task { await startJourney(force: true) }
                } label: {
                    Label("Réessayer sans me reconnecter", systemImage: "arrow.clockwise")
                        .frame(maxWidth: .infinity, minHeight: 48)
                }
                .buttonStyle(.borderedProminent)
                .tint(CheckupTheme.accent)
                Button("Choisir un autre créneau") { backToPlanner() }
                    .buttonStyle(.bordered)
                Spacer()
            }
            .frame(maxWidth: 430)
            .padding(24)
        } else if let activeBookingCookie = bookingCookie, let entryURL {
            AuthenticatedBookingWebView(
                cookie: activeBookingCookie,
                entryURL: entryURL,
                onPayment: { url in payment = BookingPaymentPage(url: url) },
                onResult: { result in
                    payment = nil
                    outcome = result
                },
                onModifySlot: { backToPlanner() },
                onFinished: {
                    Task { await model.refreshNativeAccount() }
                    dismiss()
                },
                onSessionExpired: {
                    NativeDashboardBridge.invalidate()
                    bookingCookie = nil
                    journeyError = "La session a expiré. Reprenez sans vous reconnecter."
                },
                onBlocked: {}
            )
            .id(webIdentity)
            .ignoresSafeArea(.container, edges: .bottom)
        } else {
            loadingRow("Préparation de votre session sécurisée…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func completionOverlay(_ outcome: BookingOutcome) -> some View {
        VStack(spacing: 18) {
            Image(systemName: outcome == .confirmed ? "checkmark.seal.fill" : "xmark.seal")
                .font(.system(size: 54, weight: .regular))
                .foregroundStyle(outcome == .confirmed ? CheckupTheme.accent : Color.orange)
            Text(outcome == .confirmed ? "Rendez-vous confirmé et payé." : "Paiement non effectué.")
                .font(.system(size: 26, weight: .regular, design: .serif))
                .multilineTextAlignment(.center)
                .foregroundStyle(CheckupTheme.ink)
            Text(outcome == .confirmed
                 ? "Le centre vous envoie la confirmation par e-mail. Vous retrouvez ce rendez-vous dans votre espace client."
                 : "Le créneau a été libéré et aucun montant n’a été prélevé.")
                .multilineTextAlignment(.center)
                .font(.subheadline)
                .foregroundStyle(CheckupTheme.muted)
            if outcome == .confirmed {
                Button {
                    Task { await model.refreshNativeAccount() }
                    dismiss()
                } label: {
                    Text("Terminé").frame(maxWidth: .infinity, minHeight: 50)
                }
                .buttonStyle(.borderedProminent)
                .tint(CheckupTheme.accent)
            } else {
                Button {
                    Task { await model.refreshNativeAccount() }
                    self.outcome = nil
                    backToPlanner()
                } label: {
                    Text("Choisir un autre créneau").frame(maxWidth: .infinity, minHeight: 50)
                }
                .buttonStyle(.borderedProminent)
                .tint(CheckupTheme.accent)
                Button("Fermer") { dismiss() }
                    .buttonStyle(.bordered)
            }
        }
        .frame(maxWidth: 430)
        .padding(28)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(CheckupTheme.paper.ignoresSafeArea())
        .accessibilityIdentifier("booking-journey-result")
    }

    // MARK: Helpers

    private func loadingRow(_ title: String) -> some View {
        HStack(spacing: 12) {
            ProgressView()
            Text(title)
                .font(.subheadline)
                .foregroundStyle(CheckupTheme.muted)
        }
        .frame(maxWidth: .infinity, alignment: .center)
        .padding(.vertical, 28)
    }

    private func errorRow(_ message: String, retry: @escaping () -> Void) -> some View {
        VStack(spacing: 12) {
            Text(message)
                .multilineTextAlignment(.center)
                .font(.subheadline)
                .foregroundStyle(CheckupTheme.muted)
            Button("Réessayer", action: retry)
                .buttonStyle(.bordered)
                .tint(CheckupTheme.accent)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 24)
    }

    private func priceText(_ value: Double) -> String {
        "\(Int(value.rounded())) €"
    }

    /// Shifts a `yyyy-MM-dd` business date by whole days, in the centre's
    /// timezone, to page the availability cursor forward.
    private func shiftDate(_ ymd: String, by days: Int) -> String? {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Europe/Paris") ?? TimeZone(identifier: "UTC")!
        let formatter = DateFormatter()
        formatter.calendar = calendar
        formatter.timeZone = calendar.timeZone
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        guard let date = formatter.date(from: ymd),
              let shifted = calendar.date(byAdding: .day, value: days, to: date) else { return nil }
        return formatter.string(from: shifted)
    }

    @MainActor
    private func loadServices() async {
        if services.isEmpty, let warm = BookingPlannerCache.fresh() {
            services = warm.services
            businessDate = warm.businessDate
            selectedServiceKey = defaultServiceKey(warm.services)
            loadingServices = false
            await loadSlots()
            return
        }
        loadingServices = true
        plannerError = nil
        do {
            let result = try await BookingPlannerLoader.services()
            BookingPlannerCache.store(services: result.services, businessDate: result.businessDate)
            services = result.services
            businessDate = result.businessDate
            selectedServiceKey = defaultServiceKey(result.services)
            loadingServices = false
            await loadSlots()
        } catch {
            loadingServices = false
            plannerError = "Les disponibilités sont momentanément indisponibles. Réessayez ou appelez le centre."
        }
    }

    private func defaultServiceKey(_ list: [BookingService]) -> String {
        if !selectedServiceKey.isEmpty, list.contains(where: { $0.key == selectedServiceKey }) {
            return selectedServiceKey
        }
        if list.contains(where: { $0.key == "technical" }) { return "technical" }
        return list.first?.key ?? ""
    }

    @MainActor
    private func loadSlots() async {
        guard !selectedServiceKey.isEmpty, !businessDate.isEmpty else { return }
        loadingSlots = true
        plannerError = nil
        selectedDate = ""
        selectedTime = ""
        canLoadMore = false
        loadingMore = false
        nextStart = ""
        loadMoreCount = 0
        let serviceKey = selectedServiceKey
        let date = businessDate
        do {
            let loaded = try await BookingPlannerLoader.availability(serviceKey: serviceKey, date: date)
            guard serviceKey == selectedServiceKey else { return }
            days = loaded
            loadingSlots = false
            // Point the cursor just past the furthest day returned (or a week
            // ahead if this first window is empty) so "plus de créneaux" can
            // reach the following days, up to the server's booking horizon.
            nextStart = (loaded.map { $0.date }.max()).flatMap { shiftDate($0, by: 1) }
                ?? shiftDate(date, by: 7) ?? ""
            canLoadMore = !nextStart.isEmpty
        } catch {
            guard serviceKey == selectedServiceKey else { return }
            days = []
            loadingSlots = false
            plannerError = "Les créneaux sont momentanément indisponibles. Réessayez ou appelez le centre."
        }
    }

    @MainActor
    private func loadMore() async {
        guard canLoadMore, !loadingMore, !loadingSlots, !nextStart.isEmpty else { return }
        let serviceKey = selectedServiceKey
        let start = nextStart
        loadingMore = true
        defer { loadingMore = false }
        do {
            let more = try await BookingPlannerLoader.availability(serviceKey: serviceKey, date: start)
            guard serviceKey == selectedServiceKey else { return }
            let known = Set(days.map { $0.date })
            let fresh = more.filter { !known.contains($0.date) }
            days.append(contentsOf: fresh)
            loadMoreCount += 1
            if !fresh.isEmpty, let furthest = days.map({ $0.date }).max(),
               let next = shiftDate(furthest, by: 1) {
                nextStart = next
            } else if let next = shiftDate(start, by: 7) {
                // This window added nothing: step past it to keep looking.
                nextStart = next
            } else {
                nextStart = ""
            }
            if nextStart.isEmpty || loadMoreCount >= 8 { canLoadMore = false }
        } catch {
            // Beyond the booking horizon, or momentarily unavailable: stop here.
            canLoadMore = false
        }
    }

    @MainActor
    private func startJourney(force: Bool = false) async {
        guard let service = selectedService,
              let url = MobileAPI.inAppBookingEntryURL(
                serviceLabel: service.label, date: selectedDate, time: selectedTime
              ) else { return }
        preparing = true
        journeyError = nil
        defer { preparing = false }
        do {
            let cookie = try await NativeDashboardBridge.createBrowserCookie()
            bookingCookie = cookie
            entryURL = url
            webIdentity = UUID()
            outcome = nil
            phase = .journey
        } catch NativeDashboardBridgeError.expiredNativeSession {
            // The native session itself is gone: let the app surface recovery.
            model.signOutCustomer()
            dismiss()
        } catch {
            if force {
                // Repeated failure: offer the web journey rather than trap here.
                onWebFallback()
                dismiss()
            } else {
                phase = .journey
                journeyError = "La connexion sécurisée est momentanément indisponible. Votre compte reste connecté."
            }
        }
    }

    private func backToPlanner() {
        payment = nil
        outcome = nil
        journeyError = nil
        bookingCookie = nil
        entryURL = nil
        phase = .planner
    }
}

/// The information step shown inside the app immediately before the external
/// Payline card page opens. It makes unmistakably clear — with an animated
/// alert — that the customer must not close the app and must come back to it
/// after paying, since the rendez-vous is only confirmed here. Respects Reduce
/// Motion (the alert stays steady and high-contrast instead of flashing).
private struct PaymentHandoffView: View {
    let url: URL
    let onClose: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var step: Step = .warning
    @State private var pulse: Double = 1

    private enum Step { case warning, paying }

    var body: some View {
        switch step {
        case .warning:
            warning
        case .paying:
            InAppBrowserView(url: url)
                .ignoresSafeArea()
        }
    }

    private var warning: some View {
        VStack(spacing: 22) {
            Spacer(minLength: 8)
            VStack(spacing: 12) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 46, weight: .bold))
                Text("Ne fermez pas l’application")
                    .font(.system(size: 27, weight: .heavy))
                    .multilineTextAlignment(.center)
            }
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 26)
            .padding(.horizontal, 20)
            .background(Color(red: 0.80, green: 0.14, blue: 0.10))
            .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .stroke(Color.yellow, lineWidth: 5)
                    .opacity(pulse)
            )
            .scaleEffect(reduceMotion ? 1 : 1 + CGFloat(1 - pulse) * 0.02)
            .accessibilityElement(children: .combine)
            .accessibilityAddTraits(.isHeader)

            VStack(spacing: 12) {
                Text("Le paiement par carte (Payline) va s’ouvrir.")
                    .font(.headline)
                    .foregroundStyle(CheckupTheme.ink)
                    .multilineTextAlignment(.center)
                Text("Dès que le paiement est validé, revenez sur l’application : votre rendez-vous s’y confirme automatiquement. Si vous fermez l’application, la réservation ne pourra pas être confirmée.")
                    .font(.subheadline)
                    .foregroundStyle(CheckupTheme.muted)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 8)

            Button {
                step = .paying
            } label: {
                Text("Continuer vers le paiement sécurisé")
                    .font(.headline)
                    .frame(maxWidth: .infinity, minHeight: 54)
            }
            .buttonStyle(.borderedProminent)
            .tint(CheckupTheme.accent)
            .accessibilityIdentifier("booking-payment-continue")

            Button("Annuler", action: onClose)
                .font(.subheadline)
                .tint(CheckupTheme.accent)
                .padding(.bottom, 6)
        }
        .frame(maxWidth: 460)
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(CheckupTheme.paper.ignoresSafeArea())
        .accessibilityIdentifier("booking-payment-warning")
        .onAppear {
            guard !reduceMotion else {
                pulse = 1
                return
            }
            withAnimation(.easeInOut(duration: 0.55).repeatForever(autoreverses: true)) {
                pulse = 0.1
            }
        }
    }
}
