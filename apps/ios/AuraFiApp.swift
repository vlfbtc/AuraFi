import SwiftUI

@main
struct AuraFiApp: App {
    @StateObject private var appModel = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(appModel)
        }
    }
}

enum AppFlow {
    case welcome
    case login
    case otp
    case riskQuiz
    case dashboard
}

enum MainTab: Hashable {
    case dashboard
    case aura
    case simulation
    case protocols
    case history
}

enum RiskProfile: String, CaseIterable, Identifiable, Codable {
    case conservative
    case moderate
    case aggressive

    var id: String { rawValue }

    var title: String {
        switch self {
        case .conservative: return "Conservador"
        case .moderate: return "Moderado"
        case .aggressive: return "Arrojado"
        }
    }

    var description: String {
        switch self {
        case .conservative:
            return "Prefiro priorizar estabilidade e aceitar menos variação."
        case .moderate:
            return "Aceito alguma variação para buscar mais possibilidades."
        case .aggressive:
            return "Aceito maior variação e riscos mais elevados."
        }
    }
}

@MainActor
final class AppModel: ObservableObject {
    let apiClient: AuraFiAPIClient
    private let sessionStore: SessionStore
    private let localStore: AppLocalStore

    @Published var flow: AppFlow = .welcome
    @Published var email = ""
    @Published var otpCode = ""
    @Published var otpChallenge: OTPChallenge?
    @Published var session: AuthSession?
    @Published var declaredProfile: RiskProfile?
    @Published var opportunities: [Opportunity] = []
    @Published var marketSource: APIDataSource?
    @Published var lastSimulation: Simulation?
    @Published var selectedTab: MainTab = .dashboard
    @Published var conversation: ConversationRecord?
    @Published var conversationMessages: [ConversationMessage] = []
    @Published var conversationConsent: ConversationConsent?
    @Published var decisions: [DecisionRecord]
    @Published var isUsingCachedMarket = false
    @Published var isSendingMessage = false
    @Published var auraFallbackMessage: String?
    @Published var isLoading = false
    @Published var errorMessage: String?
    @Published var deliveryMessage: String?
    private var didAttemptSessionRestore = false

    #if DEBUG
    private let previewOpportunities: [Opportunity]?
    #endif

    init(
        apiClient: AuraFiAPIClient = AuraFiAPIClient(),
        sessionStore: SessionStore = SessionStore(),
        localStore: AppLocalStore = AppLocalStore()
    ) {
        self.apiClient = apiClient
        self.sessionStore = sessionStore
        self.localStore = localStore
        self.decisions = localStore.loadDecisions()
        self.opportunities = localStore.loadOpportunities()
        self.marketSource = self.opportunities.first?.dataSource
        if let stored = sessionStore.load() {
            self.session = stored
            self.email = stored.email
            self.flow = .dashboard
        }
        #if DEBUG
        self.previewOpportunities = nil
        #endif
    }

    #if DEBUG
    init(previewOpportunities: [Opportunity]) {
        self.apiClient = AuraFiAPIClient(baseURL: nil)
        self.sessionStore = SessionStore()
        self.localStore = AppLocalStore()
        self.decisions = []
        self.previewOpportunities = previewOpportunities
    }
    #endif

    func requestOTP(for email: String) async {
        await perform { [self] in
            let normalizedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
            let challenge = try await apiClient.requestOTP(email: normalizedEmail)
            self.email = normalizedEmail
            self.otpChallenge = challenge
            self.otpCode = ""
            self.deliveryMessage = challenge.delivery == "email"
                ? "Enviamos um código para confirmar seu acesso."
                : "O serviço aceitou a solicitação. Confirme o código no ambiente configurado."
            self.flow = .otp
        }
    }

    func verifyOTP() async {
        guard let challenge = otpChallenge else {
            errorMessage = "Solicite um novo código para continuar."
            return
        }

        await perform { [self] in
            let authenticatedSession = try await apiClient.verifyOTP(
                challengeId: challenge.challengeId,
                otp: otpCode.trimmingCharacters(in: .whitespacesAndNewlines)
            )
            self.session = authenticatedSession
            try sessionStore.save(authenticatedSession)
            let profile = try await apiClient.getProfile(sessionToken: authenticatedSession.accessToken)
            if let declared = profile.riskProfile?.declaredProfile {
                self.declaredProfile = declared
                self.flow = .dashboard
            } else {
                self.flow = .riskQuiz
            }
        }
    }

    func declare(profile: RiskProfile, answers: [APIAnswer]) async {
        guard let session else {
            errorMessage = "Confirme seu acesso antes de declarar um perfil."
            flow = .welcome
            return
        }

        await perform { [self] in
            _ = try await apiClient.setRiskProfile(
                sessionToken: session.accessToken,
                profile: profile,
                answers: answers
            )
            self.declaredProfile = profile
            self.flow = .dashboard
        }
    }

    func loadOpportunities() async {
        #if DEBUG
        if let previewOpportunities {
            opportunities = previewOpportunities
            marketSource = previewOpportunities.first?.dataSource
            return
        }
        #endif

        guard let session else {
            errorMessage = "Confirme seu acesso antes de carregar as oportunidades."
            return
        }

        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let response = try await apiClient.listOpportunities(sessionToken: session.accessToken)
            self.opportunities = response.items
            self.marketSource = response.meta?.dataSources?.first ?? response.items.first?.dataSource
            self.isUsingCachedMarket = false
            self.localStore.saveOpportunities(response.items)
        } catch {
            if opportunities.isEmpty {
                errorMessage = (error as? LocalizedError)?.errorDescription ?? "Não foi possível atualizar as oportunidades."
            } else {
                isUsingCachedMarket = true
                errorMessage = "Sem conexão agora. Mostramos a última leitura salva neste aparelho."
            }
        }
    }

    func restoreSessionIfNeeded() async {
        guard !didAttemptSessionRestore else { return }
        didAttemptSessionRestore = true
        guard let session else { return }
        do {
            let profile = try await apiClient.getProfile(sessionToken: session.accessToken)
            declaredProfile = profile.riskProfile?.declaredProfile
            await loadOpportunities()
        } catch AuraFiAPIError.server(let status, _, _) where status == 401 {
            do {
                let refreshed = try await apiClient.refreshSession(refreshToken: session.refreshToken)
                self.session = refreshed
                self.email = refreshed.email
                try sessionStore.save(refreshed)
                let profile = try await apiClient.getProfile(sessionToken: refreshed.accessToken)
                declaredProfile = profile.riskProfile?.declaredProfile
                await loadOpportunities()
            } catch {
                restart()
                errorMessage = "Sua sessão expirou. Entre novamente para continuar."
            }
        } catch {
            isUsingCachedMarket = !opportunities.isEmpty
            errorMessage = "O serviço está temporariamente indisponível. Você ainda pode consultar os dados salvos."
        }
    }

    func createSimulation(for opportunity: Opportunity, amount: Double = 1000) async {
        #if DEBUG
        if previewOpportunities != nil {
            return
        }
        #endif

        guard let session else {
            errorMessage = "Confirme seu acesso antes de simular um cenário."
            return
        }

        await perform { [self] in
            self.lastSimulation = try await apiClient.createSimulation(
                sessionToken: session.accessToken,
                input: SimulationInput(
                    opportunityId: opportunity.opportunityId,
                    amount: amount,
                    asset: opportunity.asset,
                    horizonsDays: [30, 180, 365],
                    compareIdleStablecoin: true
                )
            )
        }
    }

    func grantConversationConsent() async {
        conversationConsent = .granted()
        await ensureConversation()
    }

    func ensureConversation() async {
        guard conversation == nil, let session, let consent = conversationConsent else { return }
        isSendingMessage = true
        auraFallbackMessage = nil
        defer { isSendingMessage = false }
        do {
            let created = try await apiClient.createConversation(
                sessionToken: session.accessToken,
                consent: consent
            )
            conversation = created
            conversationMessages = created.messages
        } catch {
            auraFallbackMessage = (error as? LocalizedError)?.errorDescription
                ?? "A Aura está em manutenção rápida. Tente novamente em instantes."
        }
    }

    func sendMessageToAura(_ text: String) async {
        let normalized = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty, normalized.count <= 4000,
              let session, let consent = conversationConsent
        else { return }
        if conversation == nil { await ensureConversation() }
        guard let conversation else { return }
        isSendingMessage = true
        auraFallbackMessage = nil
        defer { isSendingMessage = false }
        do {
            let response = try await apiClient.sendConversationMessage(
                sessionToken: session.accessToken,
                conversationId: conversation.conversationId,
                text: normalized,
                consent: consent
            )
            conversationMessages.append(response.userMessage)
            conversationMessages.append(response.assistantMessage)
            if response.assistantMessage.payload.fallbackUsed == true {
                auraFallbackMessage = "A IA está indisponível; a resposta segura da FAQ foi usada."
            }
        } catch {
            auraFallbackMessage = (error as? LocalizedError)?.errorDescription
                ?? "Não foi possível conversar com a Aura agora."
        }
    }

    func recordDecision(for opportunity: Opportunity, amount: Double, outcome: DecisionRecord.Outcome) {
        let projectedYield = lastSimulation?.scenarios.max(by: { $0.horizonDays < $1.horizonDays })?.projectedYield ?? 0
        let record = DecisionRecord(
            id: UUID(),
            opportunityId: opportunity.opportunityId,
            protocolName: opportunity.protocolName,
            asset: opportunity.asset,
            blockchain: opportunity.blockchain,
            amount: amount,
            projectedYield: projectedYield,
            createdAt: Date(),
            outcome: outcome
        )
        decisions.insert(record, at: 0)
        localStore.saveDecisions(decisions)
    }

    func logout() async {
        if let session { try? await apiClient.logout(sessionToken: session.accessToken) }
        restart()
    }

    func clearError() {
        errorMessage = nil
    }

    func restart() {
        sessionStore.clear()
        didAttemptSessionRestore = false
        email = ""
        otpCode = ""
        otpChallenge = nil
        session = nil
        declaredProfile = nil
        opportunities = []
        marketSource = nil
        lastSimulation = nil
        selectedTab = .dashboard
        conversation = nil
        conversationMessages = []
        conversationConsent = nil
        auraFallbackMessage = nil
        isUsingCachedMarket = false
        deliveryMessage = nil
        errorMessage = nil
        flow = .welcome
    }

    func deleteLocalData() async {
        decisions = []
        localStore.saveDecisions([])
        await logout()
    }

    private func perform(_ operation: @escaping @MainActor () async throws -> Void) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            try await operation()
        } catch {
            errorMessage = (error as? LocalizedError)?.errorDescription ?? "Não foi possível concluir a operação."
        }
    }
}

struct RootView: View {
    @EnvironmentObject private var appModel: AppModel

    var body: some View {
        Group {
            switch appModel.flow {
            case .welcome, .login, .otp, .riskQuiz:
                OnboardingView()
            case .dashboard:
                DashboardView()
            }
        }
        .tint(AuraTheme.pink)
        .preferredColorScheme(.light)
    }
}

enum AuraTheme {
    static let pink = Color(red: 0.82, green: 0.08, blue: 0.40)
    static let pinkBright = Color(red: 0.94, green: 0.20, blue: 0.55)
    static let purple = Color(red: 0.09, green: 0.03, blue: 0.16)
    static let purpleSoft = Color(red: 0.20, green: 0.07, blue: 0.30)
    static let lavender = Color(red: 0.98, green: 0.96, blue: 1.00)
    static let border = Color(red: 0.82, green: 0.76, blue: 0.88)
    static let success = Color(red: 0.00, green: 0.62, blue: 0.29)
}

struct AuraPrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: 54)
            .background(AuraTheme.pink.opacity(configuration.isPressed ? 0.78 : 1), in: Capsule())
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
    }
}

struct DataSourceBanner: View {
    let source: APIDataSource

    var body: some View {
        Label {
            VStack(alignment: .leading, spacing: 4) {
                Text("\(source.statusLabel) · \(source.sourceLabel)")
                    .font(.subheadline.weight(.semibold))
                Text(source.statusDescription)
                    .font(.footnote)
                    .fixedSize(horizontal: false, vertical: true)
            }
        } icon: {
            Image(systemName: source.isStale ? "clock.badge.exclamationmark" : "checkmark.shield")
                .imageScale(.large)
        }
        .foregroundStyle(source.isStale ? .orange : .secondary)
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background((source.isStale ? Color.orange : Color.secondary).opacity(0.12), in: RoundedRectangle(cornerRadius: 14))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(source.statusLabel), fonte \(source.sourceLabel). \(source.statusDescription)")
    }
}

struct ErrorCard: View {
    let message: String
    let retry: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Não foi possível atualizar", systemImage: "wifi.exclamationmark")
                .font(.headline)
            Text(message)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Button("Tentar novamente", action: retry)
                .buttonStyle(.borderedProminent)
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 16))
    }
}

struct DisclaimerCard: View {
    var body: some View {
        Label {
            Text("A AuraFi oferece apoio à decisão. Não é recomendação personalizada, não garante retorno e não movimenta recursos.")
                .font(.footnote)
                .fixedSize(horizontal: false, vertical: true)
        } icon: {
            Image(systemName: "info.circle")
        }
        .foregroundStyle(.secondary)
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.secondary.opacity(0.10), in: RoundedRectangle(cornerRadius: 14))
        .accessibilityElement(children: .combine)
    }
}

#if DEBUG
enum PreviewData {
    static let source = APIDataSource(
        source: "defillama",
        mode: "live",
        observedAt: "2026-08-02T10:00:00-03:00",
        retrievedAt: "2026-08-02T10:00:05-03:00",
        cacheExpiresAt: nil,
        readOnly: true,
        isStale: false,
        freshnessNote: nil
    )

    static let opportunities: [Opportunity] = [
        Opportunity(
            opportunityId: "preview-aave-usdc",
            protocolName: "Aave",
            pool: "USDC Supply",
            asset: "USDC",
            blockchain: "Base",
            apy: APIMarketValue(value: 5.2, unit: "percent_annualized", currency: nil, observedAt: source.observedAt),
            tvl: APIMarketValue(value: 1200000000, unit: nil, currency: "USD", observedAt: source.observedAt),
            liquidity: APILiquidity(level: "high", observedAt: source.observedAt),
            auditStatus: "audited",
            risk: APIRisk(score: 9.2, level: "medium", dimensions: ["contrato", "liquidez"]),
            dataSource: source,
            disclaimer: "Dados informativos de mercado; não constituem recomendação personalizada."
        )
    ]
}
#endif
