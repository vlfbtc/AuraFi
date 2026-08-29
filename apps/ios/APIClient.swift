import Foundation

enum AuraFiConfiguration {
    static var apiBaseURL: URL? {
        resolveAPIBaseURL(
            environmentValue: ProcessInfo.processInfo.environment["AURAFI_API_BASE_URL"],
            bundleValue: Bundle.main.object(forInfoDictionaryKey: "AURAFI_API_BASE_URL") as? String
        )
    }

    static func resolveAPIBaseURL(environmentValue: String?, bundleValue: String?) -> URL? {
        let environmentValue = environmentValue?.trimmingCharacters(in: .whitespacesAndNewlines)
        if let environmentValue, !environmentValue.isEmpty {
            return validatedAPIBaseURL(from: environmentValue)
        }
        return validatedAPIBaseURL(from: bundleValue)
    }

    static func validatedAPIBaseURL(from configuredValue: String?) -> URL? {
        guard let configuredValue,
              let url = URL(string: configuredValue.trimmingCharacters(in: .whitespacesAndNewlines)),
              let scheme = url.scheme?.lowercased(),
              let host = url.host?.lowercased(),
              url.user == nil,
              url.password == nil,
              url.query == nil,
              url.fragment == nil
        else {
            return nil
        }

        if scheme == "https" { return url }
        #if DEBUG
        if scheme == "http", host == "127.0.0.1" || host == "localhost" { return url }
        #endif
        return nil
    }
}

enum AuraFiAPIError: LocalizedError {
    case configuration
    case invalidParameter(String)
    case invalidResponse
    case transport(Error)
    case server(status: Int, code: String, message: String)
    case decoding(Error)

    var errorDescription: String? {
        switch self {
        case .configuration:
            return "O endereço do serviço ainda não foi configurado."
        case let .invalidParameter(message):
            return message
        case .invalidResponse:
            return "O serviço respondeu em um formato inesperado."
        case .transport:
            return "Não foi possível alcançar o serviço. Verifique sua conexão e tente novamente."
        case let .server(_, _, message):
            return message
        case .decoding:
            return "Não foi possível interpretar os dados recebidos."
        }
    }
}

struct HealthResponse: Decodable {
    let status: String
    let version: String
    let checks: [String: String]
    let meta: APIMeta?
}

struct APIDataSource: Codable, Equatable {
    let source: String
    let mode: String
    let observedAt: String
    let retrievedAt: String
    let cacheExpiresAt: String?
    let readOnly: Bool
    let isStale: Bool
    let freshnessNote: String?
    let serverSourceLabel: String?
    let serverStatusLabel: String?

    enum CodingKeys: String, CodingKey {
        case source
        case mode
        case observedAt = "observed_at"
        case retrievedAt = "retrieved_at"
        case cacheExpiresAt = "cache_expires_at"
        case readOnly = "read_only"
        case isStale = "is_stale"
        case freshnessNote = "freshness_note"
        case serverSourceLabel = "source_label"
        case serverStatusLabel = "status_label"
    }

    var sourceLabel: String {
        usefulSourceLabel ?? "Indisponível"
    }

    var usefulSourceLabel: String? {
        if let label = serverSourceLabel?.trimmingCharacters(in: .whitespacesAndNewlines),
           !label.isEmpty {
            return label
        }
        let normalized = source.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty else { return nil }
        return normalized.caseInsensitiveCompare("defillama") == .orderedSame ? "DeFiLlama" : normalized
    }

    var statusLabel: String {
        if let label = serverStatusLabel?.trimmingCharacters(in: .whitespacesAndNewlines),
           !label.isEmpty {
            return label
        }
        if isStale { return "Atualização pendente" }
        switch mode {
        case "live": return "Dados atualizados"
        case "cache": return "Última leitura disponível"
        default: return "Conteúdo de prévia"
        }
    }

    var statusDescription: String {
        if let usefulFreshnessNote { return usefulFreshnessNote }
        if isStale { return "Confira o momento da observação antes de tomar qualquer decisão." }
        return "Leitura de mercado com origem e momento informados."
    }

    var usefulFreshnessNote: String? {
        guard let note = freshnessNote?.trimmingCharacters(in: .whitespacesAndNewlines),
              !note.isEmpty
        else { return nil }
        return note
    }
}

struct APIMeta: Decodable {
    let requestId: String?
    let correlationId: String?
    let generatedAt: String?
    let disclaimer: String?
    let dataSources: [APIDataSource]?

    enum CodingKeys: String, CodingKey {
        case requestId = "request_id"
        case correlationId = "correlation_id"
        case generatedAt = "generated_at"
        case disclaimer
        case dataSources = "data_sources"
    }
}

struct OTPChallenge: Decodable {
    let challengeId: String
    let expiresAt: String
    let delivery: String

    enum CodingKeys: String, CodingKey {
        case challengeId = "challenge_id"
        case expiresAt = "expires_at"
        case delivery
    }
}

struct AuthSession: Decodable {
    let accessToken: String
    let refreshToken: String
    let tokenType: String
    let expiresAt: String
    let accountId: String
    let email: String

    private enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case tokenType = "token_type"
        case expiresAt = "expires_at"
        case account
    }

    private struct SessionAccount: Decodable {
        let accountId: String
        let email: String

        enum CodingKeys: String, CodingKey {
            case accountId = "account_id"
            case email
        }
    }

    init(
        accessToken: String,
        refreshToken: String,
        tokenType: String,
        expiresAt: String,
        accountId: String,
        email: String
    ) {
        self.accessToken = accessToken
        self.refreshToken = refreshToken
        self.tokenType = tokenType
        self.expiresAt = expiresAt
        self.accountId = accountId
        self.email = email
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        accessToken = try container.decode(String.self, forKey: .accessToken)
        refreshToken = try container.decode(String.self, forKey: .refreshToken)
        tokenType = try container.decode(String.self, forKey: .tokenType)
        expiresAt = try container.decode(String.self, forKey: .expiresAt)
        let account = try container.decode(SessionAccount.self, forKey: .account)
        accountId = account.accountId
        email = account.email
    }
}

struct AuthResponse: Decodable {
    let session: AuthSession
}

struct Account: Decodable {
    let accountId: String
    let email: String
    let emailVerified: Bool

    enum CodingKeys: String, CodingKey {
        case accountId = "account_id"
        case email
        case emailVerified = "email_verified"
    }
}

struct DeclaredRiskProfile: Decodable {
    let declaredProfile: RiskProfile
    let status: String
    let version: String
    let declaredAt: String
    let source: String

    enum CodingKeys: String, CodingKey {
        case declaredProfile = "declared_profile"
        case status
        case version
        case declaredAt = "declared_at"
        case source
    }
}

struct ProfileResponse: Decodable {
    let account: Account
    let riskProfile: DeclaredRiskProfile?

    enum CodingKeys: String, CodingKey {
        case account
        case riskProfile = "risk_profile"
    }
}

struct APIProfileInput: Encodable {
    let declaredProfile: RiskProfile
    let answers: [APIAnswer]

    enum CodingKeys: String, CodingKey {
        case declaredProfile = "declared_profile"
        case answers
    }
}

struct APIAnswer: Encodable {
    let questionId: String
    let answer: String

    enum CodingKeys: String, CodingKey {
        case questionId = "question_id"
        case answer
    }
}

struct APIMarketValue: Codable {
    let value: Double
    let unit: String?
    let currency: String?
    let observedAt: String
    let display: String?
    let displayCompact: String?

    enum CodingKeys: String, CodingKey {
        case value
        case unit
        case currency
        case observedAt = "observed_at"
        case display
        case displayCompact = "display_compact"
    }

    init(
        value: Double,
        unit: String?,
        currency: String?,
        observedAt: String,
        display: String? = nil,
        displayCompact: String? = nil
    ) {
        self.value = value
        self.unit = unit
        self.currency = currency
        self.observedAt = observedAt
        self.display = display
        self.displayCompact = displayCompact
    }
}

struct APILiquidity: Codable {
    let level: String
    let observedAt: String
    let value: Double?
    let currency: String?

    enum CodingKeys: String, CodingKey {
        case level
        case observedAt = "observed_at"
        case value, currency
    }

    init(level: String, observedAt: String, value: Double? = nil, currency: String? = nil) {
        self.level = level
        self.observedAt = observedAt
        self.value = value
        self.currency = currency
    }
}

struct APIRisk: Codable {
    let score: Double?
    let level: String
    let dimensions: [String]
    let classification: String?

    var isEstimated: Bool { classification == "heuristic" }
}

struct OpportunityHistoryPoint: Codable, Identifiable {
    let observedAt: String
    let apyPercent: Double?
    let tvlUSD: Double?

    var id: String { observedAt }

    enum CodingKeys: String, CodingKey {
        case observedAt = "observed_at"
        case apyPercent = "apy_percent"
        case tvlUSD = "tvl_usd"
    }
}

struct OpportunityAPYWindow: Codable {
    let average: Double?
    let minimum: Double?
    let maximum: Double?
    let first: Double?
    let latest: Double?
    let changePercentagePoints: Double?
    let trend: String?

    enum CodingKeys: String, CodingKey {
        case average, minimum, maximum, first, latest, trend
        case changePercentagePoints = "change_percentage_points"
    }
}

struct OpportunityTVLWindow: Codable {
    let first: Double?
    let latest: Double?
    let change: Double?
    let changePercent: Double?

    enum CodingKeys: String, CodingKey {
        case first, latest, change
        case changePercent = "change_percent"
    }
}

struct OpportunityHistoryWindow: Codable {
    let windowDays: Int
    let pointCount: Int
    let observedFrom: String
    let observedTo: String
    let apy: OpportunityAPYWindow?
    let tvlUSD: OpportunityTVLWindow?

    enum CodingKeys: String, CodingKey {
        case windowDays = "window_days"
        case pointCount = "point_count"
        case observedFrom = "observed_from"
        case observedTo = "observed_to"
        case apy
        case tvlUSD = "tvl_usd"
    }
}

struct OpportunityHistorySource: Codable {
    let source: String?
    let dataset: String?
    let mode: String?
    let observedAt: String?
    let retrievedAt: String?
    let isStale: Bool?
    let freshnessNote: String?
    let serverSourceLabel: String?

    enum CodingKeys: String, CodingKey {
        case source, dataset, mode
        case observedAt = "observed_at"
        case retrievedAt = "retrieved_at"
        case isStale = "is_stale"
        case freshnessNote = "freshness_note"
        case serverSourceLabel = "source_label"
    }
}

struct OpportunityHistory: Codable {
    let status: String
    let points: [OpportunityHistoryPoint]
    let windows: [String: OpportunityHistoryWindow]
    let dataSource: OpportunityHistorySource

    enum CodingKeys: String, CodingKey {
        case status, points, windows
        case dataSource = "data_source"
    }
}

struct CurrencyAmount: Codable {
    let value: Double
    let currency: String
    let display: String?
    let displayCompact: String?

    enum CodingKeys: String, CodingKey {
        case value
        case currency
        case display
        case displayCompact = "display_compact"
    }
}

struct CurrencyFX: Codable {
    let status: String
    let source: String
    let rate: Double?
    let observedAt: String?
    let retrievedAt: String?
    let isStale: Bool?
    let freshnessNote: String?

    enum CodingKeys: String, CodingKey {
        case status, source, rate
        case observedAt = "observed_at"
        case retrievedAt = "retrieved_at"
        case isStale = "is_stale"
        case freshnessNote = "freshness_note"
    }
}

struct OpportunityCurrencyDisplay: Codable {
    let primary: CurrencyAmount
    let secondary: CurrencyAmount?
    let fx: CurrencyFX
}

struct Opportunity: Identifiable, Codable {
    let opportunityId: String
    let protocolName: String
    let pool: String
    let asset: String
    let blockchain: String
    let apy: APIMarketValue
    let tvl: APIMarketValue
    let liquidity: APILiquidity
    let auditStatus: String?
    let risk: APIRisk
    let dataSource: APIDataSource
    let disclaimer: String
    let history: OpportunityHistory?
    let currencyDisplay: OpportunityCurrencyDisplay?

    var id: String { opportunityId }

    enum CodingKeys: String, CodingKey {
        case opportunityId = "opportunity_id"
        case protocolName = "protocol"
        case pool
        case asset
        case blockchain
        case apy
        case tvl
        case liquidity
        case auditStatus = "audit_status"
        case risk
        case dataSource = "data_source"
        case disclaimer
        case history
        case currencyDisplay = "currency_display"
    }

    init(
        opportunityId: String,
        protocolName: String,
        pool: String,
        asset: String,
        blockchain: String,
        apy: APIMarketValue,
        tvl: APIMarketValue,
        liquidity: APILiquidity,
        auditStatus: String?,
        risk: APIRisk,
        dataSource: APIDataSource,
        disclaimer: String,
        history: OpportunityHistory? = nil,
        currencyDisplay: OpportunityCurrencyDisplay? = nil
    ) {
        self.opportunityId = opportunityId
        self.protocolName = protocolName
        self.pool = pool
        self.asset = asset
        self.blockchain = blockchain
        self.apy = apy
        self.tvl = tvl
        self.liquidity = liquidity
        self.auditStatus = auditStatus
        self.risk = risk
        self.dataSource = dataSource
        self.disclaimer = disclaimer
        self.history = history
        self.currencyDisplay = currencyDisplay
    }

    var riskLabel: String {
        switch risk.level {
        case "low": return "Baixo"
        case "medium": return "Médio"
        case "high": return "Alto"
        default: return "Não informado"
        }
    }

    var apyLabel: String {
        apy.display ?? String(format: "%.2f%% a.a.", apy.value)
    }

    var tvlLabel: String {
        tvl.display ?? tvl.primaryMoneyLabel
    }

    var secondaryTVLLabel: String? {
        nil
    }
}

extension APIMarketValue {
    var primaryMoneyLabel: String {
        let code = normalizedCurrency ?? "USD"
        return value.formattedCurrency(code)
    }

    private var normalizedCurrency: String? {
        let normalized = currency?.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        return normalized?.isEmpty == false ? normalized : nil
    }

}

private extension Double {
    func formattedCurrency(_ code: String) -> String {
        formatted(
            .currency(code: code)
                .locale(Locale(identifier: "pt_BR"))
                .precision(.fractionLength(0...2))
        )
    }
}

struct OpportunityListResponse: Decodable {
    let items: [Opportunity]
    let pagination: Pagination
    let meta: APIMeta?
}

struct OpportunityResponse: Decodable {
    let opportunity: Opportunity
    let meta: APIMeta?
}

struct Pagination: Decodable {
    let page: Int
    let pageSize: Int
    let total: Int
    let hasNext: Bool

    enum CodingKeys: String, CodingKey {
        case page
        case pageSize = "page_size"
        case total
        case hasNext = "has_next"
    }
}

enum AlertType: String, Codable {
    case apyChange = "apy_change"
    case riskChange = "risk_change"
    case newOpportunity = "new_opportunity"
    case dataStale = "data_stale"

    var title: String {
        switch self {
        case .apyChange: return "Mudança de APY"
        case .riskChange: return "Mudança de risco"
        case .newOpportunity: return "Nova oportunidade"
        case .dataStale: return "Dado desatualizado"
        }
    }

    var iconName: String {
        switch self {
        case .apyChange: return "chart.line.uptrend.xyaxis"
        case .riskChange: return "exclamationmark.shield"
        case .newOpportunity: return "sparkles"
        case .dataStale: return "clock.badge.exclamationmark"
        }
    }
}

enum AlertStatus: String, Codable {
    case unread
    case read
}

enum AlertSuggestedAction: String, Codable {
    case viewOpportunity = "view_opportunity"
    case simulate
    case askHub = "ask_hub"
    case none
}

struct Alert: Identifiable, Decodable {
    let alertId: String
    let type: AlertType
    let opportunityId: String?
    let title: String
    let message: String
    let status: AlertStatus
    let createdAt: String
    let observedAt: String?
    let dataSource: APIDataSource?
    let suggestedAction: AlertSuggestedAction?
    let disclaimer: String

    var id: String { alertId }

    enum CodingKeys: String, CodingKey {
        case alertId = "alert_id"
        case type
        case opportunityId = "opportunity_id"
        case title
        case message
        case status
        case createdAt = "created_at"
        case observedAt = "observed_at"
        case dataSource = "data_source"
        case suggestedAction = "suggested_action"
        case disclaimer
    }
}

struct AlertListResponse: Decodable {
    let items: [Alert]
    let pagination: Pagination
    let meta: APIMeta?
}

struct AlertResponse: Decodable {
    let alert: Alert
    let meta: APIMeta?
}

struct SimulationInput: Encodable {
    let opportunityId: String
    let amount: Double
    let asset: String
    let horizonsDays: [Int]
    let compareIdleStablecoin: Bool

    enum CodingKeys: String, CodingKey {
        case opportunityId = "opportunity_id"
        case amount
        case asset
        case horizonsDays = "horizons_days"
        case compareIdleStablecoin = "compare_idle_stablecoin"
    }
}

struct SimulationScenario: Decodable, Identifiable {
    let horizonDays: Int
    let projectedValue: Double
    let projectedYield: Double
    let idleStablecoinValue: Double?
    let currency: String
    let projectedGain: Double?
    let projectedValueDisplay: String?
    let projectedYieldDisplay: String?
    let projectedGainDisplay: String?
    let idleStablecoinValueDisplay: String?

    var id: Int { horizonDays }

    enum CodingKeys: String, CodingKey {
        case horizonDays = "horizon_days"
        case projectedValue = "projected_value"
        case projectedYield = "projected_yield"
        case idleStablecoinValue = "idle_stablecoin_value"
        case currency
        case projectedGain = "projected_gain"
        case projectedValueDisplay = "projected_value_display"
        case projectedYieldDisplay = "projected_yield_display"
        case projectedGainDisplay = "projected_gain_display"
        case idleStablecoinValueDisplay = "idle_stablecoin_value_display"
    }
}

struct Simulation: Identifiable, Decodable {
    let simulationId: String
    let opportunityId: String
    let input: SimulationInputResponse
    let scenarios: [SimulationScenario]
    let assumptions: [String]
    let generatedAt: String
    let executionSupported: Bool
    let disclaimer: String
    let dataSource: APIDataSource?

    var id: String { simulationId }

    enum CodingKeys: String, CodingKey {
        case simulationId = "simulation_id"
        case opportunityId = "opportunity_id"
        case input
        case scenarios
        case assumptions
        case generatedAt = "generated_at"
        case executionSupported = "execution_supported"
        case disclaimer
        case dataSource = "data_source"
    }
}

struct SimulationInputResponse: Decodable {
    let opportunityId: String
    let amount: Double
    let asset: String
    let horizonsDays: [Int]
    let compareIdleStablecoin: Bool?
    let amountDisplay: String?

    enum CodingKeys: String, CodingKey {
        case opportunityId = "opportunity_id"
        case amount
        case asset
        case horizonsDays = "horizons_days"
        case compareIdleStablecoin = "compare_idle_stablecoin"
        case amountDisplay = "amount_display"
    }
}

struct ConversationConsent: Codable, Equatable {
    let purpose: String
    let status: String
    let policyVersion: String
    let capturedAt: String
    let memory: Bool
    let analytics: Bool

    enum CodingKeys: String, CodingKey {
        case purpose, status, memory, analytics
        case policyVersion = "policy_version"
        case capturedAt = "captured_at"
    }

    static func granted(now: Date = Date()) -> ConversationConsent {
        ConversationConsent(
            purpose: "conversation",
            status: "granted",
            policyVersion: "privacy-1.0",
            capturedAt: ISO8601DateFormatter().string(from: now),
            memory: false,
            analytics: false
        )
    }
}

struct ConversationMessage: Identifiable, Decodable {
    let messageId: String
    let messageType: String
    let occurredAt: String
    let payload: ConversationPayload
    let channel: ConversationChannel?

    var id: String { messageId }
    var isFromUser: Bool { messageType == "user_message" }

    enum CodingKeys: String, CodingKey {
        case messageId = "message_id"
        case messageType = "message_type"
        case occurredAt = "occurred_at"
        case payload, channel
    }
}

struct ConversationChannel: Decodable {
    let externalMessageId: String?
    enum CodingKeys: String, CodingKey { case externalMessageId = "external_message_id" }
}

struct ConversationLLMStatus: Decodable {
    let serviceStatus: String?
    let failureCode: String?

    enum CodingKeys: String, CodingKey {
        case serviceStatus = "service_status"
        case failureCode = "failure_code"
    }
}

struct ConversationPayload: Decodable {
    let text: String?
    let fallbackUsed: Bool?
    let escalationFlag: Bool?
    let llm: ConversationLLMStatus?

    enum CodingKeys: String, CodingKey {
        case text
        case fallbackUsed = "fallback_used"
        case escalationFlag = "escalation_flag"
        case llm
    }
}

struct ConversationRecord: Decodable {
    let conversationId: String
    let status: String
    let messages: [ConversationMessage]
    let lastActivityAt: String

    enum CodingKeys: String, CodingKey {
        case conversationId = "conversation_id"
        case status, messages
        case lastActivityAt = "last_activity_at"
    }
}

struct ConversationResponse: Decodable {
    let conversation: ConversationRecord
}

struct ConversationMessageResponse: Decodable {
    let userMessage: ConversationMessage
    let assistantMessage: ConversationMessage

    enum CodingKeys: String, CodingKey {
        case userMessage = "user_message"
        case assistantMessage = "assistant_message"
    }
}

private struct ErrorResponse: Decodable {
    let error: APIErrorBody
}

private struct APIErrorBody: Decodable {
    let code: String
    let message: String
}

struct AuraFiAPIClient {
    let baseURL: URL?
    let session: URLSession
    let timeout: TimeInterval
    let channel = "ios_app"
    let correlationId: String

    init(baseURL: URL? = AuraFiConfiguration.apiBaseURL, session: URLSession = .shared, timeout: TimeInterval = 20) {
        self.baseURL = baseURL
        self.session = session
        self.timeout = timeout
        self.correlationId = UUID().uuidString
    }

    func health() async throws -> HealthResponse {
        try await send(method: "GET", path: "/health", body: Optional<EmptyBody>.none, authenticated: false)
    }

    func requestOTP(email: String) async throws -> OTPChallenge {
        struct Body: Encodable { let email: String; let channel: String }
        let response: OTPChallenge = try await send(
            method: "POST",
            path: "/v1/auth/otp/request",
            body: Body(email: email, channel: channel),
            authenticated: false
        )
        return response
    }

    func verifyOTP(challengeId: String, otp: String) async throws -> AuthSession {
        struct Body: Encodable {
            let challengeId: String
            let otp: String

            enum CodingKeys: String, CodingKey {
                case challengeId = "challenge_id"
                case otp
            }
        }

        let response: AuthResponse = try await send(
            method: "POST",
            path: "/v1/auth/otp/verify",
            body: Body(challengeId: challengeId, otp: otp),
            authenticated: false
        )
        return response.session
    }

    func setRiskProfile(
        sessionToken: String,
        profile: RiskProfile,
        answers: [APIAnswer]
    ) async throws -> ProfileResponse {
        guard answers.count == 5 else {
            throw AuraFiAPIError.invalidParameter("Responda às cinco perguntas do perfil para continuar.")
        }
        return try await send(
            method: "PUT",
            path: "/v1/profile/risk",
            body: APIProfileInput(declaredProfile: profile, answers: answers),
            token: sessionToken
        )
    }

    func listOpportunities(sessionToken: String, pageSize: Int = 20) async throws -> OpportunityListResponse {
        try await listOpportunities(
            sessionToken: sessionToken,
            page: 1,
            pageSize: pageSize,
            riskProfile: nil,
            asset: nil,
            blockchain: nil
        )
    }

    func getOpportunity(sessionToken: String, opportunityId: String) async throws -> OpportunityResponse {
        try await send(
            method: "GET",
            path: "/v1/opportunities/\(opportunityId)",
            body: Optional<EmptyBody>.none,
            token: sessionToken
        )
    }

    func listOpportunities(
        sessionToken: String,
        page: Int = 1,
        pageSize: Int = 20,
        riskProfile: RiskProfile? = nil,
        asset: String? = nil,
        blockchain: String? = nil
    ) async throws -> OpportunityListResponse {
        guard page >= 1 else {
            throw AuraFiAPIError.invalidParameter("A página deve começar em 1.")
        }
        guard (1...100).contains(pageSize) else {
            throw AuraFiAPIError.invalidParameter("A quantidade por página deve estar entre 1 e 100.")
        }
        if let asset, !(2...20).contains(asset.count) {
            throw AuraFiAPIError.invalidParameter("O filtro de ativo deve ter entre 2 e 20 caracteres.")
        }
        if let blockchain, !(2...80).contains(blockchain.count) {
            throw AuraFiAPIError.invalidParameter("O filtro de blockchain deve ter entre 2 e 80 caracteres.")
        }

        var components = URLComponents(url: try makeURL(path: "/v1/opportunities"), resolvingAgainstBaseURL: false)
        var queryItems = [
            URLQueryItem(name: "page", value: String(page)),
            URLQueryItem(name: "page_size", value: String(pageSize))
        ]
        if let riskProfile {
            queryItems.append(URLQueryItem(name: "risk_profile", value: riskProfile.rawValue))
        }
        if let asset {
            queryItems.append(URLQueryItem(name: "asset", value: asset))
        }
        if let blockchain {
            queryItems.append(URLQueryItem(name: "blockchain", value: blockchain))
        }
        components?.queryItems = queryItems
        guard let url = components?.url else { throw AuraFiAPIError.invalidResponse }
        return try await send(url: url, method: "GET", body: Optional<Data>.none, token: sessionToken)
    }

    func listAlerts(
        sessionToken: String,
        page: Int = 1,
        pageSize: Int = 20,
        unreadOnly: Bool = false
    ) async throws -> AlertListResponse {
        guard page >= 1 else {
            throw AuraFiAPIError.invalidParameter("A página deve começar em 1.")
        }
        guard (1...100).contains(pageSize) else {
            throw AuraFiAPIError.invalidParameter("A quantidade por página deve estar entre 1 e 100.")
        }
        var components = URLComponents(url: try makeURL(path: "/v1/alerts"), resolvingAgainstBaseURL: false)
        var queryItems = [
            URLQueryItem(name: "page", value: String(page)),
            URLQueryItem(name: "page_size", value: String(pageSize))
        ]
        if unreadOnly {
            queryItems.append(URLQueryItem(name: "unread_only", value: "true"))
        }
        components?.queryItems = queryItems
        guard let url = components?.url else { throw AuraFiAPIError.invalidResponse }
        return try await send(url: url, method: "GET", body: Optional<Data>.none, token: sessionToken)
    }

    func markAlertRead(sessionToken: String, alertId: String) async throws -> Alert {
        struct Body: Encodable { let status: String }
        let response: AlertResponse = try await send(
            method: "PATCH",
            path: "/v1/alerts/\(alertId)",
            body: Body(status: "read"),
            token: sessionToken
        )
        return response.alert
    }

    func createSimulation(sessionToken: String, input: SimulationInput) async throws -> Simulation {
        struct Response: Decodable { let simulation: Simulation }
        let response: Response = try await send(
            method: "POST",
            path: "/v1/simulations",
            body: input,
            token: sessionToken
        )
        return response.simulation
    }

    func getProfile(sessionToken: String) async throws -> ProfileResponse {
        try await send(
            method: "GET",
            path: "/v1/profile",
            body: Optional<EmptyBody>.none,
            token: sessionToken
        )
    }

    func refreshSession(refreshToken: String) async throws -> AuthSession {
        struct Body: Encodable {
            let refreshToken: String
            enum CodingKeys: String, CodingKey { case refreshToken = "refresh_token" }
        }
        let response: AuthResponse = try await send(
            method: "POST",
            path: "/v1/auth/refresh",
            body: Body(refreshToken: refreshToken),
            authenticated: false
        )
        return response.session
    }

    func logout(sessionToken: String) async throws {
        try await sendWithoutResponse(method: "POST", path: "/v1/auth/logout", token: sessionToken)
    }

    func createConversation(
        sessionToken: String,
        consent: ConversationConsent,
        initialMessage: String? = nil
    ) async throws -> ConversationRecord {
        struct Body: Encodable {
            let channel: String
            let consent: ConversationConsent
            let initialMessage: String?
            enum CodingKeys: String, CodingKey {
                case channel, consent
                case initialMessage = "initial_message"
            }
        }
        let response: ConversationResponse = try await send(
            method: "POST",
            path: "/v1/conversations",
            body: Body(channel: channel, consent: consent, initialMessage: initialMessage),
            token: sessionToken
        )
        return response.conversation
    }

    func sendConversationMessage(
        sessionToken: String,
        conversationId: String,
        text: String,
        consent: ConversationConsent,
        externalMessageId: String
    ) async throws -> ConversationMessageResponse {
        struct Body: Encodable {
            let text: String
            let channel: String
            let consent: ConversationConsent
            let externalMessageId: String

            enum CodingKeys: String, CodingKey {
                case text, channel, consent
                case externalMessageId = "external_message_id"
            }
        }
        return try await send(
            method: "POST",
            path: "/v1/conversations/\(conversationId)/messages",
            body: Body(
                text: text,
                channel: channel,
                consent: consent,
                externalMessageId: externalMessageId
            ),
            token: sessionToken
        )
    }

    func getConversation(sessionToken: String, conversationId: String) async throws -> ConversationRecord {
        let response: ConversationResponse = try await send(
            method: "GET",
            path: "/v1/conversations/\(conversationId)",
            body: Optional<EmptyBody>.none,
            token: sessionToken
        )
        return response.conversation
    }

    private func makeURL(path: String) throws -> URL {
        guard let baseURL else { throw AuraFiAPIError.configuration }
        return baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/")))
    }

    private func send<Response: Decodable, Body: Encodable>(
        method: String,
        path: String,
        body: Body?,
        token: String? = nil,
        authenticated: Bool = true
    ) async throws -> Response {
        let url = try makeURL(path: path)
        let bodyData = try body.map { try JSONEncoder().encode($0) }
        return try await send(url: url, method: method, body: bodyData, token: token, authenticated: authenticated)
    }

    private func send<Response: Decodable>(
        url: URL,
        method: String,
        body: Data?,
        token: String? = nil,
        authenticated: Bool = true
    ) async throws -> Response {
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(channel, forHTTPHeaderField: "X-Channel")
        request.setValue(correlationId, forHTTPHeaderField: "X-Correlation-ID")
        request.setValue(UUID().uuidString, forHTTPHeaderField: "X-Request-ID")
        if authenticated, let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        request.httpBody = body

        do {
            let (data, response) = try await session.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse else { throw AuraFiAPIError.invalidResponse }
            guard (200...299).contains(httpResponse.statusCode) else {
                let error = try? JSONDecoder().decode(ErrorResponse.self, from: data)
                throw AuraFiAPIError.server(
                    status: httpResponse.statusCode,
                    code: error?.error.code ?? "API_ERROR",
                    message: error?.error.message ?? "O serviço não pôde concluir a solicitação."
                )
            }
            do {
                return try JSONDecoder().decode(Response.self, from: data)
            } catch {
                throw AuraFiAPIError.decoding(error)
            }
        } catch let error as AuraFiAPIError {
            throw error
        } catch {
            throw AuraFiAPIError.transport(error)
        }
    }

    private func sendWithoutResponse(method: String, path: String, token: String) async throws {
        let url = try makeURL(path: path)
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(channel, forHTTPHeaderField: "X-Channel")
        request.setValue(correlationId, forHTTPHeaderField: "X-Correlation-ID")
        request.setValue(UUID().uuidString, forHTTPHeaderField: "X-Request-ID")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        do {
            let (data, response) = try await session.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse else {
                throw AuraFiAPIError.invalidResponse
            }
            guard (200...299).contains(httpResponse.statusCode) else {
                let error = try? JSONDecoder().decode(ErrorResponse.self, from: data)
                throw AuraFiAPIError.server(
                    status: httpResponse.statusCode,
                    code: error?.error.code ?? "API_ERROR",
                    message: error?.error.message ?? "O serviço não pôde concluir a solicitação."
                )
            }
        } catch let error as AuraFiAPIError {
            throw error
        } catch {
            throw AuraFiAPIError.transport(error)
        }
    }
}

private struct EmptyBody: Encodable {}
