import SwiftUI

struct DashboardView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var selectedOpportunity: Opportunity?
    @State private var showSettings = false

    var body: some View {
        TabView {
            dashboardTab
                .tabItem { Label("Início", systemImage: "house") }
            InformationTab(
                title: "Aura",
                message: "A conversa com a Aura será conectada ao hub com consentimento explícito.",
                icon: "message.fill"
            )
            .tabItem { Label("Aura", systemImage: "message") }
            InformationTab(
                title: "Simulação",
                message: "Escolha uma oportunidade no Início para projetar cenários.",
                icon: "chart.bar.fill"
            )
            .tabItem { Label("Sim.", systemImage: "chart.bar") }
            InformationTab(
                title: "Protocolos",
                message: "As oportunidades disponíveis mostram protocolo, rede, risco e origem dos dados.",
                icon: "square.grid.2x2.fill"
            )
            .tabItem { Label("Protoc.", systemImage: "square.grid.2x2") }
            InformationTab(
                title: "Histórico",
                message: "Suas decisões aparecerão aqui quando o registro de aceite e recusa estiver disponível.",
                icon: "clock.arrow.circlepath"
            )
            .tabItem { Label("Hist.", systemImage: "clock.arrow.circlepath") }
        }
        .tint(AuraTheme.pink)
        .task { await appModel.loadOpportunities() }
    }

    private var dashboardTab: some View {
        NavigationStack {
            ZStack {
                AuraTheme.lavender.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        header
                        TrustCard()

                        if let errorMessage = appModel.errorMessage {
                            ErrorCard(message: errorMessage) {
                                Task { await appModel.loadOpportunities() }
                            }
                        }

                        if appModel.isLoading && appModel.opportunities.isEmpty {
                            OpportunitySkeleton()
                        } else if appModel.opportunities.isEmpty {
                            emptyState
                        } else {
                            opportunitiesContent
                        }

                        DisclaimerCard()
                    }
                    .padding(.horizontal, 18)
                    .padding(.vertical, 18)
                }
                .refreshable { await appModel.loadOpportunities() }
            }
            .toolbar {
                ToolbarItemGroup(placement: .topBarTrailing) {
                    Button { showSettings = true } label: { Image(systemName: "gearshape") }
                        .accessibilityLabel("Abrir configurações")
                    Button { Task { await appModel.loadOpportunities() } } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .accessibilityLabel("Atualizar oportunidades")
                    .disabled(appModel.isLoading)
                }
            }
            .sheet(isPresented: $showSettings) { SettingsView() }
            .sheet(item: $selectedOpportunity) { opportunity in
                OpportunityDetailView(opportunity: opportunity)
                    .environmentObject(appModel)
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text("Olá!")
                .font(.system(size: 32, weight: .bold, design: .rounded))
                .foregroundStyle(AuraTheme.purple)
            HStack(spacing: 8) {
                if let profile = appModel.declaredProfile {
                    Text("Perfil \(profile.title.lowercased())")
                }
                Text("•")
                Text("Apoio não custodial")
            }
            .font(.subheadline)
            .foregroundStyle(.secondary)
        }
    }

    private var opportunitiesContent: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Oportunidades para você")
                .font(.title2.bold())
                .foregroundStyle(AuraTheme.purple)
            Text("Curadas conforme seu perfil declarado, com riscos e fonte visíveis.")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            ForEach(appModel.opportunities) { opportunity in
                OpportunityCard(opportunity: opportunity) {
                    selectedOpportunity = opportunity
                }
            }
        }
    }

    private var emptyState: some View {
        ContentUnavailableView {
            Label("Nenhuma oportunidade agora", systemImage: "sparkles")
        } description: {
            Text("Não encontramos uma opção compatível neste momento. Atualize ou revise seu perfil.")
        } actions: {
            Button("Atualizar") { Task { await appModel.loadOpportunities() } }
                .buttonStyle(.borderedProminent)
        }
        .padding()
        .background(.white, in: RoundedRectangle(cornerRadius: 18))
    }
}

private struct TrustCard: View {
    var body: some View {
        HStack(spacing: 13) {
            Image(systemName: "checkmark.shield.fill")
                .font(.title2)
                .foregroundStyle(AuraTheme.success)
            VStack(alignment: .leading, spacing: 3) {
                Text("Você decide. A AuraFi explica.").font(.headline)
                Text("Não acessamos sua wallet nem executamos transações.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.white, in: RoundedRectangle(cornerRadius: 16))
    }
}

private struct OpportunityCard: View {
    let opportunity: Opportunity
    let action: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            HStack(alignment: .top) {
                RoundedRectangle(cornerRadius: 3)
                    .fill(riskColor)
                    .frame(width: 6, height: 66)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 4) {
                    Text("\(opportunity.protocolName) · \(opportunity.asset)")
                        .font(.headline)
                        .foregroundStyle(AuraTheme.purple)
                    Text("\(opportunity.blockchain) · \(auditLabel)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(opportunity.apyLabel)
                        .font(.system(size: 26, weight: .bold, design: .rounded))
                        .foregroundStyle(riskColor)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 4) {
                    Text("Score \(scoreLabel)").font(.caption.bold())
                    Text("TVL \(compactTVL)").font(.caption)
                }
                .foregroundStyle(.secondary)
            }

            Button("Ver detalhes e simular", action: action)
                .buttonStyle(AuraPrimaryButtonStyle())
        }
        .padding(15)
        .background(.white, in: RoundedRectangle(cornerRadius: 16))
        .overlay { RoundedRectangle(cornerRadius: 16).stroke(AuraTheme.border) }
        .accessibilityElement(children: .contain)
    }

    private var riskColor: Color {
        opportunity.risk.level == "high" ? .orange : AuraTheme.success
    }
    private var scoreLabel: String { opportunity.risk.score.map { String(format: "%.1f", $0) } ?? "–" }
    private var auditLabel: String { opportunity.auditStatus == "audited" ? "Auditado" : (opportunity.auditStatus ?? "Auditoria não informada") }
    private var compactTVL: String {
        let value = opportunity.tvl.value
        if value >= 1_000_000_000 { return String(format: "US$ %.1f bi", value / 1_000_000_000) }
        if value >= 1_000_000 { return String(format: "US$ %.0f mi", value / 1_000_000) }
        return opportunity.tvlLabel
    }
}

struct OpportunityDetailView: View {
    let opportunity: Opportunity
    @EnvironmentObject private var appModel: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var showSimulation = false

    var body: some View {
        NavigationStack {
            ZStack {
                AuraTheme.lavender.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        hero
                        Text("Dados que importam").font(.title3.bold()).foregroundStyle(AuraTheme.purple)
                        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                            MetricCard(title: "SEGURANÇA", value: scoreLabel, detail: opportunity.riskLabel)
                            MetricCard(title: "TVL", value: compactTVL, detail: "liquidez observada")
                            MetricCard(title: "AUDITORIA", value: auditLabel, detail: "status informado")
                            MetricCard(title: "REDE", value: opportunity.blockchain, detail: opportunity.liquidity.level)
                        }
                        DataSourceBanner(source: opportunity.dataSource)
                        Label("APY varia em tempo real e não há garantia de retorno.", systemImage: "exclamationmark.circle")
                            .font(.footnote)
                            .foregroundStyle(AuraTheme.pink)
                        Button("Simular alocação") { showSimulation = true }
                            .buttonStyle(AuraPrimaryButtonStyle())
                    }
                    .padding(18)
                }
            }
            .navigationTitle("Oportunidade")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Fechar") { dismiss() } } }
            .sheet(isPresented: $showSimulation) {
                SimulationView(opportunity: opportunity)
                    .environmentObject(appModel)
            }
        }
    }

    private var hero: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("\(opportunity.protocolName) · \(opportunity.asset) · \(opportunity.blockchain)")
                .font(.headline).foregroundStyle(AuraTheme.pinkBright)
            Text(opportunity.apyLabel)
                .font(.system(size: 38, weight: .bold, design: .rounded))
            Text("APY observado · atualizado pela fonte informada")
                .font(.caption).foregroundStyle(.white.opacity(0.72))
        }
        .foregroundStyle(.white)
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AuraTheme.purple, in: RoundedRectangle(cornerRadius: 18))
    }

    private var scoreLabel: String { opportunity.risk.score.map { String(format: "%.1f/10", $0) } ?? "Não informado" }
    private var auditLabel: String { opportunity.auditStatus == "audited" ? "Auditado" : (opportunity.auditStatus ?? "Não informado") }
    private var compactTVL: String {
        opportunity.tvl.value >= 1_000_000_000
            ? String(format: "US$ %.1f bi", opportunity.tvl.value / 1_000_000_000)
            : opportunity.tvlLabel
    }
}

private struct MetricCard: View {
    let title: String
    let value: String
    let detail: String
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.headline).foregroundStyle(AuraTheme.purple)
            Text(detail).font(.caption2).foregroundStyle(.secondary)
        }
        .padding(13)
        .frame(maxWidth: .infinity, minHeight: 102, alignment: .leading)
        .background(.white, in: RoundedRectangle(cornerRadius: 14))
        .overlay { RoundedRectangle(cornerRadius: 14).stroke(AuraTheme.border) }
    }
}

struct SimulationView: View {
    let opportunity: Opportunity
    @EnvironmentObject private var appModel: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var amountText = "2000"
    @State private var submittedAmount: Double?

    var body: some View {
        NavigationStack {
            ZStack {
                AuraTheme.lavender.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        selectedCard
                        Text("Quanto você alocaria?").font(.title3.bold()).foregroundStyle(AuraTheme.purple)
                        HStack {
                            Text("US$").foregroundStyle(.secondary)
                            TextField("2.000,00", text: $amountText)
                                .keyboardType(.decimalPad)
                                .font(.system(size: 30, weight: .bold, design: .rounded))
                        }
                        .padding(16)
                        .background(.white, in: RoundedRectangle(cornerRadius: 14))
                        .overlay { RoundedRectangle(cornerRadius: 14).stroke(AuraTheme.pink, lineWidth: 2) }

                        HStack {
                            ForEach([500, 1000, 2000, 5000], id: \.self) { value in
                                Button(value == 5000 ? "5 mil" : "\(value)") { amountText = String(value) }
                                    .buttonStyle(.bordered)
                                    .buttonBorderShape(.capsule)
                            }
                        }

                        if let message = appModel.errorMessage {
                            ErrorCard(message: message) { simulate() }
                        }

                        if let simulation = appModel.lastSimulation,
                           submittedAmount == simulation.input.amount,
                           simulation.opportunityId == opportunity.opportunityId {
                            SimulationResultCard(simulation: simulation)
                        }

                        Button(appModel.lastSimulation == nil ? "Projetar cenário" : "Atualizar cenário") { simulate() }
                            .buttonStyle(AuraPrimaryButtonStyle())
                            .disabled(parsedAmount == nil || appModel.isLoading)

                        DisclaimerCard()
                    }
                    .padding(18)
                }
            }
            .navigationTitle("Simulação")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Fechar") { dismiss() } } }
        }
    }

    private var selectedCard: some View {
        HStack {
            RoundedRectangle(cornerRadius: 3).fill(AuraTheme.success).frame(width: 6, height: 50)
            VStack(alignment: .leading) {
                Text("\(opportunity.protocolName) · \(opportunity.asset) · \(opportunity.blockchain)").font(.headline)
                Text("\(opportunity.apyLabel) · risco \(opportunity.riskLabel.lowercased())").font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.white, in: RoundedRectangle(cornerRadius: 14))
        .overlay { RoundedRectangle(cornerRadius: 14).stroke(AuraTheme.border) }
    }

    private var parsedAmount: Double? {
        let normalized = amountText.replacingOccurrences(of: ".", with: "").replacingOccurrences(of: ",", with: ".")
        guard let value = Double(normalized), value > 0 else { return nil }
        return value
    }

    private func simulate() {
        guard let amount = parsedAmount else { return }
        submittedAmount = amount
        Task { await appModel.createSimulation(for: opportunity, amount: amount) }
    }
}

private struct SimulationResultCard: View {
    let simulation: Simulation
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Cenário projetado").font(.headline)
            ForEach(simulation.scenarios) { scenario in
                HStack {
                    Text(horizonLabel(scenario.horizonDays))
                    Spacer()
                    Text("+ \(money(scenario.projectedYield, currency: scenario.currency))")
                        .font(.headline).foregroundStyle(AuraTheme.success)
                }
                .font(.subheadline)
            }
            Divider().overlay(.white.opacity(0.3))
            Label("Apenas projeção: nenhuma transação será executada.", systemImage: "hand.raised.fill")
                .font(.caption)
            Text(simulation.disclaimer).font(.caption).foregroundStyle(.white.opacity(0.72))
        }
        .foregroundStyle(.white)
        .padding(18)
        .background(AuraTheme.purple, in: RoundedRectangle(cornerRadius: 18))
        .accessibilityElement(children: .contain)
    }

    private func horizonLabel(_ days: Int) -> String {
        switch days { case 30: return "Em 30 dias"; case 180: return "Em 6 meses"; case 365: return "Em 12 meses"; default: return "Em \(days) dias" }
    }
    private func money(_ value: Double, currency: String) -> String {
        String(format: "%@ %.2f", currency == "USD" || currency == "USDC" ? "US$" : currency, value)
    }
}

private struct InformationTab: View {
    let title: String
    let message: String
    let icon: String
    var body: some View {
        NavigationStack {
            ZStack {
                AuraTheme.lavender.ignoresSafeArea()
                ContentUnavailableView(title, systemImage: icon, description: Text(message))
            }
        }
    }
}

private struct SettingsView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var confirmExit = false
    var body: some View {
        NavigationStack {
            ZStack {
                AuraTheme.lavender.ignoresSafeArea()
                List {
                    Section {
                        LabeledContent("E-mail", value: appModel.email)
                        LabeledContent("Perfil", value: appModel.declaredProfile?.title ?? "Não declarado")
                    }
                    Section("Privacidade") {
                        Label("Baixar meus dados", systemImage: "arrow.down.doc")
                        Label("Política de privacidade", systemImage: "hand.raised")
                    }
                    Section {
                        Button("Sair", role: .destructive) { confirmExit = true }
                    }
                }
                .scrollContentBackground(.hidden)
            }
            .navigationTitle("Configurações")
            .confirmationDialog("Sair da conta?", isPresented: $confirmExit, titleVisibility: .visible) {
                Button("Confirmar saída", role: .destructive) { appModel.restart() }
                Button("Cancelar", role: .cancel) {}
            } message: { Text("Será necessário confirmar um novo código para entrar novamente.") }
        }
    }
}

private struct OpportunitySkeleton: View {
    var body: some View {
        VStack(spacing: 12) {
            ForEach(0..<2, id: \.self) { _ in
                RoundedRectangle(cornerRadius: 16)
                    .fill(.white.opacity(0.78))
                    .frame(height: 170)
                    .overlay { ProgressView().tint(AuraTheme.pink) }
            }
            Text("Buscando oportunidades com riscos e fontes verificáveis…")
                .font(.footnote).foregroundStyle(.secondary)
        }
        .accessibilityLabel("Carregando oportunidades")
    }
}
