import XCTest
@testable import AuraFi

final class AuraFiTests: XCTestCase {
    func testAuthResponseDecodesNestedAccountFromAPIContract() throws {
        let payload = Data(
            """
            {
              "session": {
                "access_token": "access-token-value",
                "refresh_token": "refresh-token-value",
                "token_type": "Bearer",
                "expires_at": "2026-08-03T14:00:00Z",
                "account": {
                  "account_id": "acc_maria",
                  "email": "maria@example.com",
                  "email_verified": true,
                  "created_at": "2026-08-03T13:00:00Z"
                }
              }
            }
            """.utf8
        )

        let response = try JSONDecoder().decode(AuthResponse.self, from: payload)

        XCTAssertEqual(response.session.accountId, "acc_maria")
        XCTAssertEqual(response.session.email, "maria@example.com")
        XCTAssertEqual(response.session.tokenType, "Bearer")
    }

    func testAPIBaseURLRejectsNonHTTPAndNonHTTPSSchemes() {
        XCTAssertNil(AuraFiConfiguration.validatedAPIBaseURL(from: "file:///tmp/aurafi"))
        XCTAssertNil(AuraFiConfiguration.validatedAPIBaseURL(from: "aurafi://api.example.com"))
        XCTAssertEqual(
            AuraFiConfiguration.validatedAPIBaseURL(from: "https://api.aurafi.example")?.absoluteString,
            "https://api.aurafi.example"
        )
    }

    func testEmptyEnvironmentOverrideFallsBackToBundledAPIURL() {
        XCTAssertEqual(
            AuraFiConfiguration.resolveAPIBaseURL(
                environmentValue: "   ",
                bundleValue: "https://aurafi-api.onrender.com"
            )?.absoluteString,
            "https://aurafi-api.onrender.com"
        )
    }

    func testAPIBaseURLRejectsCredentialsQueryAndFragment() {
        XCTAssertNil(AuraFiConfiguration.validatedAPIBaseURL(from: "https://user:pass@api.example.com"))
        XCTAssertNil(AuraFiConfiguration.validatedAPIBaseURL(from: "https://api.example.com?token=secret"))
        XCTAssertNil(AuraFiConfiguration.validatedAPIBaseURL(from: "https://api.example.com/#internal"))
    }

    func testConversationMessageDecodesBackendEnvelope() throws {
        let payload = Data(
            """
            {
              "user_message": {
                "message_id": "msg-user",
                "message_type": "user_message",
                "occurred_at": "2026-08-03T20:00:00Z",
                "payload": {"text": "Olá Aura"}
              },
              "assistant_message": {
                "message_id": "msg-aura",
                "message_type": "assistant_message",
                "occurred_at": "2026-08-03T20:00:01Z",
                "payload": {
                  "text": "Olá! Como posso ajudar?",
                  "fallback_used": false,
                  "escalation_flag": false,
                  "llm": {"service_status": "available", "failure_code": null}
                }
              }
            }
            """.utf8
        )

        let response = try JSONDecoder().decode(ConversationMessageResponse.self, from: payload)

        XCTAssertTrue(response.userMessage.isFromUser)
        XCTAssertEqual(response.assistantMessage.payload.text, "Olá! Como posso ajudar?")
        XCTAssertEqual(response.assistantMessage.payload.fallbackUsed, false)
        XCTAssertEqual(response.assistantMessage.payload.llm?.serviceStatus, "available")
    }

    func testConversationConsentStartsWithOptionalUsesDisabled() {
        let consent = ConversationConsent.granted(now: Date(timeIntervalSince1970: 0))

        XCTAssertEqual(consent.purpose, "conversation")
        XCTAssertEqual(consent.status, "granted")
        XCTAssertFalse(consent.memory, "Memória é opcional e começa desligada")
        XCTAssertFalse(consent.analytics)
        XCTAssertEqual(consent.policyVersion, "aurafi-privacy-2026-09")
        XCTAssertTrue(consent.isCurrentPolicy)
    }

    func testConversationConsentEncodesMemoryChoiceForAPI() throws {
        let consent = ConversationConsent.granted(now: Date(timeIntervalSince1970: 0), memory: true)

        let json = try XCTUnwrap(
            JSONSerialization.jsonObject(with: JSONEncoder().encode(consent)) as? [String: Any]
        )

        XCTAssertEqual(json["purpose"] as? String, "conversation")
        XCTAssertEqual(json["status"] as? String, "granted")
        XCTAssertEqual(json["policy_version"] as? String, "aurafi-privacy-2026-09")
        XCTAssertEqual(json["captured_at"] as? String, "1970-01-01T00:00:00Z")
        XCTAssertEqual(json["memory"] as? Bool, true)
        XCTAssertEqual(json["analytics"] as? Bool, false)
    }

    func testRevokingMemoryKeepsPolicyAndRecordsNewCaptureTime() {
        let granted = ConversationConsent.granted(now: Date(timeIntervalSince1970: 0), memory: true)

        let revoked = granted.updatingMemory(false, now: Date(timeIntervalSince1970: 60))

        XCTAssertFalse(revoked.memory)
        XCTAssertFalse(revoked.analytics)
        XCTAssertEqual(revoked.purpose, granted.purpose)
        XCTAssertEqual(revoked.status, granted.status)
        XCTAssertEqual(revoked.policyVersion, granted.policyVersion)
        XCTAssertEqual(revoked.capturedAt, "1970-01-01T00:01:00Z")
    }

    @MainActor
    func testConsentFromPreviousPolicyIsAskedAgainButPendingMessagesStay() throws {
        let harness = AppModelHarness()
        defer { harness.tearDown() }
        let legacy = ConversationConsent(
            purpose: "conversation",
            status: "granted",
            policyVersion: "privacy-1.0",
            capturedAt: "2026-08-01T12:00:00Z",
            memory: false,
            analytics: false
        )
        try harness.chatStore.save(PersistedChatState(
            conversationId: "cnv-old",
            consent: legacy,
            pendingMessages: [PendingChatMessage(id: "ios-uuid-1", text: "Compare riscos")]
        ))

        let model = harness.makeModel()

        XCTAssertFalse(legacy.isCurrentPolicy)
        XCTAssertNil(model.conversationConsent, "A nova política exige um novo aceite")
        XCTAssertEqual(model.conversationMessages.map(\.id), ["ios-uuid-1"])
    }

    @MainActor
    func testNextMessagesCarryTheCurrentMemoryChoice() async throws {
        let harness = AppModelHarness { request in
            switch (request.method, request.path) {
            case ("POST", "/v1/conversations"):
                return .json(201, Fixtures.conversation)
            case ("POST", "/v1/conversations/cnv_1/messages"):
                return .json(200, Fixtures.messageExchange)
            default:
                return .json(404, Fixtures.error(code: "NOT_FOUND"))
            }
        }
        defer { harness.tearDown() }
        let model = harness.makeModel()
        model.session = harness.session

        await model.grantConversationConsent(memory: true)
        XCTAssertTrue(model.conversationMemoryEnabled)
        model.setConversationMemory(false)
        await model.sendMessageToAura("Compare os riscos")

        let requests = harness.stub.requests
        let creation = try XCTUnwrap(requests.first { $0.path == "/v1/conversations" }?.jsonBody)
        let message = try XCTUnwrap(requests.first { $0.path == "/v1/conversations/cnv_1/messages" }?.jsonBody)
        let createdConsent = try XCTUnwrap(creation["consent"] as? [String: Any])
        let messageConsent = try XCTUnwrap(message["consent"] as? [String: Any])
        XCTAssertEqual(createdConsent["memory"] as? Bool, true)
        XCTAssertEqual(createdConsent["policy_version"] as? String, "aurafi-privacy-2026-09")
        XCTAssertEqual(messageConsent["memory"] as? Bool, false, "A revogação vale a partir da próxima mensagem")
        XCTAssertEqual(messageConsent["policy_version"] as? String, "aurafi-privacy-2026-09")
        XCTAssertFalse(model.conversationMemoryEnabled)
        XCTAssertEqual(harness.chatStore.load()?.consent.memory, false, "O estado salvo da conversa acompanha a escolha")
        XCTAssertEqual(model.conversationMessages.last?.text, "Olá! Como posso ajudar?")
    }

    func testPersistedSessionRoundTripKeepsRotatingTokens() throws {
        let session = AuthSession(
            accessToken: "access",
            refreshToken: "refresh",
            tokenType: "Bearer",
            expiresAt: "2026-08-04T00:00:00Z",
            accountId: "acc-1",
            email: "maria@example.com"
        )

        let data = try JSONEncoder().encode(PersistedSession(session))
        let restored = try JSONDecoder().decode(PersistedSession.self, from: data).session

        XCTAssertEqual(restored.accessToken, "access")
        XCTAssertEqual(restored.refreshToken, "refresh")
        XCTAssertEqual(restored.accountId, "acc-1")
    }

    func testAuthenticationFailureIsNotPresentedAsInternetFailure() {
        let presentation = OTPErrorPresentation.make(
            for: AuraFiAPIError.server(
                status: 401,
                code: "AUTHENTICATION_FAILED",
                message: "Falha de autenticação."
            ),
            phase: .verification
        )

        XCTAssertEqual(presentation.kind, .invalidOrExpired)
        XCTAssertEqual(presentation.title, "Código incorreto ou expirado")
        XCTAssertNotEqual(presentation.systemImage, "wifi.exclamationmark")
    }

    func testOTPFailuresFollowIndistinguishableAuthenticationContract() {
        let invalidOrExpired = OTPErrorPresentation.make(
            for: AuraFiAPIError.server(status: 401, code: "AUTHENTICATION_FAILED", message: "authentication failed"),
            phase: .verification
        )
        let limited = OTPErrorPresentation.make(
            for: AuraFiAPIError.server(status: 429, code: "RATE_LIMITED", message: "limited"),
            phase: .verification
        )
        let delivery = OTPErrorPresentation.make(
            for: AuraFiAPIError.server(status: 503, code: "OTP_DELIVERY_UNAVAILABLE", message: "smtp"),
            phase: .request
        )

        XCTAssertEqual(invalidOrExpired.kind, .invalidOrExpired)
        XCTAssertEqual(invalidOrExpired.title, "Código incorreto ou expirado")
        XCTAssertEqual(limited.kind, .tooManyAttempts)
        XCTAssertNil(limited.actionTitle)
        XCTAssertEqual(delivery.kind, .emailDelivery)
    }

    func testPersistedChatStateKeepsConversationConsentAndPendingUUID() throws {
        let state = PersistedChatState(
            conversationId: "cnv-1",
            consent: .granted(now: Date(timeIntervalSince1970: 0)),
            pendingMessages: [PendingChatMessage(id: "ios-uuid-1", text: "Compare riscos")]
        )

        let data = try JSONEncoder().encode(state)
        let restored = try JSONDecoder().decode(PersistedChatState.self, from: data)

        XCTAssertEqual(restored.conversationId, "cnv-1")
        XCTAssertEqual(restored.pendingMessages.first?.id, "ios-uuid-1")
        XCTAssertFalse(restored.consent.memory)
    }

    func testTransportFailureUsesConnectionPresentation() {
        let presentation = OTPErrorPresentation.make(
            for: AuraFiAPIError.transport(URLError(.notConnectedToInternet)),
            phase: .verification
        )

        XCTAssertEqual(presentation.kind, .connection)
    }

    func testOpportunityDetailDecodesBRLAndHistoryEnrichment() throws {
        let payload = Data(
            """
            {
              "opportunity": {
                "opportunity_id": "pool-1",
                "protocol": "Aave",
                "pool": "USDC",
                "asset": "USDC",
                "blockchain": "Base",
                "apy": {"value": 5.2, "unit": "percent_annualized", "observed_at": "2026-08-04T12:00:00Z", "display": "5,20% a.a."},
                "tvl": {"value": 1000, "currency": "USD", "observed_at": "2026-08-04T12:00:00Z", "display": "US$ 1.000,00", "display_compact": "US$ 1.000,00"},
                "liquidity": {"level": "high", "observed_at": "2026-08-04T12:00:00Z"},
                "audit_status": "unknown",
                "risk": {"score": 8.1, "level": "medium", "dimensions": ["liquidity"]},
                "data_source": {
                  "source": "defillama", "mode": "live",
                  "observed_at": "2026-08-04T12:00:00Z", "retrieved_at": "2026-08-04T12:00:01Z",
                  "read_only": true, "is_stale": false,
                  "source_label": "DeFiLlama", "status_label": "Dados atualizados"
                },
                "disclaimer": "Informativo.",
                "history": {
                  "status": "available",
                  "points": [{"observed_at": "2026-08-04T12:00:00Z", "apy_percent": 5.2, "tvl_usd": 1000}],
                  "windows": {
                    "7d": {
                      "window_days": 7, "point_count": 1,
                      "observed_from": "2026-08-04T12:00:00Z", "observed_to": "2026-08-04T12:00:00Z",
                      "apy": {"average": 5.2, "latest": 5.2, "change_percentage_points": 0, "trend": "flat"}
                    }
                  },
                  "data_source": {"source": "defillama", "dataset": "pool_chart", "mode": "live", "is_stale": false}
                },
                "currency_display": {
                  "primary": {"value": 5300, "currency": "BRL"},
                  "secondary": {"value": 1000, "currency": "USD"},
                  "fx": {"status": "available", "source": "bcb_ptax", "rate": 5.3, "is_stale": false}
                }
              }
            }
            """.utf8
        )

        let response = try JSONDecoder().decode(OpportunityResponse.self, from: payload)

        XCTAssertEqual(response.opportunity.currencyDisplay?.primary.currency, "BRL")
        XCTAssertEqual(response.opportunity.currencyDisplay?.secondary?.currency, "USD")
        XCTAssertEqual(response.opportunity.history?.windows["7d"]?.apy?.average, 5.2)
        XCTAssertEqual(response.opportunity.apyLabel, "5,20% a.a.")
        XCTAssertEqual(response.opportunity.tvlLabel, "US$ 1.000,00")
        XCTAssertEqual(response.opportunity.dataSource.usefulSourceLabel, "DeFiLlama")
        XCTAssertEqual(response.opportunity.dataSource.statusLabel, "Dados atualizados")
    }

    func testAlertListResponseDecodesTypeStatusAndDataSource() throws {
        let payload = Data(
            """
            {
              "items": [
                {
                  "alert_id": "alert-1",
                  "type": "apy_change",
                  "opportunity_id": "pool-1",
                  "title": "Mudança de APY observada",
                  "message": "O APY observado desta oportunidade mudou.",
                  "status": "unread",
                  "created_at": "2026-08-29T12:00:00Z",
                  "observed_at": "2026-08-29T12:00:00Z",
                  "data_source": {
                    "source": "defillama", "mode": "live",
                    "observed_at": "2026-08-29T12:00:00Z", "retrieved_at": "2026-08-29T12:00:01Z",
                    "read_only": true, "is_stale": false
                  },
                  "suggested_action": "simulate",
                  "disclaimer": "Alerta educativo; não garante retorno."
                }
              ],
              "pagination": {"page": 1, "page_size": 20, "total": 1, "has_next": false}
            }
            """.utf8
        )

        let response = try JSONDecoder().decode(AlertListResponse.self, from: payload)

        XCTAssertEqual(response.items.count, 1)
        let alert = try XCTUnwrap(response.items.first)
        XCTAssertEqual(alert.type, .apyChange)
        XCTAssertEqual(alert.status, .unread)
        XCTAssertEqual(alert.suggestedAction, .simulate)
        XCTAssertEqual(alert.opportunityId, "pool-1")
        XCTAssertEqual(alert.dataSource?.usefulSourceLabel, "DeFiLlama")
        XCTAssertEqual(response.pagination.total, 1)
    }

    func testAlertResponseDecodesReadStatusAfterUpdate() throws {
        let payload = Data(
            """
            {
              "alert": {
                "alert_id": "alert-1",
                "type": "new_opportunity",
                "title": "Nova oportunidade observada",
                "message": "Uma oportunidade nova apareceu.",
                "status": "read",
                "created_at": "2026-08-29T12:00:00Z",
                "disclaimer": "Alerta educativo; não garante retorno."
              }
            }
            """.utf8
        )

        let response = try JSONDecoder().decode(AlertResponse.self, from: payload)

        XCTAssertEqual(response.alert.status, .read)
        XCTAssertEqual(response.alert.type, .newOpportunity)
        XCTAssertNil(response.alert.opportunityId)
        XCTAssertNil(response.alert.dataSource)
    }

    func testSimulationScenarioSeparatesPercentYieldFromGainAmount() throws {
        let json = Data(
            """
            {
              "horizon_days": 30,
              "projected_value": 500.9, "projected_yield": 0.18, "projected_gain": 0.9,
              "idle_stablecoin_value": 500, "currency": "STETH",
              "projected_value_display": "500,9 STETH",
              "projected_yield_display": "0,18%",
              "projected_gain_display": "0,9 STETH",
              "idle_stablecoin_value_display": "500 STETH"
            }
            """.utf8
        )

        let scenario = try JSONDecoder().decode(SimulationScenario.self, from: json)

        XCTAssertEqual(scenario.projectedYieldDisplay, "0,18%")
        XCTAssertEqual(scenario.projectedGain, 0.9)
        XCTAssertEqual(scenario.projectedGainDisplay, "0,9 STETH")
        XCTAssertEqual(scenario.projectedValueDisplay, "500,9 STETH")
    }

    func testOptimisticChatMessageStartsAsSentWithStableLocalIdentifier() {
        let message = ChatDisplayMessage(optimisticText: "Compare os riscos")

        XCTAssertTrue(message.isFromUser)
        XCTAssertEqual(message.deliveryState, .sent)
        XCTAssertNil(message.serverMessageId)
        XCTAssertFalse(message.id.isEmpty)
    }

    func testDataSourcePrefersBFFProvidedDisplayLabels() {
        let source = APIDataSource(
            source: "defillama",
            mode: "live",
            observedAt: "2026-08-04T12:00:00Z",
            retrievedAt: "2026-08-04T12:00:00Z",
            cacheExpiresAt: nil,
            readOnly: true,
            isStale: false,
            freshnessNote: nil,
            serverSourceLabel: "DeFiLlama",
            serverStatusLabel: "Dados atualizados"
        )

        XCTAssertEqual(source.usefulSourceLabel, "DeFiLlama")
        XCTAssertEqual(source.statusLabel, "Dados atualizados")
    }

    func testBiometricPreferenceDefaultsToEnabledUntilOptOut() {
        let defaults = UserDefaults(suiteName: "aurafi.tests.biometrics")!
        defaults.removePersistentDomain(forName: "aurafi.tests.biometrics")
        let store = BiometricPreferenceStore(defaults: defaults)

        XCTAssertTrue(store.isEnabled(), "Lock deve vir habilitado por padrão em aparelhos compatíveis")

        store.setEnabled(false)
        XCTAssertFalse(store.isEnabled(), "Opt-out do usuário deve persistir")
    }

    @MainActor
    func testBiometricUnlockClearsLockOnSuccessAndKeepsItOnCancel() async {
        let model = AppModel(
            apiClient: AuraFiAPIClient(baseURL: nil),
            biometrics: StubBiometricAuthenticator(kind: .faceID, result: .failure(.cancelled))
        )
        model.isLocked = true

        await model.unlock()
        XCTAssertTrue(model.isLocked, "Cancelar o prompt deve manter o app bloqueado")

        model.setBiometricLock(false)
        XCTAssertFalse(model.isLocked, "Desligar o bloqueio deve destravar imediatamente")
    }

    // MARK: - Baixar meus dados

    func testExportFileNameUsesTheLocalCalendarDay() throws {
        let instant = try XCTUnwrap(ISO8601DateFormatter().date(from: "2026-09-27T01:30:00Z"))

        XCTAssertEqual(
            AccountExportFile.fileName(for: instant, timeZone: try XCTUnwrap(TimeZone(identifier: "America/Sao_Paulo"))),
            "aurafi-meus-dados-2026-09-26.json"
        )
        XCTAssertEqual(
            AccountExportFile.fileName(for: instant, timeZone: try XCTUnwrap(TimeZone(identifier: "UTC"))),
            "aurafi-meus-dados-2026-09-27.json"
        )
    }

    func testExportIsSavedAsSingleTemporaryJSONFile() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("aurafi-tests-\(UUID().uuidString)", isDirectory: true)
        defer { AccountExportFile.removeAll(directory: directory) }
        let utc = try XCTUnwrap(TimeZone(identifier: "UTC"))
        let day = try XCTUnwrap(ISO8601DateFormatter().date(from: "2026-09-26T15:00:00Z"))
        let payload = Data(Fixtures.export.utf8)

        let first = try AccountExportFile.write(payload, date: day, timeZone: utc, directory: directory)
        XCTAssertEqual(first.lastPathComponent, "aurafi-meus-dados-2026-09-26.json")
        XCTAssertEqual(try Data(contentsOf: first), payload, "O conteúdo é salvo como veio do serviço")

        let second = try AccountExportFile.write(payload, date: day.addingTimeInterval(86_400), timeZone: utc, directory: directory)
        XCTAssertFalse(FileManager.default.fileExists(atPath: first.path), "Só a exportação mais recente fica no aparelho")
        XCTAssertTrue(FileManager.default.fileExists(atPath: second.path))

        AccountExportFile.remove(second)
        XCTAssertFalse(FileManager.default.fileExists(atPath: second.path))
    }

    func testExportAccountCallsExportEndpointAndKeepsRawJSON() async throws {
        let stub = StubHTTP { _ in .json(200, Fixtures.export) }
        defer { stub.tearDown() }

        let data = try await stub.client.exportAccount(sessionToken: "token-123")

        let request = try XCTUnwrap(stub.requests.first)
        XCTAssertEqual(request.method, "GET")
        XCTAssertEqual(request.path, "/v1/account/export")
        XCTAssertEqual(request.header("Authorization"), "Bearer token-123")
        XCTAssertEqual(String(decoding: data, as: UTF8.self), Fixtures.export)
    }

    // MARK: - Apagar minha conta

    func testAccountDeletionBodyUsesChallengeAndOTPKeys() throws {
        let data = try JSONEncoder().encode(AccountDeletionRequest(challengeId: "chl_123", otp: "042917"))

        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: String])

        XCTAssertEqual(json, ["challenge_id": "chl_123", "otp": "042917"])
    }

    func testDeleteAccountPostsChallengeAndCodeWithSessionToken() async throws {
        let stub = StubHTTP { _ in .json(200, Fixtures.deletion) }
        defer { stub.tearDown() }

        let response = try await stub.client.deleteAccount(
            sessionToken: "token-123",
            challengeId: "chl_123",
            otp: "042917"
        )

        let request = try XCTUnwrap(stub.requests.first)
        XCTAssertEqual(request.method, "POST")
        XCTAssertEqual(request.path, "/v1/account/deletion")
        XCTAssertEqual(request.header("Authorization"), "Bearer token-123")
        XCTAssertEqual(request.header("Content-Type"), "application/json")
        XCTAssertEqual(request.jsonBody as? [String: String], ["challenge_id": "chl_123", "otp": "042917"])
        XCTAssertEqual(response, AccountDeletionResponse(status: "deleted", deletedAt: "2026-09-26T18:00:00Z"))
    }

    func testDeleteAccountChecksTheCodeBeforeCallingTheService() async {
        let stub = StubHTTP { _ in .json(200, Fixtures.deletion) }
        defer { stub.tearDown() }

        do {
            try await stub.client.deleteAccount(sessionToken: "token-123", challengeId: "chl_123", otp: "12345")
            XCTFail("Um código incompleto não deve chegar ao serviço")
        } catch AuraFiAPIError.invalidParameter {
            XCTAssertTrue(stub.requests.isEmpty)
        } catch {
            XCTFail("Erro inesperado: \(error)")
        }
    }

    func testAccountActionFailuresFollowTheContractMessages() {
        let unauthorized = AuraFiAPIError.server(status: 401, code: "AUTHENTICATION_FAILED", message: "falha")
        let limited = AuraFiAPIError.server(status: 429, code: "RATE_LIMITED", message: "limite")

        XCTAssertEqual(
            AccountActionFailure.deletion(unauthorized, sessionExpired: false),
            AccountActionFailure(message: "Código inválido ou expirado.")
        )
        XCTAssertTrue(AccountActionFailure.deletion(unauthorized, sessionExpired: true).requiresSignIn)
        XCTAssertEqual(AccountActionFailure.deletion(limited, sessionExpired: false).message, PrivacyCopy.tooManyAttempts)
        XCTAssertEqual(AccountActionFailure.codeRequest(limited).message, PrivacyCopy.tooManyAttempts)
        XCTAssertTrue(AccountActionFailure.codeRequest(AccountActionError.signInRequired).requiresSignIn)
        XCTAssertTrue(AccountActionFailure.export(unauthorized).requiresSignIn)
        XCTAssertFalse(AccountActionFailure.export(AuraFiAPIError.transport(URLError(.notConnectedToInternet))).requiresSignIn)
    }

    func testSessionExpiryReadsServiceTimestampsWithMicroseconds() throws {
        let session = AuthSession(
            accessToken: "access",
            refreshToken: "refresh",
            tokenType: "Bearer",
            expiresAt: "2026-09-26T18:00:00.123456+00:00",
            accountId: "acc-1",
            email: "maria@example.com"
        )
        let formatter = ISO8601DateFormatter()

        XCTAssertFalse(session.isExpired(now: try XCTUnwrap(formatter.date(from: "2026-09-26T17:59:00Z"))))
        XCTAssertTrue(session.isExpired(now: try XCTUnwrap(formatter.date(from: "2026-09-26T18:01:00Z"))))
    }

    @MainActor
    func testDeletionCodeGoesToTheSessionEmailAfterCheckingTheSession() async throws {
        let harness = AppModelHarness { request in
            switch (request.method, request.path) {
            case ("GET", "/v1/profile"):
                return .json(200, Fixtures.profile)
            case ("POST", "/v1/auth/otp/request"):
                return .json(202, Fixtures.challenge)
            default:
                return .json(404, Fixtures.error(code: "NOT_FOUND"))
            }
        }
        defer { harness.tearDown() }
        let model = harness.makeModel()
        model.session = harness.session
        model.flow = .dashboard

        let challenge = try await model.requestAccountDeletionCode()

        XCTAssertEqual(challenge.challengeId, "chl_delete")
        let otpRequest = try XCTUnwrap(harness.stub.requests.first { $0.path == "/v1/auth/otp/request" })
        XCTAssertEqual(otpRequest.jsonBody as? [String: String], ["email": "maria@example.com", "channel": "ios_app"])
        XCTAssertEqual(model.flow, .dashboard, "Pedir o código não pode desviar para o fluxo de login")
        XCTAssertNil(model.otpChallenge)
    }

    @MainActor
    func testDeletionCodeIsNotSentWhenTheSessionIsNoLongerValid() async {
        let harness = AppModelHarness { _ in .json(401, Fixtures.error(code: "AUTHENTICATION_FAILED")) }
        defer { harness.tearDown() }
        let model = harness.makeModel()
        model.session = harness.session

        do {
            _ = try await model.requestAccountDeletionCode()
            XCTFail("Sessão inválida deve pedir um novo login")
        } catch {
            XCTAssertEqual(error as? AccountActionError, .signInRequired)
        }
        XCTAssertFalse(harness.stub.requests.contains { $0.path == "/v1/auth/otp/request" })
    }

    @MainActor
    func testConfirmedDeletionErasesEverythingLocalAndShowsTheNotice() async throws {
        let harness = AppModelHarness { request in
            request.path == "/v1/account/deletion"
                ? .json(200, Fixtures.deletion)
                : .json(404, Fixtures.error(code: "NOT_FOUND"))
        }
        defer { harness.tearDown() }
        try harness.seedSignedInDevice()
        let model = harness.makeModel()
        XCTAssertEqual(model.flow, .dashboard)
        XCTAssertEqual(model.decisions.count, 1)
        XCTAssertNotNil(model.conversationConsent)

        try await model.deleteAccount(challengeId: "chl_delete", otp: "042917")

        XCTAssertNil(model.session)
        XCTAssertEqual(model.flow, .welcome)
        XCTAssertTrue(model.decisions.isEmpty)
        XCTAssertNil(model.conversationConsent)
        XCTAssertTrue(model.conversationMessages.isEmpty)
        XCTAssertNil(harness.sessionStore.load(), "Tokens saem do Keychain")
        XCTAssertNil(harness.chatStore.load(), "A conversa salva sai do Keychain")
        XCTAssertTrue(harness.localStore.loadDecisions().isEmpty, "Histórico e planos locais são apagados")
        XCTAssertTrue(harness.localStore.loadOpportunities().isEmpty)
        XCTAssertEqual(model.accountNotice, "Sua conta e seus dados foram apagados.")
    }

    @MainActor
    func testRejectedDeletionCodeKeepsTheAccountUsable() async throws {
        let harness = AppModelHarness { _ in .json(401, Fixtures.error(code: "AUTHENTICATION_FAILED")) }
        defer { harness.tearDown() }
        try harness.seedSignedInDevice()
        let model = harness.makeModel()

        do {
            try await model.deleteAccount(challengeId: "chl_delete", otp: "000000")
            XCTFail("Código recusado não pode apagar nada")
        } catch {
            let failure = AccountActionFailure.deletion(error, sessionExpired: model.isSessionExpired)
            XCTAssertEqual(failure.message, "Código inválido ou expirado.")
            XCTAssertFalse(failure.requiresSignIn)
        }
        XCTAssertNotNil(model.session)
        XCTAssertEqual(model.flow, .dashboard)
        XCTAssertNotNil(harness.sessionStore.load())
        XCTAssertEqual(harness.localStore.loadDecisions().count, 1)
        XCTAssertNil(model.accountNotice)
    }
}

private struct StubBiometricAuthenticator: BiometricAuthenticating {
    let kind: BiometricKind
    let result: Result<Void, BiometricError>
    var availableBiometry: BiometricKind { kind }
    func authenticate(reason: String) async -> Result<Void, BiometricError> { result }
}

// MARK: - Dublês de rede e de armazenamento

private enum Fixtures {
    static let export = #"{"export_version":"1.0","generated_at":"2026-09-26T18:00:00Z","account":{"email":"maria@example.com"},"consents":[],"risk_profiles":[],"conversations":[],"simulations":[],"alerts":[],"sessions":[],"meta":{}}"#
    static let deletion = #"{"status":"deleted","deleted_at":"2026-09-26T18:00:00Z","meta":{"request_id":"req_1"}}"#
    static let challenge = #"{"challenge_id":"chl_delete","expires_at":"2026-09-26T18:05:00Z","delivery":"email","meta":{}}"#
    static let profile = #"{"account":{"account_id":"acc_maria","email":"maria@example.com","email_verified":true},"risk_profile":null}"#
    static let conversation = #"{"conversation":{"conversation_id":"cnv_1","status":"active","messages":[],"last_activity_at":"2026-09-26T18:00:00Z"}}"#
    static let messageExchange = """
    {
      "user_message": {
        "message_id": "msg-user", "message_type": "user_message",
        "occurred_at": "2026-09-26T18:00:00Z", "payload": {"text": "Compare os riscos"}
      },
      "assistant_message": {
        "message_id": "msg-aura", "message_type": "assistant_message",
        "occurred_at": "2026-09-26T18:00:01Z",
        "payload": {"text": "Olá! Como posso ajudar?", "fallback_used": false}
      }
    }
    """

    static func error(code: String) -> String {
        #"{"error":{"code":"\#(code)","message":"Falha simulada.","retryable":false}}"#
    }
}

private struct StubReply: Sendable {
    let status: Int
    let body: Data

    static func json(_ status: Int, _ body: String) -> StubReply {
        StubReply(status: status, body: Data(body.utf8))
    }
}

private struct RecordedRequest: Sendable {
    let method: String?
    let path: String?
    let headers: [String: String]
    let body: Data?

    func header(_ name: String) -> String? {
        headers.first { $0.key.caseInsensitiveCompare(name) == .orderedSame }?.value
    }

    var jsonBody: [String: Any]? {
        body.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
    }
}

/// Responde requisições em memória, separadas por host para que cada teste tenha seu próprio servidor.
private final class StubURLProtocol: URLProtocol {
    typealias Handler = @Sendable (RecordedRequest) -> StubReply

    private static let lock = NSLock()
    nonisolated(unsafe) private static var handlers: [String: Handler] = [:]
    nonisolated(unsafe) private static var recorded: [String: [RecordedRequest]] = [:]

    static func register(host: String, handler: @escaping Handler) {
        lock.withLock {
            handlers[host] = handler
            recorded[host] = []
        }
    }

    static func unregister(host: String) {
        lock.withLock {
            handlers[host] = nil
            recorded[host] = nil
        }
    }

    static func requests(host: String) -> [RecordedRequest] {
        lock.withLock { recorded[host] ?? [] }
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let host = request.url?.host ?? ""
        let recordedRequest = RecordedRequest(
            method: request.httpMethod,
            path: request.url?.path,
            headers: request.allHTTPHeaderFields ?? [:],
            body: Self.body(of: request)
        )
        let handler = Self.lock.withLock { () -> Handler? in
            Self.recorded[host, default: []].append(recordedRequest)
            return Self.handlers[host]
        }
        guard let handler, let url = request.url else {
            client?.urlProtocol(self, didFailWithError: URLError(.cannotConnectToHost))
            return
        }
        let reply = handler(recordedRequest)
        guard let response = HTTPURLResponse(
            url: url,
            statusCode: reply.status,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"]
        ) else {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
            return
        }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: reply.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    private static func body(of request: URLRequest) -> Data? {
        if let body = request.httpBody { return body }
        guard let stream = request.httpBodyStream else { return nil }
        stream.open()
        defer { stream.close() }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 4_096)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            guard count > 0 else { break }
            data.append(buffer, count: count)
        }
        return data
    }
}

private struct StubHTTP {
    let host = "stub-\(UUID().uuidString.lowercased()).aurafi.test"
    let client: AuraFiAPIClient

    init(handler: @escaping StubURLProtocol.Handler) {
        StubURLProtocol.register(host: host, handler: handler)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        client = AuraFiAPIClient(
            baseURL: URL(string: "https://\(host)"),
            session: URLSession(configuration: configuration),
            timeout: 5
        )
    }

    var requests: [RecordedRequest] { StubURLProtocol.requests(host: host) }

    func tearDown() {
        StubURLProtocol.unregister(host: host)
    }
}

/// Monta um `AppModel` com Keychain e UserDefaults próprios do teste, sem tocar nos dados do app.
@MainActor
private final class AppModelHarness {
    let stub: StubHTTP
    let sessionStore: SessionStore
    let chatStore: ChatStateStore
    let localStore: AppLocalStore
    let session = AuthSession(
        accessToken: "access-token",
        refreshToken: "refresh-token",
        tokenType: "Bearer",
        expiresAt: "2099-01-01T00:00:00Z",
        accountId: "acc_maria",
        email: "maria@example.com"
    )
    private let defaults: UserDefaults
    private let suiteName: String

    init(handler: @escaping StubURLProtocol.Handler = { _ in .json(404, Fixtures.error(code: "NOT_FOUND")) }) {
        let id = UUID().uuidString
        suiteName = "aurafi.tests.\(id)"
        defaults = UserDefaults(suiteName: suiteName) ?? .standard
        sessionStore = SessionStore(service: "br.com.aurafi.tests.session.\(id)")
        chatStore = ChatStateStore(service: "br.com.aurafi.tests.conversation.\(id)")
        localStore = AppLocalStore(defaults: defaults)
        stub = StubHTTP(handler: handler)
    }

    func makeModel() -> AppModel {
        AppModel(
            apiClient: stub.client,
            sessionStore: sessionStore,
            localStore: localStore,
            chatStore: chatStore,
            biometrics: StubBiometricAuthenticator(kind: .none, result: .success(())),
            biometricPreference: BiometricPreferenceStore(defaults: defaults)
        )
    }

    /// Simula um aparelho com sessão, conversa, histórico e leitura de mercado salvos.
    func seedSignedInDevice() throws {
        try sessionStore.save(session)
        try chatStore.save(PersistedChatState(
            conversationId: "cnv_1",
            consent: .granted(memory: true),
            pendingMessages: []
        ))
        localStore.saveDecisions([
            DecisionRecord(
                id: UUID(),
                opportunityId: "pool-1",
                protocolName: "Aave",
                asset: "USDC",
                blockchain: "Base",
                amount: 1_000,
                projectedYield: 52,
                createdAt: Date(timeIntervalSince1970: 0),
                outcome: .saved
            )
        ])
        let observedAt = "2026-09-26T18:00:00Z"
        localStore.saveOpportunities([
            Opportunity(
                opportunityId: "pool-1",
                protocolName: "Aave",
                pool: "USDC Supply",
                asset: "USDC",
                blockchain: "Base",
                apy: APIMarketValue(value: 5.2, unit: "percent_annualized", currency: nil, observedAt: observedAt),
                tvl: APIMarketValue(value: 1_000_000, unit: nil, currency: "USD", observedAt: observedAt),
                liquidity: APILiquidity(level: "high", observedAt: observedAt),
                auditStatus: "audited",
                risk: APIRisk(score: 8.1, level: "medium", dimensions: ["liquidity"], classification: nil),
                dataSource: APIDataSource(
                    source: "defillama",
                    mode: "live",
                    observedAt: observedAt,
                    retrievedAt: observedAt,
                    cacheExpiresAt: nil,
                    readOnly: true,
                    isStale: false,
                    freshnessNote: nil,
                    serverSourceLabel: "DeFiLlama",
                    serverStatusLabel: "Dados atualizados"
                ),
                disclaimer: "Informativo."
            )
        ])
    }

    func tearDown() {
        sessionStore.clear()
        chatStore.clear()
        defaults.removePersistentDomain(forName: suiteName)
        stub.tearDown()
    }
}
