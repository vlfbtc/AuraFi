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
    case explore
    case history
}

enum OTPFailureKind: Equatable {
    case invalid
    case expired
    case invalidOrExpired
    case tooManyAttempts
    case emailDelivery
    case connection
    case service
}

enum OTPPhase {
    case request
    case verification
}

struct OTPErrorPresentation: Equatable {
    let kind: OTPFailureKind
    let title: String
    let message: String
    let systemImage: String
    let actionTitle: String?

    static func make(for error: Error, phase: OTPPhase) -> OTPErrorPresentation {
        if case AuraFiAPIError.transport = error {
            return OTPErrorPresentation(
                kind: .connection,
                title: "Sem conexão com o serviço",
                message: "Confira sua conexão e tente novamente. Seu código não foi invalidado.",
                systemImage: "wifi.exclamationmark",
                actionTitle: "Tentar novamente"
            )
        }

        if case let AuraFiAPIError.server(status, rawCode, _) = error {
            let code = rawCode.uppercased()
            if ["OTP_INVALID", "INVALID_OTP", "OTP_CODE_INVALID"].contains(code) {
                return OTPErrorPresentation(
                    kind: .invalid,
                    title: "Código incorreto",
                    message: "Os seis dígitos não conferem. Revise o código que enviamos e tente de novo.",
                    systemImage: "lock.trianglebadge.exclamationmark",
                    actionTitle: "Conferir código"
                )
            }
            if ["OTP_EXPIRED", "EXPIRED_OTP", "OTP_CODE_EXPIRED"].contains(code) {
                return OTPErrorPresentation(
                    kind: .expired,
                    title: "Código expirado",
                    message: "Esse código venceu. Solicite outro para continuar.",
                    systemImage: "clock.badge.exclamationmark",
                    actionTitle: "Enviar novo código"
                )
            }
            if status == 429 || ["RATE_LIMITED", "OTP_ATTEMPTS_EXCEEDED", "OTP_MAX_ATTEMPTS"].contains(code) {
                return OTPErrorPresentation(
                    kind: .tooManyAttempts,
                    title: "Muitas tentativas",
                    message: "Aguarde alguns minutos antes de tentar novamente.",
                    systemImage: "hourglass",
                    actionTitle: nil
                )
            }
            if code == "OTP_DELIVERY_UNAVAILABLE" {
                return OTPErrorPresentation(
                    kind: .emailDelivery,
                    title: "E-mail temporariamente indisponível",
                    message: "O servidor de envio não conseguiu entregar o código. Tente solicitar novamente em instantes.",
                    systemImage: "envelope.badge.exclamationmark",
                    actionTitle: "Reenviar código"
                )
            }
            if code == "AUTHENTICATION_FAILED" {
                return OTPErrorPresentation(
                    kind: .invalidOrExpired,
                    title: "Código incorreto ou expirado",
                    message: "Não conseguimos confirmar este código. Revise os seis dígitos e tente de novo, ou solicite um novo código.",
                    systemImage: "lock.trianglebadge.exclamationmark",
                    actionTitle: "Conferir código"
                )
            }
        }

        return OTPErrorPresentation(
            kind: .service,
            title: "Serviço temporariamente indisponível",
            message: phase == .request
                ? "Não foi possível solicitar o código agora. Tente novamente em instantes."
                : "Não foi possível confirmar o código agora. Tente novamente em instantes.",
            systemImage: "exclamationmark.triangle",
            actionTitle: "Tentar novamente"
        )
    }
}

enum MarketRefreshFeedback: Equatable {
    case refreshing
    case updated
    case cached

    var label: String {
        switch self {
        case .refreshing: return "Atualizando dados…"
        case .updated: return "Dados atualizados"
        case .cached: return "Exibindo última leitura salva"
        }
    }

    var systemImage: String {
        switch self {
        case .refreshing: return "arrow.clockwise"
        case .updated: return "checkmark.circle.fill"
        case .cached: return "wifi.slash"
        }
    }
}

enum ChatDeliveryState: String, Codable, Equatable {
    case sending
    case sent
    case delivered
    case failed
    case received
}

struct ChatDisplayMessage: Identifiable, Codable, Equatable {
    let id: String
    var serverMessageId: String?
    let text: String
    let isFromUser: Bool
    let isFallback: Bool
    var deliveryState: ChatDeliveryState

    init(serverMessage: ConversationMessage) {
        id = serverMessage.messageId
        serverMessageId = serverMessage.messageId
        text = serverMessage.payload.text ?? ""
        isFromUser = serverMessage.isFromUser
        isFallback = serverMessage.payload.fallbackUsed == true
        deliveryState = serverMessage.isFromUser ? .delivered : .received
    }

    init(optimisticText: String) {
        id = UUID().uuidString
        serverMessageId = nil
        text = optimisticText
        isFromUser = true
        isFallback = false
        deliveryState = .sent
    }

    init(pendingId: String, text: String) {
        id = pendingId
        serverMessageId = nil
        self.text = text
        isFromUser = true
        isFallback = false
        deliveryState = .failed
    }
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
    private let chatStore: ChatStateStore
    private let biometrics: BiometricAuthenticating
    private let biometricPreference: BiometricPreferenceStore

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
    @Published var conversationMessages: [ChatDisplayMessage] = []
    @Published var conversationConsent: ConversationConsent?
    @Published var decisions: [DecisionRecord]
    @Published var isUsingCachedMarket = false
    @Published var isRefreshingMarket = false
    @Published var marketRefreshFeedback: MarketRefreshFeedback?
    @Published var isSendingMessage = false
    @Published var auraFallbackMessage: String?
    @Published var isLoading = false
    @Published var errorMessage: String?
    @Published var deliveryMessage: String?
    @Published var otpError: OTPErrorPresentation?
    @Published var isLocked = false
    @Published var biometricLockEnabled = false
    private var didAttemptSessionRestore = false
    private var resumedConversationId: String?

    #if DEBUG
    private let previewOpportunities: [Opportunity]?
    #endif

    init(
        apiClient: AuraFiAPIClient = AuraFiAPIClient(),
        sessionStore: SessionStore = SessionStore(),
        localStore: AppLocalStore = AppLocalStore(),
        chatStore: ChatStateStore = ChatStateStore(),
        biometrics: BiometricAuthenticating = SystemBiometricAuthenticator(),
        biometricPreference: BiometricPreferenceStore = BiometricPreferenceStore()
    ) {
        self.apiClient = apiClient
        self.sessionStore = sessionStore
        self.localStore = localStore
        self.chatStore = chatStore
        self.biometrics = biometrics
        self.biometricPreference = biometricPreference
        self.decisions = localStore.loadDecisions()
        self.opportunities = localStore.loadOpportunities()
        self.marketSource = self.opportunities.first?.dataSource
        self.biometricLockEnabled = biometricPreference.isEnabled()
        if let stored = sessionStore.load() {
            self.session = stored
            self.email = stored.email
            self.flow = .dashboard
            if self.biometricLockEnabled, biometrics.availableBiometry != .none {
                self.isLocked = true
            }
        }
        if let chat = chatStore.load() {
            self.resumedConversationId = chat.conversationId
            self.conversationConsent = chat.consent
            self.conversationMessages = chat.pendingMessages.map {
                ChatDisplayMessage(pendingId: $0.id, text: $0.text)
            }
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
        self.chatStore = ChatStateStore()
        self.biometrics = SystemBiometricAuthenticator()
        self.biometricPreference = BiometricPreferenceStore()
        self.decisions = []
        self.previewOpportunities = previewOpportunities
    }
    #endif

    func requestOTP(for email: String) async {
        isLoading = true
        errorMessage = nil
        otpError = nil
        defer { isLoading = false }
        do {
            let normalizedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
            let challenge = try await apiClient.requestOTP(email: normalizedEmail)
            self.email = normalizedEmail
            self.otpChallenge = challenge
            self.otpCode = ""
            self.deliveryMessage = challenge.delivery == "email"
                ? "Enviamos um código para confirmar seu acesso."
                : "O serviço aceitou a solicitação. Confirme o código no ambiente configurado."
            self.flow = .otp
        } catch {
            otpError = .make(for: error, phase: .request)
        }
    }

    func verifyOTP() async {
        guard let challenge = otpChallenge else {
            otpError = OTPErrorPresentation(
                kind: .expired,
                title: "Solicite um novo código",
                message: "Este acesso não tem mais um código ativo.",
                systemImage: "clock.badge.exclamationmark",
                actionTitle: "Enviar novo código"
            )
            return
        }

        isLoading = true
        errorMessage = nil
        otpError = nil
        defer { isLoading = false }
        do {
            let authenticatedSession = try await apiClient.verifyOTP(
                challengeId: challenge.challengeId,
                otp: otpCode.trimmingCharacters(in: .whitespacesAndNewlines)
            )
            self.session = authenticatedSession
            try sessionStore.save(authenticatedSession)
            do {
                let profile = try await apiClient.getProfile(sessionToken: authenticatedSession.accessToken)
                if let declared = profile.riskProfile?.declaredProfile {
                    self.declaredProfile = declared
                    self.flow = .dashboard
                } else {
                    self.flow = .riskQuiz
                }
            } catch {
                self.flow = .dashboard
            }
        } catch {
            otpError = .make(for: error, phase: .verification)
        }
    }

    func clearOTPError() {
        otpError = nil
    }


    var biometricKind: BiometricKind { biometrics.availableBiometry }
    var biometricsAvailable: Bool { biometrics.availableBiometry != .none }

    func lockIfNeeded() {
        guard session != nil, biometricLockEnabled, biometricsAvailable else { return }
        isLocked = true
    }

    func unlock() async {
        guard isLocked else { return }
        let result = await biometrics.authenticate(reason: "Desbloqueie o AuraFi para acessar sua conta.")
        switch result {
        case .success:
            isLocked = false
        case .failure(.unavailable):
            isLocked = false
        case .failure(.cancelled), .failure(.failed):
            break
        }
    }

    func setBiometricLock(_ enabled: Bool) {
        biometricLockEnabled = enabled
        biometricPreference.setEnabled(enabled)
        if !enabled { isLocked = false }
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

        isRefreshingMarket = true
        marketRefreshFeedback = .refreshing
        if opportunities.isEmpty { isLoading = true }
        defer {
            isRefreshingMarket = false
            isLoading = false
        }
        do {
            let response = try await apiClient.listOpportunities(sessionToken: session.accessToken)
            self.opportunities = response.items
            self.marketSource = response.meta?.dataSources?.first ?? response.items.first?.dataSource
            self.isUsingCachedMarket = false
            self.errorMessage = nil
            self.marketRefreshFeedback = .updated
            self.localStore.saveOpportunities(response.items)
        } catch {
            if opportunities.isEmpty {
                errorMessage = (error as? LocalizedError)?.errorDescription ?? "Não foi possível atualizar as oportunidades."
                marketRefreshFeedback = nil
            } else {
                isUsingCachedMarket = true
                errorMessage = nil
                marketRefreshFeedback = .cached
            }
        }
    }

    func refreshOpportunities() async {
        async let minimumDuration: Void = minimumRefreshDuration()
        await loadOpportunities()
        await minimumDuration
    }

    func opportunityDetail(for opportunityId: String) async throws -> Opportunity {
        guard let session else {
            throw AuraFiAPIError.server(
                status: 401,
                code: "AUTHENTICATION_REQUIRED",
                message: "Entre novamente para consultar os detalhes."
            )
        }
        return try await apiClient.getOpportunity(
            sessionToken: session.accessToken,
            opportunityId: opportunityId
        ).opportunity
    }

    private func minimumRefreshDuration() async {
        try? await Task.sleep(nanoseconds: 1_200_000_000)
    }

    func restoreSessionIfNeeded() async {
        guard !didAttemptSessionRestore else { return }
        didAttemptSessionRestore = true
        guard let session else { return }
        do {
            let profile = try await apiClient.getProfile(sessionToken: session.accessToken)
            declaredProfile = profile.riskProfile?.declaredProfile
            await restoreConversation(sessionToken: session.accessToken)
            await loadOpportunities()
        } catch AuraFiAPIError.server(let status, _, _) where status == 401 {
            do {
                let refreshed = try await apiClient.refreshSession(refreshToken: session.refreshToken)
                self.session = refreshed
                self.email = refreshed.email
                try sessionStore.save(refreshed)
                let profile = try await apiClient.getProfile(sessionToken: refreshed.accessToken)
                declaredProfile = profile.riskProfile?.declaredProfile
                await restoreConversation(sessionToken: refreshed.accessToken)
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
        persistChatState()
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
            resumedConversationId = created.conversationId
            let localPending = conversationMessages.filter { $0.serverMessageId == nil }
            conversationMessages = created.messages.map(ChatDisplayMessage.init(serverMessage:)) + localPending
            persistChatState()
        } catch {
            auraFallbackMessage = (error as? LocalizedError)?.errorDescription
                ?? "A Aura está em manutenção rápida. Tente novamente em instantes."
        }
    }

    func sendMessageToAura(_ text: String) async {
        let normalized = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty, normalized.count <= 4000,
              conversationConsent != nil,
              !isSendingMessage
        else { return }

        let optimistic = ChatDisplayMessage(optimisticText: normalized)
        conversationMessages.append(optimistic)
        persistChatState()
        await deliverMessage(id: optimistic.id)
    }

    func retryMessage(id: String) async {
        guard !isSendingMessage,
              let index = conversationMessages.firstIndex(where: { $0.id == id }),
              conversationMessages[index].isFromUser,
              conversationMessages[index].deliveryState == .failed
        else { return }
        conversationMessages[index].deliveryState = .sent
        await deliverMessage(id: id)
    }

    private func deliverMessage(id: String) async {
        guard let index = conversationMessages.firstIndex(where: { $0.id == id }),
              let session,
              let consent = conversationConsent
        else { return }
        let normalized = conversationMessages[index].text
        auraFallbackMessage = nil
        if conversation == nil { await ensureConversation() }
        guard let conversation else {
            auraFallbackMessage = nil
            markMessageFailed(id: id)
            persistChatState()
            return
        }
        isSendingMessage = true
        defer { isSendingMessage = false }
        do {
            let response = try await apiClient.sendConversationMessage(
                sessionToken: session.accessToken,
                conversationId: conversation.conversationId,
                text: normalized,
                consent: consent,
                externalMessageId: id
            )
            if let sentIndex = conversationMessages.firstIndex(where: { $0.id == id }) {
                conversationMessages[sentIndex].serverMessageId = response.userMessage.messageId
                conversationMessages[sentIndex].deliveryState = .delivered
            }
            if !conversationMessages.contains(where: { $0.serverMessageId == response.assistantMessage.messageId }) {
                conversationMessages.append(ChatDisplayMessage(serverMessage: response.assistantMessage))
            }
            if response.assistantMessage.payload.fallbackUsed == true {
                let status = response.assistantMessage.payload.llm?.serviceStatus
                auraFallbackMessage = status == "unavailable"
                    ? "A IA está indisponível; uma resposta educativa segura foi usada."
                    : "A Aura usou uma resposta segura adequada a este pedido."
            }
            persistChatState()
        } catch {
            auraFallbackMessage = nil
            markMessageFailed(id: id)
            persistChatState()
        }
    }

    private func markMessageFailed(id: String) {
        guard let index = conversationMessages.firstIndex(where: { $0.id == id }) else { return }
        conversationMessages[index].deliveryState = .failed
    }

    private func restoreConversation(sessionToken: String) async {
        guard conversation == nil, let conversationId = resumedConversationId else { return }
        do {
            let restored = try await apiClient.getConversation(
                sessionToken: sessionToken,
                conversationId: conversationId
            )
            let deliveredExternalIds = Set(restored.messages.compactMap { $0.channel?.externalMessageId })
            let stillPending = conversationMessages.filter {
                $0.serverMessageId == nil && !deliveredExternalIds.contains($0.id)
            }
            conversation = restored
            conversationMessages = restored.messages.map(ChatDisplayMessage.init(serverMessage:)) + stillPending
            persistChatState()
        } catch AuraFiAPIError.server(let status, _, _) where status == 404 {
            resumedConversationId = nil
            conversation = nil
            persistChatState()
        } catch {
            auraFallbackMessage = "Não foi possível retomar a conversa agora. Suas mensagens pendentes continuam neste aparelho."
        }
    }

    private func persistChatState() {
        guard let consent = conversationConsent else {
            chatStore.clear()
            return
        }
        let pending = conversationMessages
            .filter { $0.isFromUser && $0.serverMessageId == nil }
            .map { PendingChatMessage(id: $0.id, text: $0.text) }
        try? chatStore.save(PersistedChatState(
            conversationId: conversation?.conversationId ?? resumedConversationId,
            consent: consent,
            pendingMessages: pending
        ))
    }

    func recordDecision(for opportunity: Opportunity, amount: Double, outcome: DecisionRecord.Outcome) {
        let longestScenario = lastSimulation?.scenarios.max(by: { $0.horizonDays < $1.horizonDays })
        let projectedYield = longestScenario?.projectedGain
            ?? longestScenario.map { $0.projectedValue - amount }
            ?? 0
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
        chatStore.clear()
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
        resumedConversationId = nil
        auraFallbackMessage = nil
        isUsingCachedMarket = false
        isRefreshingMarket = false
        marketRefreshFeedback = nil
        deliveryMessage = nil
        otpError = nil
        errorMessage = nil
        isLocked = false
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
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        ZStack {
            Group {
                switch appModel.flow {
                case .welcome, .login, .otp, .riskQuiz:
                    OnboardingView()
                case .dashboard:
                    DashboardView()
                }
            }

            if appModel.flow == .dashboard && appModel.isLocked {
                BiometricLockView()
                    .transition(.opacity)
            }
        }
        .animation(.easeInOut(duration: 0.2), value: appModel.isLocked)
        .tint(AuraTheme.pink)
        .preferredColorScheme(.light)
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .background { appModel.lockIfNeeded() }
        }
    }
}

struct BiometricLockView: View {
    @EnvironmentObject private var appModel: AppModel

    var body: some View {
        ZStack {
            AuraTheme.lavender.ignoresSafeArea()
            VStack(spacing: 18) {
                Spacer()
                AuraMark(size: 76)
                Text("AuraFi protegido")
                    .font(.system(size: 28, weight: .bold, design: .rounded))
                    .foregroundStyle(AuraTheme.purple)
                Text("Use o \(appModel.biometricKind.label) para desbloquear e acessar sua conta.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
                Spacer()
                Button {
                    Task { await appModel.unlock() }
                } label: {
                    Label("Desbloquear com \(appModel.biometricKind.label)", systemImage: appModel.biometricKind.systemImage)
                }
                .buttonStyle(AuraPrimaryButtonStyle())
                .padding(.horizontal, 28)
                Button("Sair da conta") {
                    Task { await appModel.logout() }
                }
                .padding(.bottom, 24)
            }
        }
        .task { await appModel.unlock() }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("AuraFi bloqueado. Use \(appModel.biometricKind.label) para desbloquear.")
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

    @ViewBuilder
    var body: some View {
        if isUseful {
            HStack(spacing: 6) {
                Image(systemName: source.isStale ? "clock.badge.exclamationmark" : "checkmark.shield")
                Text("Fonte: \(source.usefulSourceLabel ?? "")")
                if source.isStale || source.mode == "cache" {
                    Text("·")
                    Text(source.statusLabel)
                }
            }
            .font(.caption)
            .foregroundStyle(source.isStale ? .orange : .secondary)
            .padding(.horizontal, 10)
            .frame(minHeight: 32)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.white.opacity(0.68), in: Capsule())
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Fonte \(source.usefulSourceLabel ?? ""). \(source.isStale || source.mode == "cache" ? source.statusLabel : "")")
        }
    }

    private var isUseful: Bool {
        source.usefulSourceLabel != nil
    }
}

struct ErrorCard: View {
    let message: String
    let retry: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Não foi possível concluir", systemImage: "exclamationmark.triangle")
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
        freshnessNote: nil,
        serverSourceLabel: "DeFiLlama",
        serverStatusLabel: "Dados atualizados"
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
