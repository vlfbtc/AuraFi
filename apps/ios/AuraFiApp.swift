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
    case otp
    case declaredProfile
    case dashboard
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

    @Published var flow: AppFlow = .welcome
    @Published var email = ""
    @Published var otpCode = ""
    @Published var otpChallenge: OTPChallenge?
    @Published var session: AuthSession?
    @Published var declaredProfile: RiskProfile?
    @Published var opportunities: [Opportunity] = []
    @Published var marketSource: APIDataSource?
    @Published var lastSimulation: Simulation?
    @Published var isLoading = false
    @Published var errorMessage: String?
    @Published var deliveryMessage: String?

    #if DEBUG
    private let previewOpportunities: [Opportunity]?
    #endif

    init(apiClient: AuraFiAPIClient = AuraFiAPIClient()) {
        self.apiClient = apiClient
        #if DEBUG
        self.previewOpportunities = nil
        #endif
    }

    #if DEBUG
    init(previewOpportunities: [Opportunity]) {
        self.apiClient = AuraFiAPIClient(baseURL: nil)
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
            self.flow = .declaredProfile
        }
    }

    func declare(profile: RiskProfile) async {
        guard let session else {
            errorMessage = "Confirme seu acesso antes de declarar um perfil."
            flow = .welcome
            return
        }

        await perform { [self] in
            _ = try await apiClient.setRiskProfile(sessionToken: session.accessToken, profile: profile)
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

        await perform { [self] in
            let response = try await apiClient.listOpportunities(sessionToken: session.accessToken)
            self.opportunities = response.items
            self.marketSource = response.items.first?.dataSource
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

    func clearError() {
        errorMessage = nil
    }

    func restart() {
        email = ""
        otpCode = ""
        otpChallenge = nil
        session = nil
        declaredProfile = nil
        opportunities = []
        marketSource = nil
        lastSimulation = nil
        deliveryMessage = nil
        errorMessage = nil
        flow = .welcome
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
            case .welcome, .otp, .declaredProfile:
                OnboardingView()
            case .dashboard:
                DashboardView()
            }
        }
        .tint(.indigo)
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
