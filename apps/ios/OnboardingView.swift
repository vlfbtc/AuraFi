import SwiftUI

struct OnboardingView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var email = ""
    @State private var questionIndex = 0
    @State private var answers: [String: RiskOption] = [:]

    // Mesmas perguntas e mesma pontuação do site (RiskQuestionnaire.swift).
    private let questions = RiskQuestionnaire.questions

    var body: some View {
        ZStack {
            AuraTheme.lavender.ignoresSafeArea()
            switch appModel.flow {
            case .welcome: welcome
            case .login: login
            case .otp: otp
            case .riskQuiz: quiz
            case .dashboard: EmptyView()
            }
        }
        .onAppear { if email.isEmpty { email = appModel.email } }
    }

    private var welcome: some View {
        VStack(spacing: 0) {
            Spacer(minLength: 46)
            AuraMark(size: 72)
            Text("AuraFi")
                .font(.system(size: 30, weight: .bold, design: .rounded))
                .foregroundStyle(AuraTheme.purple)
                .padding(.top, 14)
            Text("Clareza para investir.")
                .font(.subheadline.italic())
                .foregroundStyle(AuraTheme.pink)
            Spacer()
            VStack(alignment: .leading, spacing: 12) {
                Text("Suas stablecoins\npodem render mais.")
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                    .foregroundStyle(AuraTheme.purple)
                Text("Decisões em DeFi com a clareza de uma conversa em português.")
                    .font(.body)
                    .foregroundStyle(AuraTheme.purple.opacity(0.78))
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            Spacer()
            if let notice = appModel.accountNotice {
                // Ocupa o lugar do ícone decorativo para não empurrar o restante da tela.
                accountNoticeBanner(notice)
            } else {
                Image(systemName: "message.fill")
                    .font(.system(size: 68))
                    .foregroundStyle(AuraTheme.pink.opacity(0.88))
                    .accessibilityHidden(true)
            }
            Spacer()
            Button("Começar agora") {
                appModel.accountNotice = nil
                appModel.flow = .login
            }
            .buttonStyle(AuraPrimaryButtonStyle())
            Text("A AuraFi apoia sua decisão e nunca movimenta seus recursos.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.top, 14)
        }
        .padding(.horizontal, 28)
        .padding(.bottom, 24)
    }

    private var login: some View {
        onboardingScroll(title: "Vamos começar", subtitle: "Entre com seu e-mail para receber um código seguro.") {
            fieldLabel("E-mail")
            TextField("voce@exemplo.com", text: $email)
                .textContentType(.emailAddress)
                .keyboardType(.emailAddress)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .auraField()
                .onChange(of: email) { appModel.clearOTPError() }

            otpErrorCard(phase: .request)

            Button {
                Task { await appModel.requestOTP(for: email) }
            } label: {
                loadingLabel("Receber código")
            }
            .buttonStyle(AuraPrimaryButtonStyle())
            .disabled(!isValidEmail || appModel.isLoading)

            Button("Voltar") { appModel.flow = .welcome }
                .frame(maxWidth: .infinity)
        }
    }

    private var otp: some View {
        onboardingScroll(title: "Confirme seu acesso", subtitle: "Digite o código enviado para \(appModel.email).") {
            fieldLabel("Código de acesso")
            TextField("000000", text: $appModel.otpCode)
                .keyboardType(.numberPad)
                .textContentType(.oneTimeCode)
                .auraField()
                .onChange(of: appModel.otpCode) {
                    let digits = appModel.otpCode.filter(\.isNumber)
                    appModel.otpCode = String(digits.prefix(6))
                    appModel.clearOTPError()
                }

            if let message = appModel.deliveryMessage {
                Text(message).font(.footnote).foregroundStyle(.secondary)
            }
            otpErrorCard(phase: .verification)

            Button {
                Task { await appModel.verifyOTP() }
            } label: {
                loadingLabel("Confirmar e continuar")
            }
            .buttonStyle(AuraPrimaryButtonStyle())
            .disabled(appModel.otpCode.count < 6 || appModel.isLoading)

            if appModel.otpError?.kind != .tooManyAttempts {
                Button("Enviar novo código") {
                    Task { await appModel.requestOTP(for: appModel.email) }
                }
                .frame(maxWidth: .infinity)
                .disabled(appModel.isLoading)
            }

            Button("Usar outro e-mail") {
                appModel.restart()
                appModel.flow = .login
                email = ""
            }
            .frame(maxWidth: .infinity)
        }
    }

    private var quiz: some View {
        let question = questions[questionIndex]
        return VStack(alignment: .leading, spacing: 0) {
            HStack {
                Button { previousQuestion() } label: { Label("Voltar", systemImage: "chevron.left") }
                    .disabled(questionIndex == 0 || appModel.isLoading)
                Spacer()
                Text("\(questionIndex + 1) de 5")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            ProgressView(value: Double(questionIndex + 1), total: 5)
                .tint(AuraTheme.pink)
                .padding(.vertical, 18)

            HStack(alignment: .top, spacing: 12) {
                AuraMark(size: 38)
                Text("Vou conhecer você melhor para mostrar oportunidades com mais clareza.")
                    .font(.subheadline)
                    .padding(12)
                    .background(.white, in: RoundedRectangle(cornerRadius: 12))
                    .overlay { RoundedRectangle(cornerRadius: 12).stroke(AuraTheme.pink.opacity(0.6)) }
            }

            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text(question.title)
                        .font(.system(size: 26, weight: .bold, design: .rounded))
                        .foregroundStyle(AuraTheme.purple)
                        .padding(.top, 28)

                    ForEach(question.options) { option in
                        Button { answers[question.id] = option } label: {
                            HStack(spacing: 14) {
                                Image(systemName: answers[question.id]?.id == option.id ? "largecircle.fill.circle" : "circle")
                                    .foregroundStyle(AuraTheme.pink)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(option.title).font(.headline).foregroundStyle(AuraTheme.purple)
                                    Text(option.subtitle).font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                            }
                            .padding(16)
                            .frame(maxWidth: .infinity, minHeight: 70, alignment: .leading)
                            .background(
                                answers[question.id]?.id == option.id
                                    ? AuraTheme.pink.opacity(0.06)
                                    : Color.white,
                                in: RoundedRectangle(cornerRadius: 14)
                            )
                            .overlay {
                                RoundedRectangle(cornerRadius: 14)
                                    .inset(by: 1.5)
                                    .strokeBorder(
                                        answers[question.id]?.id == option.id ? AuraTheme.pink : AuraTheme.border,
                                        lineWidth: answers[question.id]?.id == option.id ? 3 : 1
                                    )
                            }
                        }
                        .buttonStyle(.plain)
                        .padding(.horizontal, 1)
                        .accessibilityAddTraits(answers[question.id]?.id == option.id ? .isSelected : [])
                    }

                    Text(question.context)
                        .font(.footnote.italic())
                        .foregroundStyle(AuraTheme.pink)
                }
                .padding(.horizontal, 3)
            }

            errorCard { submitQuiz() }
            Button(questionIndex == 4 ? "Ver meu perfil" : "Continuar") { nextQuestion() }
                .buttonStyle(AuraPrimaryButtonStyle())
                .disabled(answers[question.id] == nil || appModel.isLoading)
                .padding(.top, 14)
        }
        .padding(.horizontal, 22)
        .padding(.vertical, 16)
    }

    private func accountNoticeBanner(_ notice: String) -> some View {
        Label {
            Text(notice)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(AuraTheme.purple)
                .fixedSize(horizontal: false, vertical: true)
        } icon: {
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(AuraTheme.success)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.white, in: RoundedRectangle(cornerRadius: 14))
        .overlay { RoundedRectangle(cornerRadius: 14).stroke(AuraTheme.success.opacity(0.35)) }
        .accessibilityElement(children: .combine)
        .onAppear { AccessibilityNotification.Announcement(notice).post() }
    }

    private func onboardingScroll<Content: View>(title: String, subtitle: String, @ViewBuilder content: () -> Content) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                AuraMark(size: 52)
                Text(title).font(.system(size: 32, weight: .bold, design: .rounded)).foregroundStyle(AuraTheme.purple)
                Text(subtitle).font(.body).foregroundStyle(.secondary)
                content()
                DisclaimerCard()
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 30)
        }
    }

    @ViewBuilder private func errorCard(retry: @escaping () -> Void) -> some View {
        if let message = appModel.errorMessage { ErrorCard(message: message, retry: retry) }
    }

    @ViewBuilder private func otpErrorCard(phase: OTPPhase) -> some View {
        if let error = appModel.otpError {
            VStack(alignment: .leading, spacing: 10) {
                Label {
                    Text(error.title)
                } icon: {
                    Image(systemName: error.systemImage)
                        .foregroundStyle(error.kind == .connection ? Color.orange : AuraTheme.pink)
                }
                .font(.headline)
                .foregroundStyle(AuraTheme.purple)
                Text(error.message)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if let actionTitle = error.actionTitle {
                    Button(actionTitle) {
                        if phase == .request || error.kind == .expired || error.kind == .emailDelivery {
                            let targetEmail = phase == .request ? email : appModel.email
                            Task { await appModel.requestOTP(for: targetEmail) }
                        } else {
                            Task { await appModel.verifyOTP() }
                        }
                    }
                    .buttonStyle(.borderedProminent)
                }
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                (error.kind == .connection ? Color.orange : AuraTheme.pink).opacity(0.08),
                in: RoundedRectangle(cornerRadius: 16)
            )
            .overlay {
                RoundedRectangle(cornerRadius: 16)
                    .stroke((error.kind == .connection ? Color.orange : AuraTheme.pink).opacity(0.35))
            }
            .accessibilityElement(children: .contain)
            .accessibilityLabel("\(error.title). \(error.message)")
        } else {
            errorCard {
                if phase == .request {
                    Task { await appModel.requestOTP(for: email) }
                } else {
                    Task { await appModel.verifyOTP() }
                }
            }
        }
    }

    private func fieldLabel(_ value: String) -> some View {
        Text(value).font(.headline).foregroundStyle(AuraTheme.purple)
    }

    @ViewBuilder private func loadingLabel(_ value: String) -> some View {
        if appModel.isLoading { ProgressView().tint(.white) } else { Text(value) }
    }

    private var isValidEmail: Bool {
        let value = email.trimmingCharacters(in: .whitespacesAndNewlines)
        return value.contains("@") && value.contains(".")
    }

    private func previousQuestion() { questionIndex = max(0, questionIndex - 1) }

    private func nextQuestion() {
        if questionIndex < questions.count - 1 { questionIndex += 1 } else { submitQuiz() }
    }

    private func submitQuiz() {
        guard answers.count == questions.count,
              let profile = RiskQuestionnaire.profile(forAnswers: answers.mapValues(\.id)) else { return }
        let apiAnswers = questions.compactMap { question in
            answers[question.id].map { APIAnswer(questionId: question.id, answer: $0.id) }
        }
        Task { await appModel.declare(profile: profile, answers: apiAnswers) }
    }
}

struct AuraMark: View {
    let size: CGFloat
    var body: some View {
        Text("A")
            .font(.system(size: size * 0.44, weight: .bold, design: .rounded))
            .foregroundStyle(.white)
            .frame(width: size, height: size)
            .background(AuraTheme.pinkBright, in: Circle())
            .accessibilityLabel("Aura")
    }
}

private extension View {
    func auraField() -> some View {
        padding(.horizontal, 16)
            .frame(minHeight: 56)
            .background(.white, in: RoundedRectangle(cornerRadius: 14))
            .overlay { RoundedRectangle(cornerRadius: 14).stroke(AuraTheme.border) }
    }
}
