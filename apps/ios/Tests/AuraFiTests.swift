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
}
