"""End-to-end coverage of the managed PostgreSQL backend.

Skipped unless AURAFI_TEST_DATABASE_URL points at a real, disposable database
(CI doesn't provision one; see IMPLEMENTATION_STATUS.md for the local setup
commands). Truncates every AuraFi table before each test.
"""

from __future__ import annotations

import os
import unittest

DATABASE_URL = os.environ.get("AURAFI_TEST_DATABASE_URL", "").strip()


@unittest.skipUnless(DATABASE_URL, "AURAFI_TEST_DATABASE_URL not configured; skipping PostgreSQL suite")
class PostgresRepositoryTest(unittest.TestCase):
    NOW = "2026-08-02T12:00:00Z"

    @classmethod
    def setUpClass(cls) -> None:
        from database.postgres.repository import PostgresRepository

        cls.repository = PostgresRepository(DATABASE_URL)
        cls.repository.initialize()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.repository.close()

    def setUp(self) -> None:
        with self.repository._transaction() as connection:  # noqa: SLF001 - test-only reset
            connection.execute(
                """TRUNCATE
                aurafi.idempotent_responses, aurafi.alerts, aurafi.messages,
                aurafi.conversation_runtime_state, aurafi.conversations,
                aurafi.simulation_scenarios, aurafi.simulations, aurafi.opportunities,
                aurafi.defi_market_observations, aurafi.risk_profile_answers,
                aurafi.risk_profiles, aurafi.consents, aurafi.channel_identities,
                aurafi.sessions, aurafi.otp_challenges, aurafi.accounts
                CASCADE"""
            )

    def test_mvp_journey_is_persisted_on_managed_postgres(self) -> None:
        repo = self.repository
        account = repo.create_account({"account_id": "acct-maria", "email": "Maria@Example.Test"}, created_at=self.NOW)
        self.assertEqual(account["email"], "maria@example.test")
        self.assertFalse(account["email_verified"])
        self.assertTrue(account["created_at"].endswith("Z"))

        challenge = repo.create_otp_challenge(
            {
                "challenge_id": "challenge-1",
                "email": "maria@example.test",
                "channel": "simulated",
                "delivery": "mock",
                "expires_at": "2026-08-02T12:05:00Z",
                "created_at": self.NOW,
                "otp": "123456",
            }
        )
        self.assertNotIn("123456", challenge["otp_digest"])

        repo.mark_email_verified("acct-maria", self.NOW)
        self.assertTrue(repo.get_account("acct-maria")["email_verified"])

        repo.create_session(
            {
                "session_id": "session-1",
                "account_id": "acct-maria",
                "started_at": self.NOW,
                "expires_at": "2026-08-02T12:30:00Z",
                "access_token_digest": "access-digest",
                "refresh_token_digest": "refresh-digest",
            }
        )
        self.assertEqual(repo.get_by_access_token_digest("access-digest")["session_id"], "session-1")
        self.assertEqual(repo.get_by_refresh_token_digest("refresh-digest")["session_id"], "session-1")

        profile = repo.create_risk_profile(
            {
                "risk_profile_id": "profile-1",
                "account_id": "acct-maria",
                "declared_profile": "moderate",
                "status": "declared",
                "version": "1",
                "declared_at": self.NOW,
                "source": "questionnaire",
                "answers": [{"question_id": f"q{i}", "answer": f"answer-{i}"} for i in range(1, 6)],
            }
        )
        self.assertEqual(len(profile["answers"]), 5)
        self.assertEqual(repo.get_latest_risk_profile("acct-maria")["risk_profile_id"], "profile-1")

        with self.assertRaises(ValueError):
            repo.create_risk_profile(
                {
                    "risk_profile_id": "profile-invalid",
                    "account_id": "acct-maria",
                    "declared_profile": "moderate",
                    "version": "2",
                    "declared_at": self.NOW,
                    "source": "questionnaire",
                    "answers": [{"question_id": "q1", "answer": "only one"}],
                }
            )
        self.assertIsNone(repo.get_risk_profile("profile-invalid"))

        opportunity = repo.create_opportunity_snapshot(
            {
                "opportunity_id": "opportunity-1",
                "market_observation_id": "observation-1",
                "protocol": "Demo Protocol",
                "pool": "USDC Demo",
                "asset": "USDC",
                "blockchain": "Ethereum",
                "apy": {"value": 8.5, "unit": "percent_annualized", "observed_at": self.NOW},
                "tvl": {"value": 1000000, "currency": "USD", "observed_at": self.NOW},
                "liquidity": {"level": "high", "observed_at": self.NOW},
                "risk": {"score": 35, "level": "medium", "dimensions": ["liquidity"]},
                "eligibility": {"status": "needs_profile"},
                "data_source": {
                    "source": "defillama",
                    "mode": "test",
                    "observed_at": self.NOW,
                    "retrieved_at": self.NOW,
                    "read_only": True,
                    "is_stale": False,
                },
                "disclaimer": "Simulação informativa; não representa promessa de retorno.",
                "created_at": self.NOW,
            }
        )
        self.assertEqual(opportunity["data_source"]["mode"], "test")
        self.assertEqual(opportunity["risk"]["dimensions"], ["liquidity"])
        self.assertEqual(len(repo.list_opportunities()), 1)

        simulation = repo.create_simulation(
            {
                "simulation_id": "simulation-1",
                "account_id": "acct-maria",
                "opportunity_id": "opportunity-1",
                "input": {"amount": 1000, "asset": "USDC", "horizons_days": [30, 180, 365], "compare_idle_stablecoin": True},
                "assumptions": ["fixture-test"],
                "data_source_observation_id": "observation-1",
                "generated_at": self.NOW,
                "execution_supported": False,
                "disclaimer": "Valores simulados; não representam promessa de retorno.",
                "scenarios": [
                    {"horizon_days": 30, "projected_value": 1007, "projected_yield": 7, "currency": "USD"},
                    {"horizon_days": 180, "projected_value": 1040, "projected_yield": 40, "currency": "USD"},
                    {"horizon_days": 365, "projected_value": 1085, "projected_yield": 85, "currency": "USD"},
                ],
            }
        )
        self.assertFalse(simulation["execution_supported"])
        self.assertEqual(simulation["input"]["horizons_days"], [30, 180, 365])
        self.assertEqual(len(simulation["scenarios"]), 3)

        repo.create_consent(
            {
                "consent_id": "consent-conversation",
                "account_id": "acct-maria",
                "purpose": "conversation",
                "status": "granted",
                "policy_version": "2026-01",
                "captured_at": self.NOW,
            }
        )
        repo.create_conversation(
            {
                "conversation_id": "conversation-1",
                "account_id": "acct-maria",
                "session_id": "session-1",
                "consent_id": "consent-conversation",
                "correlation_id": "corr-1",
                "channel": {"name": "simulated", "adapter": "test-adapter", "simulated": True},
                "last_activity_at": self.NOW,
            }
        )
        message = repo.create_message(
            {
                "message_id": "message-1",
                "conversation_id": "conversation-1",
                "message_type": "user_message",
                "occurred_at": self.NOW,
                "payload": {"text": "Explique o risco desta oportunidade"},
                "disclaimer": "A informação é educativa e não representa promessa de retorno.",
                "audit": {"source": "test", "schema_version": "1.0", "redaction": "not_required"},
            }
        )
        self.assertEqual(message["payload"]["text"], "Explique o risco desta oportunidade")
        self.assertEqual(len(repo.list_messages("conversation-1")), 1)

        repo.save_conversation_runtime_state("conversation-1", "acct-maria", {"hello": "world"})
        self.assertEqual(repo.get_conversation_runtime_state("conversation-1"), {"hello": "world"})
        repo.update_conversation_runtime_state("conversation-1", "acct-maria", {"hello": "updated"})
        self.assertEqual(repo.latest_conversation_runtime_state("acct-maria"), {"hello": "updated"})

        alert = repo.create_alert(
            {
                "alert_id": "alert-1",
                "account_id": "acct-maria",
                "opportunity_id": "opportunity-1",
                "data_source_observation_id": "observation-1",
                "type": "data_stale",
                "title": "Dado desatualizado",
                "message": "Revise o snapshot antes de decidir.",
                "observed_at": self.NOW,
                "suggested_action": "view_opportunity",
                "disclaimer": "Alerta informativo; não representa promessa de retorno.",
                "created_at": self.NOW,
            }
        )
        self.assertEqual(alert["status"], "unread")
        self.assertEqual(repo.mark_alert_read("alert-1")["status"], "read")
        self.assertEqual(len(repo.list_alerts("acct-maria")), 1)

    def test_idempotent_response_round_trips_via_postgres(self) -> None:
        repo = self.repository
        self.assertIsNone(repo.get_idempotent_response("principal-1", "POST /v1/simulations", "key-1"))
        saved = repo.save_idempotent_response(
            principal="principal-1",
            route="POST /v1/simulations",
            idempotency_key="key-1",
            request_hash="hash-1",
            response_status=201,
            response_payload={"simulation": {"simulation_id": "simulation-1"}},
            created_at=self.NOW,
        )
        self.assertEqual(saved["response_payload"]["simulation"]["simulation_id"], "simulation-1")
        fetched = repo.get_idempotent_response("principal-1", "POST /v1/simulations", "key-1")
        self.assertEqual(fetched["request_hash"], "hash-1")

    def test_app_persists_risk_profile_and_conversation_across_restart(self) -> None:
        from services.api import create_app
        from services.api.app import Request

        os.environ["DATABASE_URL"] = DATABASE_URL
        try:
            app = create_app()
            self.assertEqual(app.persistence_kind, "postgres")

            requested = app.handle(
                Request(
                    method="POST",
                    target="/v1/auth/otp/request",
                    headers={},
                    body={"email": "maria@example.com", "channel": "web_widget"},
                )
            )
            otp = app.otp_sink.code_for(requested.payload["challenge_id"])
            verified = app.handle(
                Request(
                    method="POST",
                    target="/v1/auth/otp/verify",
                    headers={},
                    body={"challenge_id": requested.payload["challenge_id"], "otp": otp},
                )
            )
            token = verified.payload["session"]["access_token"]

            saved = app.handle(
                Request(
                    method="PUT",
                    target="/v1/profile/risk",
                    headers={"Authorization": f"Bearer {token}"},
                    body={
                        "declared_profile": "moderate",
                        "answers": [{"question_id": f"q{i}", "answer": "resposta"} for i in range(1, 6)],
                    },
                )
            )
            self.assertEqual(saved.status, 200)
            app.close()

            app2 = create_app()
            try:
                restored = app2.handle(
                    Request(
                        method="GET",
                        target="/v1/profile/risk",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                )
                self.assertEqual(restored.status, 200)
                self.assertEqual(restored.payload["risk_profile"]["declared_profile"], "moderate")
            finally:
                app2.close()
        finally:
            os.environ.pop("DATABASE_URL", None)


if __name__ == "__main__":
    unittest.main()
