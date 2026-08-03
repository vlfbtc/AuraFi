import Foundation

enum AuraFiConfiguration {
    static var apiBaseURL: URL? {
        let configuredValue = ProcessInfo.processInfo.environment["AURAFI_API_BASE_URL"]
            ?? Bundle.main.object(forInfoDictionaryKey: "AURAFI_API_BASE_URL") as? String

        if let configuredValue,
           let url = URL(string: configuredValue.trimmingCharacters(in: .whitespacesAndNewlines)),
           url.scheme != nil,
           url.host != nil {
            return url
        }

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

    enum CodingKeys: String, CodingKey {
        case source
        case mode
        case observedAt = "observed_at"
        case retrievedAt = "retrieved_at"
        case cacheExpiresAt = "cache_expires_at"
        case readOnly = "read_only"
        case isStale = "is_stale"
        case freshnessNote = "freshness_note"
    }

    var sourceLabel: String {
        source.caseInsensitiveCompare("defillama") == .orderedSame ? "DeFiLlama" : source
    }

    var statusLabel: String {
        if isStale { return "Atualização pendente" }
        switch mode {
        case "live": return "Dados atualizados"
        case "cache": return "Última leitura disponível"
        default: return "Conteúdo de prévia"
        }
    }

    var statusDescription: String {
        if let freshnessNote, !freshnessNote.isEmpty { return freshnessNote }
        if isStale { return "Confira o momento da observação antes de tomar qualquer decisão." }
        return "Leitura de mercado com origem e momento informados."
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

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case tokenType = "token_type"
        case expiresAt = "expires_at"
        case accountId = "account_id"
        case email
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

struct APIMarketValue: Decodable {
    let value: Double
    let unit: String?
    let currency: String?
    let observedAt: String

    enum CodingKeys: String, CodingKey {
        case value
        case unit
        case currency
        case observedAt = "observed_at"
    }
}

struct APILiquidity: Decodable {
    let level: String
    let observedAt: String

    enum CodingKeys: String, CodingKey {
        case level
        case observedAt = "observed_at"
    }
}

struct APIRisk: Decodable {
    let score: Double?
    let level: String
    let dimensions: [String]
}

struct Opportunity: Identifiable, Decodable {
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
        String(format: "%.2f%% a.a.", apy.value)
    }

    var tvlLabel: String {
        let currency = tvl.currency ?? "USD"
        return String(format: "%@ %.0f", currency == "USD" ? "US$" : currency, tvl.value)
    }
}

struct OpportunityListResponse: Decodable {
    let items: [Opportunity]
    let pagination: Pagination
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

    var id: Int { horizonDays }

    enum CodingKeys: String, CodingKey {
        case horizonDays = "horizon_days"
        case projectedValue = "projected_value"
        case projectedYield = "projected_yield"
        case idleStablecoinValue = "idle_stablecoin_value"
        case currency
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

    enum CodingKeys: String, CodingKey {
        case opportunityId = "opportunity_id"
        case amount
        case asset
        case horizonsDays = "horizons_days"
        case compareIdleStablecoin = "compare_idle_stablecoin"
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

    func setRiskProfile(sessionToken: String, profile: RiskProfile) async throws -> ProfileResponse {
        let answers = (1...5).map { APIAnswer(questionId: "question_\($0)", answer: profile.rawValue) }
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

    /// GET /v1/opportunities using the app session token.
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
}

private struct EmptyBody: Encodable {}
