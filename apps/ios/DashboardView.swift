import SwiftUI

struct DashboardView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var selectedOpportunity: Opportunity?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    header

                    if let errorMessage = appModel.errorMessage {
                        ErrorCard(message: errorMessage) {
                            Task { await appModel.loadOpportunities() }
                        }
                    }

                    if appModel.isLoading && appModel.opportunities.isEmpty {
                        ProgressView("Atualizando oportunidades...")
                            .frame(maxWidth: .infinity, alignment: .center)
                            .padding(.vertical, 24)
                    } else if appModel.opportunities.isEmpty {
                        emptyState
                    } else {
                        opportunitiesContent
                    }

                    DisclaimerCard()
                }
                .padding(.horizontal)
                .padding(.vertical, 20)
            }
            .scrollIndicators(.hidden)
            .navigationTitle("Dashboard")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task { await appModel.loadOpportunities() }
                    } label: {
                        if appModel.isLoading {
                            ProgressView()
                        } else {
                            Image(systemName: "arrow.clockwise")
                        }
                    }
                    .accessibilityLabel("Atualizar oportunidades")
                    .disabled(appModel.isLoading)
                }
            }
            .sheet(item: $selectedOpportunity) { opportunity in
                OpportunityDetailView(opportunity: opportunity)
            }
        }
        .task {
            await appModel.loadOpportunities()
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Olá, \(appModel.email)")
                .font(.largeTitle.weight(.bold))

            if let profile = appModel.declaredProfile {
                Label("Perfil declarado: \(profile.title)", systemImage: "checkmark.seal")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.indigo)
            }

            Text("Veja oportunidades com contexto de mercado e momento de atualização.")
                .font(.body)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityElement(children: .combine)
    }

    private var opportunitiesContent: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("Oportunidades")
                    .font(.title2.weight(.bold))
                Spacer()
                if appModel.isLoading {
                    ProgressView()
                        .accessibilityLabel("Atualizando")
                }
            }

            ForEach(appModel.opportunities) { opportunity in
                opportunityCard(for: opportunity)
            }
        }
    }

    private var emptyState: some View {
        ContentUnavailableView {
            Label("Nenhuma oportunidade disponível", systemImage: "chart.bar.xaxis")
        } description: {
            Text("Tente atualizar novamente quando o serviço estiver disponível.")
        } actions: {
            Button("Atualizar") {
                Task { await appModel.loadOpportunities() }
            }
            .buttonStyle(.borderedProminent)
            .disabled(appModel.isLoading)
        }
    }

    private func opportunityCard(for opportunity: Opportunity) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(opportunity.protocolName)
                        .font(.title3.weight(.semibold))
                    Text("\(opportunity.pool) • \(opportunity.blockchain)")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }

                Spacer(minLength: 8)
                Text(opportunity.riskLabel)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.indigo)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 5)
                    .background(.indigo.opacity(0.12), in: Capsule())
                    .accessibilityLabel("Risco \(opportunity.riskLabel)")
            }

            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: 14) {
                metric(title: "Ativo", value: opportunity.asset)
                metric(title: "APY", value: opportunity.apyLabel)
                metric(title: "TVL", value: opportunity.tvlLabel)
                metric(title: "Liquidez", value: liquidityLabel(opportunity.liquidity.level))
            }

            DataSourceBanner(source: opportunity.dataSource)

            VStack(alignment: .leading, spacing: 4) {
                Text("Origem: \(opportunity.dataSource.sourceLabel)")
                Text("Observado em: \(opportunity.dataSource.observedAt)")
                Text("Atualizado em: \(opportunity.dataSource.retrievedAt)")
            }
            .font(.footnote)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)

            Button("Ver detalhes") {
                selectedOpportunity = opportunity
            }
            .buttonStyle(.bordered)
            .frame(maxWidth: .infinity)
            .controlSize(.large)
        }
        .padding()
        .background(.background, in: RoundedRectangle(cornerRadius: 18))
        .overlay {
            RoundedRectangle(cornerRadius: 18)
                .stroke(.secondary.opacity(0.20), lineWidth: 1)
        }
        .accessibilityElement(children: .contain)
    }

    private func metric(title: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.subheadline.weight(.semibold))
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityElement(children: .combine)
    }

    private func liquidityLabel(_ value: String) -> String {
        switch value.lowercased() {
        case "high": return "Alta"
        case "medium": return "Média"
        case "low": return "Baixa"
        default: return value
        }
    }
}

struct OpportunityDetailView: View {
    let opportunity: Opportunity
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text(opportunity.protocolName)
                        .font(.largeTitle.weight(.bold))

                    Text("\(opportunity.pool) • \(opportunity.asset) • \(opportunity.blockchain)")
                        .font(.body)
                        .foregroundStyle(.secondary)

                    detailRow("APY", opportunity.apyLabel)
                    detailRow("TVL", opportunity.tvlLabel)
                    detailRow("Liquidez", opportunity.liquidity.level)
                    detailRow("Risco", "\(opportunity.riskLabel) • \(opportunity.risk.dimensions.joined(separator: ", "))")
                    if let auditStatus = opportunity.auditStatus, !auditStatus.isEmpty {
                        detailRow("Auditoria", auditStatus)
                    }
                    detailRow("Origem", opportunity.dataSource.sourceLabel)
                    detailRow("Observado em", opportunity.dataSource.observedAt)
                    detailRow("Atualizado em", opportunity.dataSource.retrievedAt)

                    DataSourceBanner(source: opportunity.dataSource)

                    Text(opportunity.disclaimer)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)

                    DisclaimerCard()
                }
                .padding()
            }
            .navigationTitle("Detalhes")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Fechar") { dismiss() }
                }
            }
        }
    }

    private func detailRow(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.body)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}
