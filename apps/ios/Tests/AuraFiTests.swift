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

        XCTAssertEqual(consent.status, "granted")
        XCTAssertFalse(consent.memory)
        XCTAssertFalse(consent.analytics)
        XCTAssertEqual(consent.policyVersion, "privacy-1.0")
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
}

private struct StubBiometricAuthenticator: BiometricAuthenticating {
    let kind: BiometricKind
    let result: Result<Void, BiometricError>
    var availableBiometry: BiometricKind { kind }
    func authenticate(reason: String) async -> Result<Void, BiometricError> { result }
}
