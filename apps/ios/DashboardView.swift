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
            ExploreView()
                .tag(MainTab.explore)
                .tabItem { Label("Explorar", systemImage: "square.grid.2x2") }
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

                        if appModel.marketRefreshFeedback == .refreshing {
                            MarketRefreshIndicator(feedback: .refreshing)
                        } else if appModel.isUsingCachedMarket {
                            MarketRefreshIndicator(feedback: .cached)
                        } else if let errorMessage = appModel.errorMessage {
                            ErrorCard(message: errorMessage) {
                                Task { await appModel.refreshOpportunities() }
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
                .refreshable { await appModel.refreshOpportunities() }
            }
            .toolbar {
                ToolbarItemGroup(placement: .topBarTrailing) {
                    Button { showSettings = true } label: { Image(systemName: "gearshape") }
                        .accessibilityLabel("Abrir ajustes")
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

    private var marketFreshnessSubtitle: String {
        if appModel.isRefreshingMarket {
            return "Consultando os serviços de mercado…"
        }
        if let source = appModel.marketSource,
           let time = shortTimeLabel(source.observedAt) ?? shortTimeLabel(source.retrievedAt) {
            let origin = source.usefulSourceLabel.map { " · \($0)" } ?? ""
            return "Atualizado às \(time)\(origin)"
        }
        return "Dados observados, riscos e fonte sempre visíveis."
    }

    private var opportunitiesContent: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Text("Oportunidades para você")
                    .font(.title2.bold())
                    .foregroundStyle(AuraTheme.purple)
                Spacer()
                Button("Ver todas") { appModel.selectedTab = .explore }
                    .font(.subheadline.weight(.semibold))
            }
            HStack(alignment: .firstTextBaseline) {
                Text(marketFreshnessSubtitle)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                Spacer()
                Button { Task { await appModel.refreshOpportunities() } } label: {
                    if appModel.isRefreshingMarket {
                        Label("Atualizando", systemImage: "arrow.clockwise")
                    } else {
                        Label("Atualizar", systemImage: "arrow.clockwise")
                    }
                }
                .font(.caption.weight(.semibold))
                .disabled(appModel.isRefreshingMarket)
                .accessibilityHint("Consulta novamente os serviços de mercado")
            }

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
        ) { Task { await appModel.refreshOpportunities() } }
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

private struct MarketRefreshIndicator: View {
    let feedback: MarketRefreshFeedback
    var body: some View {
        HStack(spacing: 7) {
            if feedback == .refreshing {
                ProgressView().controlSize(.small)
            } else {
                Image(systemName: feedback.systemImage)
            }
            Text(feedback.label)
                .font(.caption.weight(.medium))
        }
        .foregroundStyle(feedback == .cached ? Color.orange : Color.secondary)
        .padding(.horizontal, 10)
        .frame(minHeight: 32)
        .background(.white.opacity(0.72), in: Capsule())
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(feedback.label)
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
                        Text(metadataLine)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(opportunity.apyLabel)
                            .font(.system(size: 25, weight: .bold, design: .rounded))
                            .foregroundStyle(riskColor)
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 5) {
                        if let scoreLabel { Text("Score \(scoreLabel)").font(.caption.bold()) }
                        if let compactTVL { Text("TVL \(compactTVL)").font(.caption) }
                        if let secondaryTVL { Text(secondaryTVL).font(.caption2) }
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
        .accessibilityLabel(accessibilityDescription)
        .accessibilityHint("Abre detalhes e simulação")
    }

    private var riskColor: Color {
        switch opportunity.risk.level {
        case "high": return .orange
        case "low", "medium": return AuraTheme.success
        default: return .gray
        }
    }
    private var scoreLabel: String? {
        opportunity.risk.score.flatMap { $0.isFinite ? String(format: "%.1f", $0) : nil }
    }
    private var auditLabel: String? {
        switch opportunity.auditStatus {
        case "audited": return "Auditado"
        case "partially_audited": return "Auditoria parcial"
        case "not_verified": return "Auditoria não verificada"
        default: return nil
        }
    }
    private var metadataLine: String {
        [opportunity.blockchain, auditLabel].compactMap { $0 }.joined(separator: " · ")
    }
    private var compactTVL: String? {
        if let primary = opportunity.currencyDisplay?.primary,
           primary.value.isFinite,
           primary.value > 0 {
            return primary.displayCompact ?? compactMoney(primary.value, currency: primary.currency)
        }
        guard opportunity.tvl.value.isFinite, opportunity.tvl.value > 0 else { return nil }
        return opportunity.tvl.displayCompact
            ?? compactMoney(opportunity.tvl.value, currency: opportunity.tvl.currency ?? "USD")
    }
    private var secondaryTVL: String? {
        guard let secondary = opportunity.currencyDisplay?.secondary else { return nil }
        return secondary.displayCompact ?? compactMoney(secondary.value, currency: secondary.currency)
    }
    private var accessibilityDescription: String {
        var parts = [
            opportunity.protocolName,
            opportunity.asset,
            "APY \(opportunity.apyLabel)",
            "risco \(opportunity.riskLabel)"
        ]
        if let scoreLabel { parts.append("score \(scoreLabel)") }
        if let compactTVL { parts.append("TVL \(compactTVL)") }
        return parts.joined(separator: ", ")
    }
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
                List {
                    Group {
                        ChatBubble(
                            text: "Olá! Posso explicar riscos, comparar dados observados e ajudar com simulações educativas.",
                            isFromUser: false,
                            isFallback: false,
                            deliveryState: .received,
                            retry: nil
                        )
                        ForEach(appModel.conversationMessages) { item in
                            if !item.text.isEmpty {
                                ChatBubble(
                                    text: item.text,
                                    isFromUser: item.isFromUser,
                                    isFallback: item.isFallback,
                                    deliveryState: item.deliveryState,
                                    retry: item.deliveryState == .failed
                                        ? { Task { await appModel.retryMessage(id: item.id) } }
                                        : nil
                                )
                                .id(item.id)
                            }
                        }
                        if appModel.isSendingMessage {
                            TypingBubble()
                        }
                        Color.clear.frame(height: 1).id("chat-bottom")
                    }
                    .listRowSeparator(.hidden)
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets(top: 6, leading: 18, bottom: 6, trailing: 18))
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
                .scrollDismissesKeyboard(.interactively)
                .onChange(of: appModel.conversationMessages.count) {
                    withAnimation(.easeOut(duration: 0.2)) {
                        proxy.scrollTo("chat-bottom", anchor: .bottom)
                    }
                }
                .onChange(of: appModel.isSendingMessage) {
                    withAnimation(.easeOut(duration: 0.2)) {
                        proxy.scrollTo("chat-bottom", anchor: .bottom)
                    }
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
                Button("Explique os riscos") { send("Explique os riscos") }
                Button("Compare as opções") { send("Compare as opções") }
                Button("Como funciona?") { send("Como funciona?") }
            }
            .buttonStyle(.bordered)
            .tint(AuraTheme.pinkBright)
            .disabled(appModel.isSendingMessage)
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
    let deliveryState: ChatDeliveryState
    let retry: (() -> Void)?
    var body: some View {
        HStack {
            if isFromUser { Spacer(minLength: 44) }
            VStack(alignment: .leading, spacing: 5) {
                Text(isFromUser ? AttributedString(text) : Self.rendered(text))
                    .fixedSize(horizontal: false, vertical: true)
                if isFallback {
                    Label("Resposta segura de contingência", systemImage: "exclamationmark.triangle")
                        .font(.caption2).foregroundStyle(.orange)
                }
                if isFromUser {
                    deliveryStatus
                }
            }
            .padding(13)
            .background(isFromUser ? AuraTheme.pinkBright : AuraTheme.purpleSoft, in: RoundedRectangle(cornerRadius: 16))
            .foregroundStyle(.white)
            if !isFromUser { Spacer(minLength: 44) }
        }
        .accessibilityElement(children: retry == nil ? .combine : .contain)
        .accessibilityLabel("\(isFromUser ? "Você" : "Aura"): \(text). \(deliveryAccessibilityLabel)")
    }

    @ViewBuilder private var deliveryStatus: some View {
        switch deliveryState {
        case .sending:
            HStack(spacing: 5) {
                ProgressView().controlSize(.mini).tint(.white)
                Text("Enviando…")
            }
            .font(.caption2)
            .foregroundStyle(.white.opacity(0.8))
        case .sent:
            Label("Enviada", systemImage: "checkmark")
                .font(.caption2)
                .foregroundStyle(.white.opacity(0.8))
        case .delivered:
            Label("Entregue", systemImage: "checkmark.circle.fill")
                .font(.caption2)
                .foregroundStyle(.white.opacity(0.85))
        case .failed:
            HStack(spacing: 8) {
                Label("Não enviada", systemImage: "exclamationmark.circle")
                if let retry {
                    Button("Tentar novamente", action: retry)
                        .font(.caption2.bold())
                        .buttonStyle(.plain)
                        .underline()
                }
            }
            .font(.caption2)
            .foregroundStyle(.white)
        case .received:
            EmptyView()
        }
    }

    static func rendered(_ raw: String) -> AttributedString {
        let options = AttributedString.MarkdownParsingOptions(
            interpretedSyntax: .inlineOnlyPreservingWhitespace
        )
        return (try? AttributedString(markdown: raw, options: options)) ?? AttributedString(raw)
    }

    private var deliveryAccessibilityLabel: String {
        switch deliveryState {
        case .sending: return "Enviando"
        case .sent: return "Enviada"
        case .delivered: return "Entregue"
        case .failed: return "Falha no envio; é possível tentar novamente"
        case .received: return "Recebida"
        }
    }
}

private struct TypingBubble: View {
    @State private var animating = false

    var body: some View {
        HStack {
            HStack(spacing: 5) {
                ForEach(0..<3, id: \.self) { index in
                    Circle()
                        .fill(.white.opacity(0.85))
                        .frame(width: 7, height: 7)
                        .scaleEffect(animating ? 1.0 : 0.5)
                        .opacity(animating ? 1.0 : 0.4)
                        .animation(.easeInOut(duration: 0.6).repeatForever().delay(Double(index) * 0.2), value: animating)
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(AuraTheme.purpleSoft, in: RoundedRectangle(cornerRadius: 16))
            Spacer(minLength: 44)
        }
        .onAppear { animating = true }
        .accessibilityLabel("A Aura está preparando uma resposta")
    }
}

struct ExploreView: View {
    enum RiskFilter: String, CaseIterable, Identifiable {
        case all = "Todos", low = "Baixo", medium = "Médio", high = "Alto"
        var id: String { rawValue }
        var level: String? {
            switch self {
            case .all: return nil
            case .low: return "low"
            case .medium: return "medium"
            case .high: return "high"
            }
        }
    }

    @EnvironmentObject private var appModel: AppModel
    @State private var search = ""
    @State private var riskFilter: RiskFilter = .all
    @State private var networkFilter: String?
    @State private var selectedOpportunity: Opportunity?

    var body: some View {
        NavigationStack {
            ZStack {
                AuraTheme.lavender.ignoresSafeArea()
                VStack(spacing: 0) {
                    filters
                    if filtered.isEmpty {
                        EmptyStateCard(
                            title: appModel.opportunities.isEmpty ? "Catálogo indisponível" : "Nenhum resultado",
                            message: appModel.opportunities.isEmpty ? "Atualize os dados para explorar oportunidades." : "Ajuste a busca ou os filtros.",
                            icon: "square.grid.2x2",
                            actionTitle: appModel.opportunities.isEmpty ? "Atualizar" : "Limpar filtros"
                        ) {
                            if appModel.opportunities.isEmpty {
                                Task { await appModel.refreshOpportunities() }
                            } else {
                                search = ""; riskFilter = .all; networkFilter = nil
                            }
                        }
                        .padding(18)
                        Spacer(minLength: 0)
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
                        .refreshable { await appModel.refreshOpportunities() }
                    }
                }
            }
            .navigationTitle("Explorar")
            .searchable(text: $search, prompt: "Protocolo, ativo ou rede")
            .sheet(item: $selectedOpportunity) { item in
                OpportunityDetailView(opportunity: item).environmentObject(appModel)
            }
        }
    }

    private var filters: some View {
        VStack(spacing: 8) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(RiskFilter.allCases) { option in
                        chip(option.rawValue, selected: riskFilter == option) { riskFilter = option }
                    }
                }
                .padding(.horizontal, 18)
            }
            if networks.count > 1 {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        chip("Todas as redes", selected: networkFilter == nil) { networkFilter = nil }
                        ForEach(networks, id: \.self) { network in
                            chip(network, selected: networkFilter == network) {
                                networkFilter = networkFilter == network ? nil : network
                            }
                        }
                    }
                    .padding(.horizontal, 18)
                }
            }
        }
        .padding(.vertical, 10)
    }

    private func chip(_ title: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.caption.weight(.semibold))
                .padding(.horizontal, 13)
                .frame(minHeight: 32)
                .background(selected ? AuraTheme.pink : Color.white, in: Capsule())
                .foregroundStyle(selected ? .white : AuraTheme.purple)
                .overlay { Capsule().stroke(AuraTheme.border, lineWidth: selected ? 0 : 1) }
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private var networks: [String] {
        var seen = Set<String>()
        var result: [String] = []
        for opportunity in appModel.opportunities {
            let name = opportunity.blockchain.trimmingCharacters(in: .whitespacesAndNewlines)
            if !name.isEmpty && seen.insert(name.lowercased()).inserted {
                result.append(name)
            }
        }
        return result
    }

    private var filtered: [Opportunity] {
        let query = search.localizedLowercase
        return appModel.opportunities.filter { opportunity in
            (riskFilter.level == nil || opportunity.risk.level == riskFilter.level)
                && (networkFilter == nil || opportunity.blockchain.caseInsensitiveCompare(networkFilter!) == .orderedSame)
                && (query.isEmpty
                    || opportunity.protocolName.localizedLowercase.contains(query)
                    || opportunity.asset.localizedLowercase.contains(query)
                    || opportunity.blockchain.localizedLowercase.contains(query))
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
                                message: "Escolha uma oportunidade em Explorar e simule um cenário para registrar sua primeira decisão.",
                                icon: "clock.arrow.circlepath",
                                actionTitle: "Explorar oportunidades"
                            ) { appModel.selectedTab = .explore }
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
                Text("\(decision.protocolName) · \(decision.asset) · \(assetAmount(decision.amount, asset: decision.asset))")
                    .font(.headline)
                Text(decision.outcome == .saved ? "✓ Cenário salvo para acompanhar" : "○ Você decidiu não seguir agora")
                    .font(.caption).foregroundStyle(decision.outcome == .saved ? AuraTheme.success : Color.secondary)
            }
            Spacer()
            if decision.projectedYield > 0 {
                Text("+ \(assetAmount(decision.projectedYield, asset: decision.asset))")
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
    @State private var enrichedOpportunity: Opportunity?
    @State private var isLoadingEnrichment = false
    @State private var enrichmentError: String?

    var body: some View {
        NavigationStack {
            ZStack {
                AuraTheme.lavender.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        hero
                        OpportunityExplainerCard(opportunity: currentOpportunity)
                        Text("Números observados").font(.title3.bold()).foregroundStyle(AuraTheme.purple)
                        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                            MetricCard(
                                title: "RISCO",
                                value: scoreLabel ?? currentOpportunity.riskLabel,
                                detail: currentOpportunity.risk.isEstimated
                                    ? "estimado por APY, TVL e auditoria"
                                    : (scoreLabel != nil ? currentOpportunity.riskLabel : nil)
                            )
                            if let primaryTVL {
                                MetricCard(title: "TVL", value: primaryTVL, detail: "total depositado no protocolo")
                            }
                            if let auditLabel {
                                MetricCard(title: "AUDITORIA", value: auditLabel, detail: nil)
                            }
                            if !currentOpportunity.blockchain.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                                MetricCard(title: "REDE", value: currentOpportunity.blockchain, detail: liquidityLabel)
                            }
                        }
                        if !currentOpportunity.risk.dimensions.isEmpty {
                            RiskDimensionsView(dimensions: currentOpportunity.risk.dimensions)
                        }
                        if let history = currentOpportunity.history,
                           history.status == "available",
                           !history.points.isEmpty {
                            OpportunityHistoryView(history: history)
                        } else if isLoadingEnrichment {
                            HStack(spacing: 8) {
                                ProgressView().controlSize(.small)
                                Text("Buscando histórico e valores em reais…")
                            }
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        } else if let enrichmentError {
                            HStack(alignment: .center, spacing: 10) {
                                Image(systemName: "wifi.exclamationmark")
                                    .foregroundStyle(Color.orange)
                                Text(enrichmentError)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                Spacer(minLength: 4)
                                Button("Tentar novamente") {
                                    Task { await loadEnrichment() }
                                }
                                .font(.caption.weight(.semibold))
                            }
                            .padding(12)
                            .background(.white.opacity(0.72), in: RoundedRectangle(cornerRadius: 12))
                            .accessibilityElement(children: .combine)
                        }
                        DataSourceBanner(source: currentOpportunity.dataSource)
                        if let fxLabel {
                            Text(fxLabel)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
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
                SimulationView(opportunity: currentOpportunity).environmentObject(appModel)
            }
            .task(id: opportunity.opportunityId) { await loadEnrichment() }
        }
    }

    private var hero: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text([currentOpportunity.protocolName, currentOpportunity.asset, currentOpportunity.blockchain]
                .filter { !$0.isEmpty }
                .joined(separator: " · "))
                .font(.headline).foregroundStyle(AuraTheme.pinkBright)
            Text(currentOpportunity.apyLabel)
                .font(.system(size: 38, weight: .bold, design: .rounded))
            if let source = currentOpportunity.dataSource.usefulSourceLabel {
                Text("APY observado · fonte \(source)")
                    .font(.caption).foregroundStyle(.white.opacity(0.72))
            }
        }
        .foregroundStyle(.white)
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AuraTheme.purple, in: RoundedRectangle(cornerRadius: 18))
        .accessibilityElement(children: .combine)
    }

    private var currentOpportunity: Opportunity { enrichedOpportunity ?? opportunity }
    private var scoreLabel: String? {
        currentOpportunity.risk.score.flatMap { $0.isFinite ? String(format: "%.1f", $0) : nil }
    }
    private var auditLabel: String? {
        switch currentOpportunity.auditStatus {
        case "audited": return "Auditado"
        case "partially_audited": return "Parcial"
        case "not_verified": return "Não verificada"
        default: return nil
        }
    }
    private var liquidityLabel: String? {
        switch currentOpportunity.liquidity.level {
        case "high": return "Liquidez alta"
        case "medium": return "Liquidez média"
        case "low": return "Liquidez baixa"
        default: return nil
        }
    }
    private var primaryTVL: String? {
        if let display = currentOpportunity.currencyDisplay {
            return display.primary.displayCompact ?? compactMoney(display.primary.value, currency: display.primary.currency)
        }
        guard currentOpportunity.tvl.value.isFinite, currentOpportunity.tvl.value > 0 else { return nil }
        return currentOpportunity.tvl.displayCompact ?? compactMoney(currentOpportunity.tvl.value, currency: currentOpportunity.tvl.currency ?? "USD")
    }
    private var secondaryTVL: String? {
        if let secondary = currentOpportunity.currencyDisplay?.secondary {
            return secondary.display ?? money(secondary.value, currency: secondary.currency)
        }
        return nil
    }
    private var fxLabel: String? {
        guard let display = currentOpportunity.currencyDisplay,
              display.primary.currency.uppercased() == "BRL",
              display.fx.status == "available" || display.fx.status == "cached"
        else { return nil }
        let source = display.fx.source == "bcb_ptax" ? "PTAX do Banco Central" : display.fx.source
        return "Conversão informativa por \(source)\(display.fx.isStale == true ? " · cotação em cache" : "")"
    }

    private func loadEnrichment() async {
        guard enrichedOpportunity == nil, !isLoadingEnrichment else { return }
        enrichmentError = nil
        isLoadingEnrichment = true
        defer { isLoadingEnrichment = false }
        do {
            enrichedOpportunity = try await appModel.opportunityDetail(
                for: opportunity.opportunityId
            )
        } catch {
            enrichmentError = (error as? LocalizedError)?.errorDescription
                ?? "Não foi possível atualizar histórico e conversão agora."
        }
    }
}

private struct OpportunityExplainerCard: View {
    let opportunity: Opportunity

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Entenda esta oportunidade")
                .font(.headline)
                .foregroundStyle(AuraTheme.purple)
            ForEach(points, id: \.title) { point in
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: point.icon)
                        .font(.subheadline)
                        .foregroundStyle(AuraTheme.pink)
                        .frame(width: 22)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(point.title).font(.subheadline.weight(.semibold)).foregroundStyle(AuraTheme.purple)
                        Text(point.detail).font(.caption).foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            Text("Compare com outras oportunidades e converse com a Aura antes de decidir. Você decide; a AuraFi explica.")
                .font(.caption.italic())
                .foregroundStyle(AuraTheme.pink)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AuraTheme.pink.opacity(0.05), in: RoundedRectangle(cornerRadius: 16))
        .overlay { RoundedRectangle(cornerRadius: 16).stroke(AuraTheme.pink.opacity(0.25)) }
        .accessibilityElement(children: .contain)
    }

    private struct Point { let icon: String; let title: String; let detail: String }

    private var points: [Point] {
        var result: [Point] = [
            Point(
                icon: "percent",
                title: "Rendimento de \(opportunity.apyLabel)",
                detail: "É quanto renderia em um ano no ritmo de agora. Esse número muda com o mercado e não é garantido."
            ),
            Point(
                icon: "building.columns",
                title: "Tamanho do protocolo (TVL)",
                detail: "É quanto de dinheiro já está depositado aqui. Quanto maior, mais gente usando e mais fácil de entrar e sair. Não elimina o risco, mas ajuda."
            )
        ]
        switch opportunity.risk.level {
        case "low", "medium", "high":
            result.append(Point(
                icon: "shield.lefthalf.filled",
                title: "Risco \(opportunity.riskLabel.lowercased())",
                detail: "Considera o contrato, a liquidez e o ativo por trás. Em geral, risco maior vem com chance de ganho maior e de perda maior."
            ))
        default:
            break
        }
        result.append(Point(
            icon: "checkmark.seal",
            title: auditTitle,
            detail: "Uma auditoria diminui, mas não elimina, o risco de falha no contrato. \"Não informada\" quer dizer que a fonte não trouxe esse dado."
        ))
        return result
    }

    private var auditTitle: String {
        switch opportunity.auditStatus {
        case "audited": return "Auditado por terceiros"
        case "partially_audited": return "Auditoria parcial"
        case "not_verified": return "Auditoria não verificada"
        default: return "Auditoria não informada"
        }
    }
}

private struct MetricCard: View {
    let title: String
    let value: String
    let detail: String?
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.caption).foregroundStyle(.secondary)
            Text(value).font(.headline).foregroundStyle(AuraTheme.purple).minimumScaleFactor(0.72)
            if let detail, !detail.isEmpty {
                Text(detail).font(.caption2).foregroundStyle(.secondary)
            }
        }
        .padding(13)
        .frame(maxWidth: .infinity, minHeight: 102, alignment: .leading)
        .background(.white, in: RoundedRectangle(cornerRadius: 14))
        .overlay { RoundedRectangle(cornerRadius: 14).stroke(AuraTheme.border) }
        .accessibilityElement(children: .combine)
    }
}

private struct RiskDimensionsView: View {
    let dimensions: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            Text("Fatores observados").font(.headline).foregroundStyle(AuraTheme.purple)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack {
                    ForEach(dimensions, id: \.self) { dimension in
                        Text(label(for: dimension))
                            .font(.caption.weight(.medium))
                            .padding(.horizontal, 10)
                            .frame(minHeight: 32)
                            .background(.white, in: Capsule())
                    }
                }
            }
        }
    }

    private func label(for dimension: String) -> String {
        switch dimension {
        case "smart_contract": return "Contrato inteligente"
        case "liquidity": return "Liquidez"
        case "volatility": return "Volatilidade"
        case "underlying_asset": return "Ativo subjacente"
        case "counterparty": return "Contraparte"
        case "data_quality": return "Qualidade dos dados"
        default: return dimension.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }
}

private struct OpportunityHistoryView: View {
    let history: OpportunityHistory

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Histórico observado").font(.headline).foregroundStyle(AuraTheme.purple)
            ForEach(history.windows.keys.sorted(by: windowOrder), id: \.self) { key in
                if let window = history.windows[key], let apy = window.apy {
                    HStack {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(key.uppercased()).font(.caption.bold()).foregroundStyle(.secondary)
                            if let average = apy.average {
                                Text("Média \(average.formatted(.number.precision(.fractionLength(2))))%")
                                    .font(.subheadline.weight(.semibold))
                            }
                        }
                        Spacer()
                        if let change = apy.changePercentagePoints {
                            Text("\(change >= 0 ? "+" : "")\(change.formatted(.number.precision(.fractionLength(2)))) p.p.")
                                .font(.subheadline.bold())
                                .foregroundStyle(change > 0 ? AuraTheme.success : change < 0 ? Color.orange : Color.secondary)
                        }
                    }
                    .padding(12)
                    .background(.white, in: RoundedRectangle(cornerRadius: 12))
                }
            }
            Text("Série histórica observada; não representa retorno realizado nem futuro.")
                .font(.caption2)
                .foregroundStyle(.secondary)
            if let sourceLabel {
                Text("Fonte do histórico: \(sourceLabel)\(history.dataSource.isStale == true ? " · pode estar desatualizado" : "")")
                    .font(.caption2)
                    .foregroundStyle(history.dataSource.isStale == true ? Color.orange : Color.secondary)
            }
        }
    }

    private func windowOrder(_ lhs: String, _ rhs: String) -> Bool {
        (history.windows[lhs]?.windowDays ?? .max) < (history.windows[rhs]?.windowDays ?? .max)
    }

    private var sourceLabel: String? {
        if let label = history.dataSource.serverSourceLabel?.trimmingCharacters(in: .whitespacesAndNewlines),
           !label.isEmpty {
            return label
        }
        guard let raw = history.dataSource.source?.trimmingCharacters(in: .whitespacesAndNewlines),
              !raw.isEmpty
        else { return nil }
        return raw.caseInsensitiveCompare("defillama") == .orderedSame ? "DeFiLlama" : raw
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
                            Text(opportunity.asset).foregroundStyle(.secondary)
                            TextField("2.000,00", text: $amountText)
                                .keyboardType(.decimalPad)
                                .font(.system(size: 30, weight: .bold, design: .rounded))
                                .accessibilityLabel("Valor para simular em \(opportunity.asset)")
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
                    Text("+ \(gainLabel(scenario, principal: simulation.input.amount))")
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
                if appModel.biometricsAvailable {
                    Section("Segurança") {
                        Toggle(isOn: Binding(
                            get: { appModel.biometricLockEnabled },
                            set: { appModel.setBiometricLock($0) }
                        )) {
                            Label("Bloquear com \(appModel.biometricKind.label)", systemImage: appModel.biometricKind.systemImage)
                        }
                        Text("Ao abrir o AuraFi, pediremos \(appModel.biometricKind.label) antes de mostrar seus dados. O código do aparelho continua como alternativa.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
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
                    LabeledContent("Mercado", value: appModel.marketSource?.usefulSourceLabel ?? "Indisponível")
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

private func compactMoney(_ value: Double, currency: String) -> String {
    let code = currency.uppercased()
    let symbol = code == "BRL" ? "R$" : code == "USD" ? "US$" : code
    if value >= 1_000_000_000 { return String(format: "%@ %.1f bi", symbol, value / 1_000_000_000) }
    if value >= 1_000_000 { return String(format: "%@ %.0f mi", symbol, value / 1_000_000) }
    return money(value, currency: code)
}

private func money(_ value: Double, currency: String = "USD") -> String {
    value.formatted(
        .currency(code: currency.uppercased())
            .locale(Locale(identifier: "pt_BR"))
            .precision(.fractionLength(0...2))
    )
}

private func assetAmount(_ value: Double, asset: String) -> String {
    "\(value.formatted(.number.locale(Locale(identifier: "pt_BR")).precision(.fractionLength(0...2)))) \(asset)"
}

private func shortTimeLabel(_ iso: String) -> String? {
    let trimmed = iso.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty else { return nil }
    let withFraction = ISO8601DateFormatter()
    withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    let plain = ISO8601DateFormatter()
    plain.formatOptions = [.withInternetDateTime]
    guard let date = withFraction.date(from: trimmed) ?? plain.date(from: trimmed) else {
        return nil
    }
    return date.formatted(.dateTime.hour().minute().locale(Locale(identifier: "pt_BR")))
}

private func gainLabel(_ scenario: SimulationScenario, principal: Double) -> String {
    scenario.projectedGainDisplay ?? assetAmount(scenario.projectedValue - principal, asset: scenario.currency)
}
