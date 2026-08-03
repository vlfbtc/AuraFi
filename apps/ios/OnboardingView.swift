import SwiftUI

struct OnboardingView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var email = ""
    @State private var profileToRetry: RiskProfile?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    switch appModel.flow {
                    case .welcome:
                        welcomeContent
                    case .otp:
                        otpContent
                    case .declaredProfile:
                        profileContent
                    case .dashboard:
                        EmptyView()
                    }
                }
                .padding(.horizontal)
                .padding(.vertical, 28)
            }
            .scrollIndicators(.hidden)
            .navigationTitle("AuraFi")
            .navigationBarTitleDisplayMode(.inline)
        }
        .onAppear {
            if email.isEmpty { email = appModel.email }
        }
    }

    private var welcomeContent: some View {
        VStack(alignment: .leading, spacing: 24) {
            VStack(alignment: .leading, spacing: 12) {
                Image(systemName: "sparkles")
                    .font(.system(size: 32, weight: .semibold))
                    .foregroundStyle(.indigo)
                    .accessibilityHidden(true)

                Text("Decida com mais clareza")
                    .font(.largeTitle.weight(.bold))
                    .fixedSize(horizontal: false, vertical: true)

                Text("Explore oportunidades DeFi com contexto, riscos e dados atualizados.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            VStack(alignment: .leading, spacing: 12) {
                Text("E-mail")
                    .font(.headline)

                TextField("voce@exemplo.com", text: $email)
                    .textContentType(.emailAddress)
                    .keyboardType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .padding(.horizontal, 14)
                    .frame(minHeight: 52)
                    .background(.secondary.opacity(0.10), in: RoundedRectangle(cornerRadius: 12))
                    .accessibilityLabel("E-mail")
                    .accessibilityHint("Usaremos este endereco para confirmar seu acesso por codigo.")

                Text("Voce recebera um codigo para confirmar sua conta AuraFi.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if let errorMessage = appModel.errorMessage {
                ErrorCard(message: errorMessage) {
                    Task { await appModel.requestOTP(for: email) }
                }
            }

            Button {
                Task { await appModel.requestOTP(for: email) }
            } label: {
                Group {
                    if appModel.isLoading {
                        ProgressView().tint(.white)
                    } else {
                        Text("Receber codigo")
                    }
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(!isValidEmail || appModel.isLoading)

            DisclaimerCard()
        }
    }

    private var otpContent: some View {
        VStack(alignment: .leading, spacing: 24) {
            VStack(alignment: .leading, spacing: 10) {
                Text("Confirme seu acesso")
                    .font(.largeTitle.weight(.bold))
                Text("Digite o codigo enviado para \(appModel.email).")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            TextField("Codigo de acesso", text: $appModel.otpCode)
                .keyboardType(.numberPad)
                .textContentType(.oneTimeCode)
                .padding(.horizontal, 14)
                .frame(minHeight: 52)
                .background(.secondary.opacity(0.10), in: RoundedRectangle(cornerRadius: 12))
                .accessibilityLabel("Codigo de acesso")

            if let deliveryMessage = appModel.deliveryMessage {
                Text(deliveryMessage)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if let errorMessage = appModel.errorMessage {
                ErrorCard(message: errorMessage) {
                    Task { await appModel.verifyOTP() }
                }
            }

            Button {
                Task { await appModel.verifyOTP() }
            } label: {
                Group {
                    if appModel.isLoading {
                        ProgressView().tint(.white)
                    } else {
                        Text("Confirmar e continuar")
                    }
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(appModel.otpCode.trimmingCharacters(in: .whitespacesAndNewlines).count < 4 || appModel.isLoading)

            Button("Usar outro e-mail") {
                appModel.restart()
                email = ""
            }
            .frame(maxWidth: .infinity)
            .disabled(appModel.isLoading)

            DisclaimerCard()
        }
    }

    private var profileContent: some View {
        VStack(alignment: .leading, spacing: 22) {
            VStack(alignment: .leading, spacing: 10) {
                Text("Seu perfil declarado")
                    .font(.largeTitle.weight(.bold))
                    .fixedSize(horizontal: false, vertical: true)

                Text("Escolha a opcao que melhor descreve sua preferencia hoje. Esta e uma declaracao sua; a AuraFi nao calcula nem infere o perfil.")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if let errorMessage = appModel.errorMessage {
                ErrorCard(message: errorMessage) {
                    if let profileToRetry {
                        Task { await appModel.declare(profile: profileToRetry) }
                    }
                }
            }

            VStack(spacing: 12) {
                ForEach(RiskProfile.allCases) { profile in
                    Button {
                        profileToRetry = profile
                        Task { await appModel.declare(profile: profile) }
                    } label: {
                        HStack(alignment: .top, spacing: 14) {
                            Image(systemName: icon(for: profile))
                                .font(.title3)
                                .frame(width: 28)
                                .foregroundStyle(.indigo)

                            VStack(alignment: .leading, spacing: 5) {
                                Text(profile.title)
                                    .font(.headline)
                                Text(profile.description)
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }

                            Spacer(minLength: 8)
                            Image(systemName: "chevron.right")
                                .foregroundStyle(.secondary)
                                .accessibilityHidden(true)
                        }
                        .frame(maxWidth: .infinity, minHeight: 76, alignment: .leading)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.bordered)
                    .disabled(appModel.isLoading)
                    .accessibilityLabel("Perfil \(profile.title)")
                    .accessibilityHint("Declara este perfil e abre seu dashboard")
                }
            }

            if appModel.isLoading {
                ProgressView("Salvando seu perfil...")
                    .frame(maxWidth: .infinity, alignment: .center)
            }

            Text("Perfil para \(appModel.email). Voce podera declarar outro perfil quando quiser.")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            DisclaimerCard()
        }
    }

    private var isValidEmail: Bool {
        let value = email.trimmingCharacters(in: .whitespacesAndNewlines)
        return value.contains("@") && value.contains(".")
    }

    private func icon(for profile: RiskProfile) -> String {
        switch profile {
        case .conservative: return "shield"
        case .moderate: return "scale.3d"
        case .aggressive: return "chart.line.uptrend.xyaxis"
        }
    }
}
