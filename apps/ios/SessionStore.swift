import Foundation
import Security

struct PersistedSession: Codable {
    let accessToken: String
    let refreshToken: String
    let tokenType: String
    let expiresAt: String
    let accountId: String
    let email: String

    init(_ session: AuthSession) {
        accessToken = session.accessToken
        refreshToken = session.refreshToken
        tokenType = session.tokenType
        expiresAt = session.expiresAt
        accountId = session.accountId
        email = session.email
    }

    var session: AuthSession {
        AuthSession(
            accessToken: accessToken,
            refreshToken: refreshToken,
            tokenType: tokenType,
            expiresAt: expiresAt,
            accountId: accountId,
            email: email
        )
    }
}

enum SessionStoreError: Error {
    case encoding
    case keychain(OSStatus)
}

struct SessionStore {
    private let service: String
    private let account: String

    init(service: String = "br.com.aurafi.app.session", account: String = "authenticated-session") {
        self.service = service
        self.account = account
    }

    func save(_ session: AuthSession) throws {
        guard let data = try? JSONEncoder().encode(PersistedSession(session)) else {
            throw SessionStoreError.encoding
        }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        SecItemDelete(query as CFDictionary)
        var insert = query
        insert[kSecValueData as String] = data
        insert[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(insert as CFDictionary, nil)
        guard status == errSecSuccess else { throw SessionStoreError.keychain(status) }
    }

    func load() -> AuthSession? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data,
              let stored = try? JSONDecoder().decode(PersistedSession.self, from: data)
        else { return nil }
        return stored.session
    }

    func clear() {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        SecItemDelete(query as CFDictionary)
    }
}

struct PendingChatMessage: Codable, Equatable {
    let id: String
    let text: String
}

struct PersistedChatState: Codable, Equatable {
    let conversationId: String?
    let consent: ConversationConsent
    let pendingMessages: [PendingChatMessage]
}

struct ChatStateStore {
    private let service: String
    private let account: String

    init(service: String = "br.com.aurafi.app.conversation", account: String = "conversation-resume-state") {
        self.service = service
        self.account = account
    }

    func save(_ state: PersistedChatState) throws {
        guard let data = try? JSONEncoder().encode(state) else { throw SessionStoreError.encoding }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        SecItemDelete(query as CFDictionary)
        var insert = query
        insert[kSecValueData as String] = data
        insert[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(insert as CFDictionary, nil)
        guard status == errSecSuccess else { throw SessionStoreError.keychain(status) }
    }

    func load() -> PersistedChatState? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data
        else { return nil }
        return try? JSONDecoder().decode(PersistedChatState.self, from: data)
    }

    func clear() {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
        SecItemDelete(query as CFDictionary)
    }
}

struct DecisionRecord: Identifiable, Codable, Equatable {
    enum Outcome: String, Codable { case saved, declined }

    let id: UUID
    let opportunityId: String
    let protocolName: String
    let asset: String
    let blockchain: String
    let amount: Double
    let projectedYield: Double
    let createdAt: Date
    let outcome: Outcome
}

struct AppLocalStore {
    private let decisionsKey = "aurafi.decisions.v1"
    private let opportunitiesKey = "aurafi.market-cache.v1"
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func loadDecisions() -> [DecisionRecord] {
        guard let data = defaults.data(forKey: decisionsKey) else { return [] }
        return (try? JSONDecoder().decode([DecisionRecord].self, from: data)) ?? []
    }

    func saveDecisions(_ decisions: [DecisionRecord]) {
        guard let data = try? JSONEncoder().encode(decisions) else { return }
        defaults.set(data, forKey: decisionsKey)
    }

    func loadOpportunities() -> [Opportunity] {
        guard let data = defaults.data(forKey: opportunitiesKey) else { return [] }
        return (try? JSONDecoder().decode([Opportunity].self, from: data)) ?? []
    }

    func saveOpportunities(_ opportunities: [Opportunity]) {
        guard let data = try? JSONEncoder().encode(opportunities) else { return }
        defaults.set(data, forKey: opportunitiesKey)
    }

    /// Remove o histórico de decisões e a última leitura de mercado guardados neste aparelho.
    func clearAll() {
        defaults.removeObject(forKey: decisionsKey)
        defaults.removeObject(forKey: opportunitiesKey)
    }
}
