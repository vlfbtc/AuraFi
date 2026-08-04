import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from database.local.repository import SQLiteRepository


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "database" / "local" / "schema.sql"
NOW = "2026-08-02T12:00:00Z"


class SQLiteRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "aurafi.sqlite3"
        connection = sqlite3.connect(self.db_path)
        try:
            connection.executescript(SCHEMA.read_text(encoding="utf-8"))
        finally:
            connection.close()
        self.repository = SQLiteRepository(
            self.db_path,
            now=lambda: datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
        )

    def tearDown(self) -> None:
        self.repository.close()
        self.tempdir.cleanup()

    def test_mvp_journey_is_persisted_without_network(self) -> None:
        account = self.repository.create_account(
            {"account_id": "acct-maria", "email": "Maria@Example.Test"},
            created_at=NOW,
        )
        self.assertEqual(account["email"], "maria@example.test")
        self.assertFalse(account["email_verified"])

        challenge = self.repository.create_otp_challenge(
            {
                "challenge_id": "challenge-1",
                "email": "maria@example.test",
                "channel": "simulated",
                "delivery": "mock",
                "expires_at": "2026-08-02T12:05:00Z",
                "created_at": NOW,
                "otp": "123456",
            }
        )
        self.assertNotIn("123456", challenge["otp_digest"])
        inspection_connection = sqlite3.connect(self.db_path)
        try:
            raw = inspection_connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'otp_challenges'"
            ).fetchone()[0]
        finally:
            inspection_connection.close()
        self.assertNotIn(" otp ", raw.lower())

        self.repository.mark_email_verified("acct-maria", NOW)
        self.repository.create_session(
            {
                "session_id": "session-1",
                "account_id": "acct-maria",
                "started_at": NOW,
                "expires_at": "2026-08-02T12:30:00Z",
                "access_token_digest": "access-digest",
                "refresh_token_digest": "refresh-digest",
            }
        )
        channel_identity = self.repository.create_channel_identity(
            {
                "channel_identity_id": "channel-ios-1",
                "account_id": "acct-maria",
                "channel": {
                    "name": "ios_app",
                    "adapter": "ios-app",
                    "simulated": False,
                },
                "created_at": NOW,
            }
        )
        self.assertEqual(channel_identity["channel"]["name"], "ios_app")
        self.assertEqual(
            self.repository.find_channel_identity(
                "acct-maria", "ios_app", "ios-app"
            )["channel_identity_id"],
            "channel-ios-1",
        )
        self.assertEqual(
            self.repository.first_channel_identity("acct-maria")[
                "channel_identity_id"
            ],
            "channel-ios-1",
        )
        self.repository.create_consent(
            {
                "consent_id": "consent-conversation",
                "account_id": "acct-maria",
                "purpose": "conversation",
                "status": "granted",
                "policy_version": "2026-01",
                "captured_at": NOW,
            }
        )
        profile = self.repository.create_risk_profile(
            {
                "risk_profile_id": "profile-1",
                "account_id": "acct-maria",
                "declared_profile": "moderate",
                "status": "declared",
                "version": "1",
                "declared_at": NOW,
                "source": "questionnaire",
                "answers": [
                    {"question_id": f"q{i}", "answer": f"answer-{i}"} for i in range(1, 6)
                ],
            }
        )
        self.assertEqual(len(profile["answers"]), 5)

        opportunity = self.repository.create_opportunity_snapshot(
            {
                "opportunity_id": "opportunity-1",
                "market_observation_id": "observation-1",
                "protocol": "Demo Protocol",
                "pool": "USDC Demo",
                "asset": "USDC",
                "blockchain": "Ethereum",
                "apy": {"value": 8.5, "unit": "percent_annualized", "observed_at": NOW},
                "tvl": {"value": 1000000, "currency": "USD", "observed_at": NOW},
                "liquidity": {"level": "high", "observed_at": NOW},
                "risk": {"score": 35, "level": "medium", "dimensions": ["liquidity"]},
                "eligibility": {"status": "needs_profile"},
                "data_source": {
                    "source": "defillama",
                    "mode": "test",
                    "observed_at": NOW,
                    "retrieved_at": NOW,
                    "read_only": True,
                    "is_stale": False,
                },
                "disclaimer": "Simulação informativa; não representa promessa de retorno.",
                "created_at": NOW,
            }
        )
        self.assertEqual(opportunity["opportunity_id"], "opportunity-1")
        self.assertEqual(opportunity["data_source"]["mode"], "test")

        simulation = self.repository.create_simulation(
            {
                "simulation_id": "simulation-1",
                "account_id": "acct-maria",
                "opportunity_id": "opportunity-1",
                "input": {
                    "amount": 1000,
                    "asset": "USDC",
                    "horizons_days": [30, 180, 365],
                    "compare_idle_stablecoin": True,
                },
                "assumptions": ["fixture-test"],
                "data_source_observation_id": "observation-1",
                "generated_at": NOW,
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

        self.repository.create_conversation(
            {
                "conversation_id": "conversation-1",
                "account_id": "acct-maria",
                "session_id": "session-1",
                "consent_id": "consent-conversation",
                "correlation_id": "corr-1",
                "channel": {"name": "simulated", "adapter": "test-adapter", "simulated": True},
                "last_activity_at": NOW,
            }
        )
        message = self.repository.create_message(
            {
                "message_id": "message-1",
                "conversation_id": "conversation-1",
                "message_type": "user_message",
                "occurred_at": NOW,
                "payload": {"text": "Explique o risco desta oportunidade"},
                "disclaimer": "A informação é educativa e não representa promessa de retorno.",
                "audit": {"source": "test", "schema_version": "1.0", "redaction": "not_required"},
            }
        )
        self.assertEqual(message["payload"]["text"], "Explique o risco desta oportunidade")
        self.assertEqual(len(self.repository.list_messages("conversation-1")), 1)

        alert = self.repository.create_alert(
            {
                "alert_id": "alert-1",
                "account_id": "acct-maria",
                "opportunity_id": "opportunity-1",
                "data_source_observation_id": "observation-1",
                "type": "data_stale",
                "title": "Dado desatualizado",
                "message": "Revise o snapshot antes de decidir.",
                "observed_at": NOW,
                "suggested_action": "view_opportunity",
                "disclaimer": "Alerta informativo; não representa promessa de retorno.",
                "created_at": NOW,
            }
        )
        self.assertEqual(alert["status"], "unread")
        self.assertEqual(self.repository.mark_alert_read("alert-1")["status"], "read")

    def test_profile_write_is_atomic_and_connection_closes(self) -> None:
        self.repository.create_account({"account_id": "acct-1", "email": "a@example.test"}, created_at=NOW)
        with self.assertRaises(ValueError):
            self.repository.create_risk_profile(
                {
                    "risk_profile_id": "profile-invalid",
                    "account_id": "acct-1",
                    "declared_profile": "moderate",
                    "version": "1",
                    "declared_at": NOW,
                    "source": "questionnaire",
                    "answers": [{"question_id": "q1", "answer": "only one"}],
                }
            )
        self.assertIsNone(self.repository.get_risk_profile("profile-invalid"))
        self.repository.close()
        self.assertTrue(self.repository.is_closed)
        with self.assertRaises(RuntimeError):
            self.repository.get_account("acct-1")


if __name__ == "__main__":
    unittest.main()
