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
                  "escalation_flag": false
                }
              }
            }
            """.utf8
        )

        let response = try JSONDecoder().decode(ConversationMessageResponse.self, from: payload)

        XCTAssertTrue(response.userMessage.isFromUser)
        XCTAssertEqual(response.assistantMessage.payload.text, "Olá! Como posso ajudar?")
        XCTAssertEqual(response.assistantMessage.payload.fallbackUsed, false)
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
}
