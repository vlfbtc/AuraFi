import SwiftUI

struct DashboardView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var selectedOpportunity: Opportunity?
    @State private var showSettings = false

    var body: some View {
        TabView(selection: $appModel.selectedTab) {
            dashboardTab
                .tag(MainTab.dashboard)
                .tabItem { Label("Início", systemImage: "house") }
            AuraChatView()
                .tag(MainTab.aura)
                .tabItem { Label("Aura", systemImage: "message") }
            SimulationHubView()
                .tag(MainTab.simulation)
                .tabItem { Label("Simulação", systemImage: "chart.bar") }
            ProtocolCatalogView()
                .tag(MainTab.protocols)
                .tabItem { Label("Protocolos", systemImage: "square.grid.2x2") }
            HistoryView()
                .tag(MainTab.history)
                .tabItem { Label("Histórico", systemImage: "clock.arrow.circlepath") }
        }
        .tint(AuraTheme.pink)
        .task { await appModel.restoreSessionIfNeeded() }
    }

    private var dashboardTab: some View {
        NavigationStack {
            ZStack {
                AuraTheme.lavender.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        header
                        TrustCard()

                        if appModel.isUsingCachedMarket {
                            OfflineBanner {
                                Task { await appModel.loadOpportunities() }
                            }
                        } else if let errorMessage = appModel.errorMessage {
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

                        AuraSuggestionCard {
                            appModel.selectedTab = .aura
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
                        .accessibilityLabel("Abrir ajustes")
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
            Text("Olá, \(firstName)")
                .font(.system(size: 32, weight: .bold, design: .rounded))
                .foregroundStyle(AuraTheme.purple)
            HStack(spacing: 8) {
                Text("Perfil \((appModel.declaredProfile?.title ?? "não declarado").lowercased())")
                Text("•")
                Text("Não custodial")
            }
            .font(.subheadline)
            .foregroundStyle(.secondary)
        }
        .accessibilityElement(children: .combine)
    }

    private var firstName: String {
        let localPart = appModel.email.split(separator: "@").first.map(String.init) ?? ""
        guard !localPart.isEmpty else { return "você" }
        return localPart.split(whereSeparator: { ".-_".contains($0) }).first.map {
            $0.prefix(1).uppercased() + $0.dropFirst()
        } ?? "você"
    }

    private var opportunitiesContent: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Text("Oportunidades para você")
                    .font(.title2.bold())
                    .foregroundStyle(AuraTheme.purple)
                Spacer()
                Button("Ver todas") { appModel.selectedTab = .protocols }
                    .font(.subheadline.weight(.semibold))
            }
            Text("Dados observados, riscos e fonte sempre visíveis.")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            ForEach(appModel.opportunities.prefix(3)) { opportunity in
                OpportunityCard(opportunity: opportunity) {
                    selectedOpportunity = opportunity
                }
            }
        }
    }

    private var emptyState: some View {
        EmptyStateCard(
            title: "Nenhuma oportunidade agora",
            message: "Hoje os pools compatíveis não estão disponíveis. Atualize ou revise seu perfil.",
            icon: "sparkles",
            actionTitle: "Atualizar"
        ) { Task { await appModel.loadOpportunities() } }
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
                Text("Nunca tocamos seus fundos e não executamos transações.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AuraTheme.purple, in: RoundedRectangle(cornerRadius: 16))
        .foregroundStyle(.white)
        .accessibilityElement(children: .combine)
    }
}

private struct AuraSuggestionCard: View {
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(alignment: .top, spacing: 12) {
                AuraMark(size: 36)
                VStack(alignment: .leading, spacing: 4) {
                    Text("Converse com a Aura").font(.headline)
                    Text("Compare riscos, entenda os dados e decida no seu ritmo.")
                        .font(.subheadline)
                    Text("Abrir conversa →").font(.caption.bold()).foregroundStyle(AuraTheme.pink)
                }
                Spacer()
            }
            .foregroundStyle(AuraTheme.purple)
            .padding(15)
            .background(AuraTheme.pink.opacity(0.06), in: RoundedRectangle(cornerRadius: 16))
            .overlay { RoundedRectangle(cornerRadius: 16).stroke(AuraTheme.pink) }
        }
        .buttonStyle(.plain)
        .accessibilityHint("Abre o hub conversacional")
    }
}

private struct OfflineBanner: View {
    let retry: () -> Void
    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "wifi.slash")
            VStack(alignment: .leading, spacing: 4) {
                Text("Sem conexão agora").font(.headline)
                Text("Mostramos o que estava salvo. Os valores podem estar desatualizados.")
                    .font(.footnote)
                Button("Tentar atualizar", action: retry).font(.footnote.bold())
            }
        }
        .foregroundStyle(.orange)
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.orange.opacity(0.10), in: RoundedRectangle(cornerRadius: 14))
        .accessibilityElement(children: .combine)
    }
}

struct OpportunityCard: View {
    let opportunity: Opportunity
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 13) {
                HStack(alignment: .top) {
                    RoundedRectangle(cornerRadius: 3)
                        .fill(riskColor)
                        .frame(width: 6, height: 70)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("\(opportunity.protocolName) · \(opportunity.asset)")
                            .font(.headline)
                            .foregroundStyle(AuraTheme.purple)
                        Text("\(opportunity.blockchain) · \(auditLabel)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(opportunity.apyLabel)
                            .font(.system(size: 25, weight: .bold, design: .rounded))
                            .foregroundStyle(riskColor)
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 5) {
                        Text("Score \(scoreLabel)").font(.caption.bold())
                        Text("TVL \(compactTVL)").font(.caption)
                        Text("Detalhes →").font(.caption.bold()).foregroundStyle(AuraTheme.pink)
                    }
                    .foregroundStyle(.secondary)
                }
            }
            .padding(15)
            .background(.white, in: RoundedRectangle(cornerRadius: 16))
            .overlay { RoundedRectangle(cornerRadius: 16).stroke(AuraTheme.border) }
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(opportunity.protocolName), \(opportunity.asset), APY \(opportunity.apyLabel), risco \(opportunity.riskLabel), score \(scoreLabel), TVL \(compactTVL)")
        .accessibilityHint("Abre detalhes e simulação")
    }

    private var riskColor: Color { opportunity.risk.level == "high" ? .orange : AuraTheme.success }
    private var scoreLabel: String { opportunity.risk.score.map { String(format: "%.1f", $0) } ?? "não informado" }
    private var auditLabel: String { opportunity.auditStatus == "audited" ? "Auditado" : (opportunity.auditStatus ?? "Auditoria não informada") }
    private var compactTVL: String { compactMoney(opportunity.tvl.value) }
}

struct AuraChatView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var message = ""

    var body: some View {
        NavigationStack {
            ZStack {
                AuraTheme.purple.ignoresSafeArea()
                if appModel.conversationConsent == nil {
                    consentView
                } else {
                    conversationView
                }
            }
            .navigationTitle("Aura")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbarBackground(AuraTheme.purple, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
        }
    }

    private var consentView: some View {
        ScrollView {
            VStack(spacing: 20) {
                Spacer(minLength: 36)
                AuraMark(size: 74)
                Text("Converse com a Aura")
                    .font(.system(size: 30, weight: .bold, design: .rounded))
                Text("Suas mensagens serão enviadas ao hub conversacional para produzir respostas educativas. Não envie senhas, códigos, seed phrases ou chaves privadas.")
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.white.opacity(0.76))
                VStack(alignment: .leading, spacing: 12) {
                    Label("Memória e analytics ficam desativados", systemImage: "brain.head.profile")
                    Label("Você pode sair da conversa quando quiser", systemImage: "xmark.circle")
                    Label("Nenhuma transação pode ser executada", systemImage: "hand.raised.fill")
                }
                .font(.subheadline)
                .padding()
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(.white.opacity(0.08), in: RoundedRectangle(cornerRadius: 16))
                Button("Concordar e iniciar conversa") {
                    Task { await appModel.grantConversationConsent() }
                }
                .buttonStyle(AuraPrimaryButtonStyle())
                .disabled(appModel.isSendingMessage)
                Text("Ao continuar, você concorda apenas com o uso necessário para esta conversa.")
                    .font(.caption)
                    .foregroundStyle(.white.opacity(0.58))
                    .multilineTextAlignment(.center)
            }
            .foregroundStyle(.white)
            .padding(24)
        }
    }

    private var conversationView: some View {
        VStack(spacing: 0) {
            connectionHeader
            if let fallback = appModel.auraFallbackMessage {
                Text(fallback)
                    .font(.footnote)
                    .foregroundStyle(.orange)
                    .padding(.horizontal, 18)
                    .padding(.vertical, 10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.orange.opacity(0.12))
                    .accessibilityLabel("Aviso: \(fallback)")
            }
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 12) {
                        ChatBubble(
                            text: "Olá! Posso explicar riscos, comparar dados observados e ajudar com simulações educativas.",
                            isFromUser: false,
                            isFallback: false
                        )
                        ForEach(appModel.conversationMessages) { item in
                            if let text = item.payload.text, !text.isEmpty {
                                ChatBubble(
                                    text: text,
                                    isFromUser: item.isFromUser,
                                    isFallback: item.payload.fallbackUsed == true
                                )
                                .id(item.id)
                            }
                        }
                        if appModel.isSendingMessage {
                            HStack {
                                ProgressView().tint(.white)
                                Text("A Aura está pensando…").font(.footnote)
                                Spacer()
                            }
                            .foregroundStyle(.white.opacity(0.72))
                            .accessibilityLabel("A Aura está preparando uma resposta")
                        }
                    }
                    .padding(18)
                }
                .onChange(of: appModel.conversationMessages.count) {
                    if let last = appModel.conversationMessages.last { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
            quickActions
            messageComposer
        }
    }

    private var connectionHeader: some View {
        HStack(spacing: 10) {
            AuraMark(size: 34)
            VStack(alignment: .leading, spacing: 1) {
                Text("Aura").font(.headline)
                Text(appModel.conversation == nil ? "conectando ao hub…" : "hub conectado")
                    .font(.caption).foregroundStyle(appModel.conversation == nil ? .orange : AuraTheme.success)
            }
            Spacer()
            Label("Não custodial", systemImage: "checkmark.shield")
                .font(.caption)
        }
        .foregroundStyle(.white)
        .padding(.horizontal, 18)
        .padding(.vertical, 10)
    }

    private var quickActions: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack {
                Button("Explique os riscos") { send("Quais riscos devo observar nas oportunidades atuais?") }
                Button("Compare opções") { send("Compare as oportunidades disponíveis de forma educativa.") }
                Button("Como funciona?") { send("Como a AuraFi usa os dados de mercado?") }
            }
            .buttonStyle(.bordered)
            .tint(AuraTheme.pinkBright)
            .padding(.horizontal, 14)
        }
        .padding(.vertical, 8)
    }

    private var messageComposer: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField("Pergunte algo à Aura…", text: $message, axis: .vertical)
                .lineLimit(1...4)
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .background(.white, in: RoundedRectangle(cornerRadius: 22))
                .foregroundStyle(AuraTheme.purple)
                .accessibilityLabel("Mensagem para a Aura")
            Button { send(message) } label: {
                Image(systemName: "arrow.up")
                    .font(.headline)
                    .foregroundStyle(.white)
                    .frame(width: 46, height: 46)
                    .background(AuraTheme.pinkBright, in: Circle())
            }
            .accessibilityLabel("Enviar mensagem")
            .disabled(message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || appModel.isSendingMessage)
        }
        .padding(14)
        .background(AuraTheme.purple)
    }

    private func send(_ text: String) {
        let content = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !content.isEmpty else { return }
        message = ""
        Task { await appModel.sendMessageToAura(content) }
    }
}

private struct ChatBubble: View {
    let text: String
    let isFromUser: Bool
    let isFallback: Bool
    var body: some View {
        HStack {
            if isFromUser { Spacer(minLength: 44) }
            VStack(alignment: .leading, spacing: 5) {
                Text(text).fixedSize(horizontal: false, vertical: true)
                if isFallback {
                    Label("Resposta segura de contingência", systemImage: "exclamationmark.triangle")
                        .font(.caption2).foregroundStyle(.orange)
                }
            }
            .padding(13)
            .background(isFromUser ? AuraTheme.pinkBright : AuraTheme.purpleSoft, in: RoundedRectangle(cornerRadius: 16))
            .foregroundStyle(.white)
            if !isFromUser { Spacer(minLength: 44) }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(isFromUser ? "Você" : "Aura"): \(text)")
    }
}

struct SimulationHubView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var selectedOpportunity: Opportunity?
    var body: some View {
        NavigationStack {
            ZStack {
                AuraTheme.lavender.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        Text("E se eu alocar…?")
                            .font(.system(size: 30, weight: .bold, design: .rounded))
                            .foregroundStyle(AuraTheme.purple)
                        Text("Escolha uma oportunidade e projete cenários. Nenhuma alocação será executada.")
                            .foregroundStyle(.secondary)
                        if let simulation = appModel.lastSimulation {
                            LastSimulationCard(simulation: simulation)
                        }
                        if appModel.opportunities.isEmpty {
                            EmptyStateCard(
                                title: "Sem oportunidades para simular",
                                message: "Atualize os dados no Início para escolher uma oportunidade.",
                                icon: "chart.bar.xaxis",
                                actionTitle: "Ir para Início"
                            ) { appModel.selectedTab = .dashboard }
                        } else {
                            Text("Escolha uma oportunidade").font(.title3.bold())
                            ForEach(appModel.opportunities) { item in
                                OpportunityCard(opportunity: item) { selectedOpportunity = item }
                            }
                        }
                        DisclaimerCard()
                    }
                    .padding(18)
                }
            }
            .navigationTitle("Simulação")
            .sheet(item: $selectedOpportunity) { item in
                SimulationView(opportunity: item).environmentObject(appModel)
            }
        }
    }
}

private struct LastSimulationCard: View {
    let simulation: Simulation
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Último cenário").font(.headline)
            Text("\(money(simulation.input.amount)) em \(simulation.input.asset)")
                .font(.title3.bold())
            if let scenario = simulation.scenarios.max(by: { $0.horizonDays < $1.horizonDays }) {
                Text("Em \(scenario.horizonDays) dias: + \(money(scenario.projectedYield))")
                    .foregroundStyle(AuraTheme.success).font(.headline)
            }
            Text("Projeção educativa, sem execução.").font(.caption).foregroundStyle(.white.opacity(0.7))
        }
        .foregroundStyle(.white)
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AuraTheme.purple, in: RoundedRectangle(cornerRadius: 16))
    }
}

struct ProtocolCatalogView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var search = ""
    @State private var selectedOpportunity: Opportunity?

    var body: some View {
        NavigationStack {
            ZStack {
                AuraTheme.lavender.ignoresSafeArea()
                if filtered.isEmpty {
                    EmptyStateCard(
                        title: search.isEmpty ? "Catálogo indisponível" : "Nenhum resultado",
                        message: search.isEmpty ? "Atualize os dados para consultar protocolos e pools." : "Tente buscar por protocolo, ativo ou rede.",
                        icon: "square.grid.2x2",
                        actionTitle: search.isEmpty ? "Atualizar" : "Limpar busca"
                    ) {
                        if search.isEmpty { Task { await appModel.loadOpportunities() } } else { search = "" }
                    }
                    .padding(18)
                } else {
                    ScrollView {
                        LazyVStack(spacing: 12) {
                            if let source = appModel.marketSource { DataSourceBanner(source: source) }
                            ForEach(filtered) { item in
                                OpportunityCard(opportunity: item) { selectedOpportunity = item }
                            }
                        }
                        .padding(18)
                    }
                }
            }
            .navigationTitle("Protocolos")
            .searchable(text: $search, prompt: "Protocolo, ativo ou rede")
            .refreshable { await appModel.loadOpportunities() }
            .sheet(item: $selectedOpportunity) { item in
                OpportunityDetailView(opportunity: item).environmentObject(appModel)
            }
        }
    }

    private var filtered: [Opportunity] {
        guard !search.isEmpty else { return appModel.opportunities }
        let query = search.localizedLowercase
        return appModel.opportunities.filter {
            $0.protocolName.localizedLowercase.contains(query)
                || $0.asset.localizedLowercase.contains(query)
                || $0.blockchain.localizedLowercase.contains(query)
        }
    }
}

struct HistoryView: View {
    enum Filter: String, CaseIterable, Identifiable {
        case all = "Tudo"
        case saved = "Salvas"
        case declined = "Recusadas"
        var id: String { rawValue }
    }

    @EnvironmentObject private var appModel: AppModel
    @State private var filter: Filter = .all

    var body: some View {
        NavigationStack {
            ZStack {
                AuraTheme.lavender.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        Picker("Filtrar histórico", selection: $filter) {
                            ForEach(Filter.allCases) { Text($0.rawValue).tag($0) }
                        }
                        .pickerStyle(.segmented)

                        if filtered.isEmpty {
                            EmptyStateCard(
                                title: "Ainda não há histórico aqui",
                                message: "Sua primeira simulação salva ou recusada aparece nesta tela.",
                                icon: "clock.arrow.circlepath",
                                actionTitle: "Fazer uma simulação"
                            ) { appModel.selectedTab = .simulation }
                        } else {
                            ForEach(filtered) { DecisionCard(decision: $0) }
                            LearningCard(decisions: appModel.decisions)
                        }
                        Text("Este histórico fica salvo somente neste aparelho enquanto o servidor não oferece sincronização de decisões.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    .padding(18)
                }
            }
            .navigationTitle("Histórico")
        }
    }

    private var filtered: [DecisionRecord] {
        switch filter {
        case .all: return appModel.decisions
        case .saved: return appModel.decisions.filter { $0.outcome == .saved }
        case .declined: return appModel.decisions.filter { $0.outcome == .declined }
        }
    }
}

private struct DecisionCard: View {
    let decision: DecisionRecord
    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            RoundedRectangle(cornerRadius: 3)
                .fill(decision.outcome == .saved ? AuraTheme.success : Color.gray)
                .frame(width: 6, height: 74)
            VStack(alignment: .leading, spacing: 5) {
                Text(decision.createdAt.formatted(date: .abbreviated, time: .omitted).uppercased())
                    .font(.caption2).foregroundStyle(.secondary)
                Text("\(decision.protocolName) · \(decision.asset) · \(money(decision.amount))")
                    .font(.headline)
                Text(decision.outcome == .saved ? "✓ Cenário salvo para acompanhar" : "○ Você decidiu não seguir agora")
                    .font(.caption).foregroundStyle(decision.outcome == .saved ? AuraTheme.success : Color.secondary)
            }
            Spacer()
            if decision.projectedYield > 0 {
                Text("+ \(money(decision.projectedYield))")
                    .font(.subheadline.bold()).foregroundStyle(AuraTheme.success)
            }
        }
        .padding(14)
        .background(.white, in: RoundedRectangle(cornerRadius: 14))
        .overlay { RoundedRectangle(cornerRadius: 14).stroke(AuraTheme.border) }
        .accessibilityElement(children: .combine)
    }
}

private struct LearningCard: View {
    let decisions: [DecisionRecord]
    var body: some View {
        let declined = decisions.filter { $0.outcome == .declined }.count
        VStack(alignment: .leading, spacing: 8) {
            Text("Você está aprendendo").font(.headline).foregroundStyle(AuraTheme.pinkBright)
            Text(decisions.isEmpty ? "Suas decisões formarão um histórico educativo." : "Você registrou \(decisions.count) decisão(ões), sendo \(declined) recusada(s).")
                .font(.subheadline)
            Text("A Aura não executa nenhuma decisão automaticamente.").font(.caption).foregroundStyle(.white.opacity(0.7))
        }
        .foregroundStyle(.white)
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AuraTheme.purple, in: RoundedRectangle(cornerRadius: 16))
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
                            MetricCard(title: "TVL", value: compactMoney(opportunity.tvl.value), detail: "liquidez observada")
                            MetricCard(title: "AUDITORIA", value: auditLabel, detail: "status informado")
                            MetricCard(title: "REDE", value: opportunity.blockchain, detail: opportunity.liquidity.level)
                        }
                        DataSourceBanner(source: opportunity.dataSource)
                        Label("APY varia em tempo real e não há garantia de retorno.", systemImage: "exclamationmark.circle")
                            .font(.footnote).foregroundStyle(AuraTheme.pink)
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
                SimulationView(opportunity: opportunity).environmentObject(appModel)
            }
        }
    }

    private var hero: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("\(opportunity.protocolName) · \(opportunity.asset) · \(opportunity.blockchain)")
                .font(.headline).foregroundStyle(AuraTheme.pinkBright)
            Text(opportunity.apyLabel)
                .font(.system(size: 38, weight: .bold, design: .rounded))
            Text("APY observado · fonte \(opportunity.dataSource.sourceLabel)")
                .font(.caption).foregroundStyle(.white.opacity(0.72))
        }
        .foregroundStyle(.white)
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AuraTheme.purple, in: RoundedRectangle(cornerRadius: 18))
        .accessibilityElement(children: .combine)
    }

    private var scoreLabel: String { opportunity.risk.score.map { String(format: "%.1f/10", $0) } ?? "Não informado" }
    private var auditLabel: String { opportunity.auditStatus == "audited" ? "Auditado" : (opportunity.auditStatus ?? "Não informado") }
}

private struct MetricCard: View {
    let title: String
    let value: String
    let detail: String
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.headline).foregroundStyle(AuraTheme.purple).minimumScaleFactor(0.72)
            Text(detail).font(.caption2).foregroundStyle(.secondary)
        }
        .padding(13)
        .frame(maxWidth: .infinity, minHeight: 102, alignment: .leading)
        .background(.white, in: RoundedRectangle(cornerRadius: 14))
        .overlay { RoundedRectangle(cornerRadius: 14).stroke(AuraTheme.border) }
        .accessibilityElement(children: .combine)
    }
}

struct SimulationView: View {
    let opportunity: Opportunity
    @EnvironmentObject private var appModel: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var amountText = "2000"
    @State private var submittedAmount: Double?
    @State private var decisionRecorded: DecisionRecord.Outcome?

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
                                .accessibilityLabel("Valor para simular em dólares")
                        }
                        .padding(16)
                        .background(.white, in: RoundedRectangle(cornerRadius: 14))
                        .overlay { RoundedRectangle(cornerRadius: 14).stroke(AuraTheme.pink, lineWidth: 2) }

                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack {
                                ForEach([500, 1000, 2000, 5000], id: \.self) { value in
                                    Button(value == 5000 ? "5 mil" : "\(value)") { amountText = String(value) }
                                        .buttonStyle(.bordered).buttonBorderShape(.capsule)
                                }
                            }
                        }

                        if let message = appModel.errorMessage {
                            ErrorCard(message: message) { simulate() }
                        }

                        if appModel.isLoading { ProgressView("Calculando cenários…").frame(maxWidth: .infinity) }

                        if let simulation = matchingSimulation {
                            SimulationResultCard(simulation: simulation)
                            decisionActions(amount: simulation.input.amount)
                        }

                        Button(matchingSimulation == nil ? "Projetar cenário" : "Atualizar cenário") { simulate() }
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
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder private func decisionActions(amount: Double) -> some View {
        if let outcome = decisionRecorded {
            Label(outcome == .saved ? "Cenário salvo no histórico" : "Decisão registrada como recusada", systemImage: "checkmark.circle.fill")
                .foregroundStyle(AuraTheme.success).font(.subheadline.bold())
                .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            VStack(spacing: 10) {
                Button("Salvar no histórico") {
                    appModel.recordDecision(for: opportunity, amount: amount, outcome: .saved)
                    decisionRecorded = .saved
                }
                .buttonStyle(AuraPrimaryButtonStyle())
                Button("Não seguir agora") {
                    appModel.recordDecision(for: opportunity, amount: amount, outcome: .declined)
                    decisionRecorded = .declined
                }
                .buttonStyle(.bordered)
                .buttonBorderShape(.capsule)
                Text("Salvar registra sua decisão; não conecta wallet e não movimenta fundos.")
                    .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
            }
        }
    }

    private var parsedAmount: Double? {
        let normalized = amountText.replacingOccurrences(of: ".", with: "").replacingOccurrences(of: ",", with: ".")
        guard let value = Double(normalized), value > 0 else { return nil }
        return value
    }
    private var matchingSimulation: Simulation? {
        guard let simulation = appModel.lastSimulation,
              submittedAmount == simulation.input.amount,
              simulation.opportunityId == opportunity.opportunityId else { return nil }
        return simulation
    }
    private func simulate() {
        guard let amount = parsedAmount else { return }
        submittedAmount = amount
        decisionRecorded = nil
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
                    Text("+ \(money(scenario.projectedYield))")
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
        .accessibilityElement(children: .combine)
    }

    private func horizonLabel(_ days: Int) -> String {
        switch days { case 30: return "Em 30 dias"; case 180: return "Em 6 meses"; case 365: return "Em 12 meses"; default: return "Em \(days) dias" }
    }
}

struct SettingsView: View {
    @EnvironmentObject private var appModel: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var confirmExit = false
    @State private var confirmDelete = false
    @State private var showPrivacy = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack(spacing: 12) {
                        AuraMark(size: 48)
                        VStack(alignment: .leading) {
                            Text(appModel.email).font(.headline)
                            Text("Conta verificada por OTP").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                Section("Perfil de risco") {
                    LabeledContent("Perfil", value: appModel.declaredProfile?.title ?? "Não declarado")
                    Button("Refazer questionário") {
                        dismiss()
                        appModel.flow = .riskQuiz
                    }
                }
                Section("Serviço") {
                    LabeledContent("API", value: appModel.apiClient.baseURL?.host ?? "Não configurada")
                    LabeledContent("Mercado", value: appModel.marketSource?.sourceLabel ?? "Indisponível")
                    Label("Apoio não custodial", systemImage: "checkmark.shield")
                }
                Section("Privacidade") {
                    ShareLink(item: exportText) { Label("Compartilhar meus dados locais", systemImage: "square.and.arrow.up") }
                    Button { showPrivacy = true } label: { Label("Como usamos seus dados", systemImage: "hand.raised") }
                    Button(role: .destructive) { confirmDelete = true } label: { Label("Apagar dados deste aparelho", systemImage: "trash") }
                }
                Section {
                    Button("Sair", role: .destructive) { confirmExit = true }
                }
            }
            .navigationTitle("Ajustes")
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Fechar") { dismiss() } } }
            .confirmationDialog("Sair da conta?", isPresented: $confirmExit, titleVisibility: .visible) {
                Button("Confirmar saída", role: .destructive) { Task { await appModel.logout() } }
                Button("Cancelar", role: .cancel) {}
            } message: { Text("A sessão também será encerrada no servidor.") }
            .confirmationDialog("Apagar dados locais?", isPresented: $confirmDelete, titleVisibility: .visible) {
                Button("Apagar e sair", role: .destructive) { Task { await appModel.deleteLocalData() } }
                Button("Cancelar", role: .cancel) {}
            } message: { Text("Remove sessão e histórico deste aparelho. A exclusão da conta no servidor ainda não está disponível.") }
            .sheet(isPresented: $showPrivacy) { PrivacyExplanationView() }
        }
    }

    private var exportText: String {
        let rows = appModel.decisions.map {
            "\($0.createdAt.formatted()) | \($0.protocolName) \($0.asset) | \($0.outcome.rawValue)"
        }
        return (["AuraFi - dados locais", "Conta: \(appModel.email)", "Perfil: \(appModel.declaredProfile?.title ?? "não declarado")"] + rows).joined(separator: "\n")
    }
}

private struct PrivacyExplanationView: View {
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            List {
                Label("OTP confirma o controle do e-mail.", systemImage: "envelope.badge.shield.half.filled")
                Label("Mensagens só vão ao hub após consentimento explícito.", systemImage: "message.badge")
                Label("Tokens de sessão ficam no Keychain do aparelho.", systemImage: "key.horizontal")
                Label("Histórico de decisões fica local neste MVP.", systemImage: "iphone")
                Label("A AuraFi nunca solicita seed phrase ou chave privada.", systemImage: "hand.raised.fill")
            }
            .navigationTitle("Privacidade")
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Fechar") { dismiss() } } }
        }
    }
}

private struct OpportunitySkeleton: View {
    var body: some View {
        VStack(spacing: 12) {
            ForEach(0..<2, id: \.self) { _ in
                RoundedRectangle(cornerRadius: 16)
                    .fill(.white.opacity(0.78))
                    .frame(height: 132)
                    .overlay { ProgressView().tint(AuraTheme.pink) }
            }
            Text("A Aura está olhando os dados mais recentes…")
                .font(.footnote).foregroundStyle(.secondary)
        }
        .accessibilityLabel("Carregando oportunidades")
    }
}

private struct EmptyStateCard: View {
    let title: String
    let message: String
    let icon: String
    let actionTitle: String
    let action: () -> Void
    var body: some View {
        VStack(spacing: 13) {
            Image(systemName: icon).font(.largeTitle).foregroundStyle(AuraTheme.pink)
            Text(title).font(.title3.bold()).multilineTextAlignment(.center)
            Text(message).font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
            Button(actionTitle, action: action).buttonStyle(.borderedProminent)
        }
        .padding(22)
        .frame(maxWidth: .infinity)
        .background(.white, in: RoundedRectangle(cornerRadius: 18))
        .accessibilityElement(children: .contain)
    }
}

private func compactMoney(_ value: Double) -> String {
    if value >= 1_000_000_000 { return String(format: "US$ %.1f bi", value / 1_000_000_000) }
    if value >= 1_000_000 { return String(format: "US$ %.0f mi", value / 1_000_000) }
    return money(value)
}

private func money(_ value: Double) -> String {
    value.formatted(.currency(code: "USD").precision(.fractionLength(2)))
}
