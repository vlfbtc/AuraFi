import SwiftUI
import UIKit

/// Falhas locais das ações de conta, antes de qualquer resposta do serviço.
enum AccountActionError: Error, Equatable {
    case signInRequired
}

/// Textos de privacidade compartilhados entre as telas.
enum PrivacyCopy {
    static let memoryToggleTitle = "Lembrar o contexto desta conversa"
    static let memoryToggleHelp = "A Aura usa as mensagens anteriores desta conversa para responder. Você pode desligar quando quiser."
    static let deletionWarning = "Isso apaga sua conta, seu perfil de risco, suas conversas, simulações e alertas. A ação não pode ser desfeita."
    static let accountDeleted = "Sua conta e seus dados foram apagados."
    static let invalidCode = "Código inválido ou expirado."
    static let tooManyAttempts = "Muitas tentativas. Aguarde alguns minutos e tente de novo."
    static let connection = "Sem conexão com o serviço. Confira sua internet e tente de novo."
}

/// Mensagem pronta para a interface; `requiresSignIn` oferece o caminho para entrar de novo.
struct AccountActionFailure: Equatable, Identifiable {
    let message: String
    let requiresSignIn: Bool

    var id: String { message }

    init(message: String, requiresSignIn: Bool = false) {
        self.message = message
        self.requiresSignIn = requiresSignIn
    }

    static func export(_ error: Error) -> AccountActionFailure {
        if error as? AccountActionError == .signInRequired {
            return sessionExpired("Sua sessão expirou. Entre novamente para baixar seus dados.")
        }
        switch error {
        case AuraFiAPIError.server(let status, _, _) where status == 401:
            return sessionExpired("Sua sessão expirou. Entre novamente para baixar seus dados.")
        case AuraFiAPIError.server(let status, _, _) where status == 429:
            return AccountActionFailure(
                message: "Você já baixou seus dados várias vezes na última hora. Tente de novo mais tarde."
            )
        case AuraFiAPIError.transport:
            return AccountActionFailure(message: PrivacyCopy.connection)
        case is CocoaError:
            return AccountActionFailure(message: "Não foi possível salvar o arquivo neste aparelho.")
        default:
            return AccountActionFailure(message: "Não foi possível preparar seus dados agora. Tente de novo em instantes.")
        }
    }

    static func codeRequest(_ error: Error) -> AccountActionFailure {
        if error as? AccountActionError == .signInRequired {
            return sessionExpired("Sua sessão expirou. Entre novamente para apagar sua conta.")
        }
        switch error {
        case AuraFiAPIError.server(let status, let code, _)
            where status == 429 || code.uppercased() == "RATE_LIMITED":
            return AccountActionFailure(message: PrivacyCopy.tooManyAttempts)
        case AuraFiAPIError.server(_, let code, _) where code.uppercased() == "OTP_DELIVERY_UNAVAILABLE":
            return AccountActionFailure(message: "Não conseguimos enviar o código agora. Tente de novo em instantes.")
        case AuraFiAPIError.transport:
            return AccountActionFailure(message: PrivacyCopy.connection)
        default:
            return AccountActionFailure(message: "Não foi possível enviar o código agora. Tente de novo em instantes.")
        }
    }

    /// O serviço responde 401 tanto para código recusado quanto para sessão inválida;
    /// o vencimento local da sessão separa os dois casos.
    static func deletion(_ error: Error, sessionExpired isSessionExpired: Bool) -> AccountActionFailure {
        if error as? AccountActionError == .signInRequired {
            return sessionExpired("Sua sessão expirou. Entre novamente para apagar sua conta.")
        }
        switch error {
        case AuraFiAPIError.server(let status, _, _) where status == 401:
            return isSessionExpired
                ? sessionExpired("Sua sessão expirou. Entre novamente para apagar sua conta.")
                : AccountActionFailure(message: PrivacyCopy.invalidCode)
        case AuraFiAPIError.server(let status, let code, _)
            where status == 429 || code.uppercased() == "RATE_LIMITED":
            return AccountActionFailure(message: PrivacyCopy.tooManyAttempts)
        case AuraFiAPIError.server(let status, _, _) where status == 400:
            return AccountActionFailure(message: "Não foi possível validar o pedido. Peça um novo código e tente de novo.")
        case AuraFiAPIError.invalidParameter(let message):
            return AccountActionFailure(message: message)
        case AuraFiAPIError.transport:
            return AccountActionFailure(message: PrivacyCopy.connection)
        default:
            return AccountActionFailure(message: "Não foi possível apagar sua conta agora. Tente de novo em instantes.")
        }
    }

    private static func sessionExpired(_ message: String) -> AccountActionFailure {
        AccountActionFailure(message: message, requiresSignIn: true)
    }
}

/// Arquivo temporário com a exportação da conta, usado só enquanto a folha de compartilhamento está aberta.
enum AccountExportFile {
    static func fileName(for date: Date, timeZone: TimeZone = .current) -> String {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        return "aurafi-meus-dados-\(formatter.string(from: date)).json"
    }

    static var defaultDirectory: URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("AuraFiExport", isDirectory: true)
    }

    /// Grava a exportação e remove qualquer arquivo anterior, para manter no máximo uma cópia.
    @discardableResult
    static func write(
        _ data: Data,
        date: Date = Date(),
        timeZone: TimeZone = .current,
        directory: URL = defaultDirectory
    ) throws -> URL {
        let fileManager = FileManager.default
        if fileManager.fileExists(atPath: directory.path) {
            try fileManager.removeItem(at: directory)
        }
        try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        let url = directory.appendingPathComponent(fileName(for: date, timeZone: timeZone), isDirectory: false)
        try data.write(to: url, options: [.atomic, .completeFileProtectionUnlessOpen])
        return url
    }

    static func remove(_ url: URL) {
        try? FileManager.default.removeItem(at: url)
    }

    static func removeAll(directory: URL = defaultDirectory) {
        try? FileManager.default.removeItem(at: directory)
    }
}

/// Abre a folha de compartilhamento do sistema sobre a tela visível no momento.
@MainActor
enum ShareSheetPresenter {
    @discardableResult
    static func present(fileURL: URL, onFinish: @escaping @MainActor () -> Void) -> Bool {
        guard let presenter = topViewController() else { return false }
        let controller = UIActivityViewController(activityItems: [fileURL], applicationActivities: nil)
        controller.completionWithItemsHandler = { _, _, _, _ in
            MainActor.assumeIsolated { onFinish() }
        }
        if let popover = controller.popoverPresentationController {
            popover.sourceView = presenter.view
            popover.sourceRect = CGRect(x: presenter.view.bounds.midX, y: presenter.view.bounds.midY, width: 0, height: 0)
            popover.permittedArrowDirections = []
        }
        presenter.present(controller, animated: true)
        return true
    }

    private static func topViewController() -> UIViewController? {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        let windows = scenes.flatMap(\.windows)
        var top = (windows.first(where: \.isKeyWindow) ?? windows.first)?.rootViewController
        while let presented = top?.presentedViewController, !presented.isBeingDismissed {
            top = presented
        }
        return top
    }
}

/// Exclusão da conta: aviso, envio do código ao e-mail da sessão e confirmação com 6 dígitos.
struct AccountDeletionView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var challenge: OTPChallenge?
    @State private var code = ""
    @State private var deliveryNote: String?
    @State private var isSendingCode = false
    @State private var isDeleting = false
    @State private var failure: AccountActionFailure?
    @FocusState private var isCodeFocused: Bool

    var body: some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 10) {
                    Label("Esta ação é definitiva", systemImage: "exclamationmark.triangle.fill")
                        .font(.headline)
                        .foregroundStyle(.red)
                    Text(PrivacyCopy.deletionWarning)
                        .font(.subheadline)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.vertical, 4)
                .accessibilityElement(children: .combine)
            }

            if let challenge {
                codeSections(challenge: challenge)
            } else {
                Section {
                    Button {
                        Task { await sendCode() }
                    } label: {
                        progressLabel("Enviar código de confirmação", isWorking: isSendingCode)
                    }
                    .disabled(isSendingCode)
                } footer: {
                    Text("Vamos enviar um código de 6 dígitos para \(sessionEmail) para confirmar que é você.")
                }
                failureSection
            }
        }
        .navigationTitle("Apagar minha conta")
        .navigationBarTitleDisplayMode(.inline)
        .navigationBarBackButtonHidden(isDeleting)
        .interactiveDismissDisabled(isDeleting)
    }

    /// Fica logo abaixo da ação que falhou, acima do teclado numérico.
    @ViewBuilder
    private var failureSection: some View {
        if let failure {
            Section {
                Label(failure.message, systemImage: "exclamationmark.circle")
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
                if failure.requiresSignIn {
                    Button("Entrar novamente") {
                        Task { await appModel.logout() }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func codeSections(challenge: OTPChallenge) -> some View {
        Section {
            TextField("000000", text: $code)
                .keyboardType(.numberPad)
                .textContentType(.oneTimeCode)
                .font(.title2.monospacedDigit())
                .focused($isCodeFocused)
                .onAppear { isCodeFocused = true }
                .disabled(isDeleting)
                .accessibilityLabel("Código de confirmação com 6 dígitos")
                .onChange(of: code) { _, newValue in
                    let digits = String(newValue.filter { ("0"..."9").contains($0) }.prefix(6))
                    if digits != newValue { code = digits }
                    failure = nil
                }
            Button(role: .destructive) {
                Task { await deleteAccount(challengeId: challenge.challengeId) }
            } label: {
                progressLabel("Apagar definitivamente", isWorking: isDeleting)
            }
            .disabled(code.count != 6 || isDeleting)
        } header: {
            Text("Código de confirmação")
        } footer: {
            Text(deliveryNote ?? "Digite o código enviado para \(sessionEmail).")
        }

        failureSection

        Section {
            Button("Enviar novo código") {
                Task { await sendCode() }
            }
            .disabled(isSendingCode || isDeleting)
        }
    }

    private func progressLabel(_ title: String, isWorking: Bool) -> some View {
        HStack {
            Text(title)
            Spacer()
            if isWorking { ProgressView() }
        }
    }

    private var sessionEmail: String {
        appModel.session?.email ?? appModel.email
    }

    private func sendCode() async {
        guard !isSendingCode else { return }
        isSendingCode = true
        failure = nil
        defer { isSendingCode = false }
        do {
            let newChallenge = try await appModel.requestAccountDeletionCode()
            challenge = newChallenge
            code = ""
            deliveryNote = newChallenge.delivery == "email"
                ? "Digite o código enviado para \(sessionEmail)."
                : "O serviço aceitou o pedido. Confirme o código no ambiente configurado."
            isCodeFocused = true
        } catch {
            failure = .codeRequest(error)
        }
    }

    private func deleteAccount(challengeId: String) async {
        guard !isDeleting, code.count == 6 else { return }
        isDeleting = true
        failure = nil
        defer { isDeleting = false }
        do {
            try await appModel.deleteAccount(challengeId: challengeId, otp: code)
        } catch {
            failure = .deletion(error, sessionExpired: appModel.isSessionExpired)
        }
    }
}
