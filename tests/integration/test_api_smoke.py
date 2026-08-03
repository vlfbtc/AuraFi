"""Smoke test stdlib da jornada minima da API BE-011."""

from __future__ import annotations

import json
import os
import threading
import unittest
from http.client import HTTPConnection
from tempfile import TemporaryDirectory
from unittest.mock import patch

from services.api import create_app, create_server
from services.api.server import allowed_origins_from_env
from services.api.app import (
    DEFAULT_MARKET_BASE_URL,
    DEFAULT_MARKET_ENDPOINT,
    Request,
    create_otp_delivery_from_env,
)
from services.conversation import DeterministicMockLlm
from services.identity.service import OtpDeliveryMessage
from services.market_data import MarketDataError


class ApiSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.production_data = TemporaryDirectory()
        self.addCleanup(self.production_data.cleanup)
        self.app = create_app()
        self.server = create_server(self.app, port=0)
        self.thread = self.server.start_background()
        self.connection = HTTPConnection(*self.server.address, timeout=3)

    def tearDown(self) -> None:
        self.connection.close()
        self.server.shutdown()

    def production_env(self, **overrides: str) -> dict[str, str]:
        values = {
            "AURAFI_DB_PATH": os.path.join(self.production_data.name, "production.sqlite3"),
            "AURAFI_OTP_HMAC_PEPPER": "test-only-pepper-with-at-least-32-bytes",
        }
        values.update(overrides)
        return values

    def request(self, method: str, path: str, payload: dict | None = None, token: str | None = None, headers: dict | None = None):
        headers = dict(headers or {})
        headers.setdefault("Accept", "application/json")
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.connection.request(method, path, body=body, headers=headers)
        response = self.connection.getresponse()
        raw = response.read()
        return response.status, json.loads(raw.decode("utf-8")) if raw else None

    def test_cors_allows_configured_origin_and_rejects_unknown_origin(self) -> None:
        status, _ = self.request(
            "OPTIONS",
            "/v1/auth/otp/request",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type, X-Request-ID",
            },
        )
        self.assertEqual(status, 204)

        status, rejected = self.request(
            "GET",
            "/health",
            headers={"Origin": "https://malicious.example"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(rejected["error"]["code"], "ORIGIN_NOT_ALLOWED")

    def test_cors_configuration_rejects_wildcards(self) -> None:
        with self.assertRaises(ValueError):
            allowed_origins_from_env("*")

    def test_otp_requests_are_rate_limited_by_source(self) -> None:
        last = None
        for _ in range(6):
            last = self.app.handle(
                Request(
                    method="POST",
                    target="/v1/auth/otp/request",
                    headers={},
                    body={"email": "maria@example.com", "channel": "web_widget"},
                    source_ip="203.0.113.10",
                )
            )

        self.assertIsNotNone(last)
        self.assertEqual(last.status, 429)
        self.assertEqual(last.payload["error"]["code"], "RATE_LIMITED")
        self.assertGreaterEqual(int(last.headers["Retry-After"]), 1)

    def test_production_requires_explicit_cors_origins(self) -> None:
        with patch.dict(
            os.environ,
            self.production_env(AURAFI_ENV="production", AURAFI_ALLOWED_ORIGINS=""),
            clear=False,
        ):
            app = create_app(otp_delivery=self.FakeOtpDelivery(), llm=DeterministicMockLlm())
            with self.assertRaises(ValueError):
                create_server(app, port=0)

    class FakeOtpDelivery:
        def __init__(self) -> None:
            self.deliveries: list[OtpDeliveryMessage] = []

        def deliver(self, message: OtpDeliveryMessage) -> None:
            self.deliveries.append(message)

    class FailingOtpDelivery:
        def deliver(self, message: OtpDeliveryMessage) -> None:
            del message
            raise RuntimeError("simulated provider outage")

    def test_otp_delivery_failure_is_reported_as_retryable_503(self) -> None:
        app = create_app(
            otp_delivery=self.FailingOtpDelivery(),
            llm=DeterministicMockLlm(),
        )
        response = app.handle(
            Request(
                method="POST",
                target="/v1/auth/otp/request",
                headers={},
                body={"email": "maria@example.com", "channel": "ios_app"},
                source_ip="203.0.113.20",
            )
        )

        self.assertEqual(response.status, 503)
        self.assertEqual(response.payload["error"]["code"], "OTP_DELIVERY_UNAVAILABLE")
        self.assertTrue(response.payload["error"]["retryable"])

    def test_sqlite_otp_request_works_through_threaded_http_server(self) -> None:
        delivery = self.FakeOtpDelivery()
        environment = self.production_env(
            AURAFI_ENV="production",
            AURAFI_ALLOWED_ORIGINS="https://app.aurafi.example",
        )
        with patch.dict(os.environ, environment, clear=False):
            app = create_app(otp_delivery=delivery, llm=DeterministicMockLlm())
            server = create_server(app, port=0)

        server.start_background(name="aurafi-sqlite-thread-test")
        connection = HTTPConnection(*server.address, timeout=3)
        try:
            body = json.dumps(
                {"email": "maria@example.com", "channel": "ios_app"}
            ).encode("utf-8")
            connection.request(
                "POST",
                "/v1/auth/otp/request",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()
            server.shutdown()
            app.close()

        self.assertEqual(response.status, 202)
        self.assertEqual(payload["delivery"], "email")
        self.assertEqual(len(delivery.deliveries), 1)

    def test_health_auth_profile_market_simulation_conversation(self) -> None:
        status, health = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["status"], "ok")
        self.assertIn("disclaimer", health["meta"])

        status, requested = self.request(
            "POST",
            "/v1/auth/otp/request",
            {"email": "maria@example.com", "channel": "simulated"},
        )
        self.assertEqual(status, 202)
        self.assertNotIn("otp", requested)
        otp = self.app.otp_sink.code_for(requested["challenge_id"])
        self.assertIsNotNone(otp)

        status, authenticated = self.request(
            "POST",
            "/v1/auth/otp/verify",
            {"challenge_id": requested["challenge_id"], "otp": otp},
        )
        self.assertEqual(status, 200)
        token = authenticated["session"]["access_token"]

        answers = [{"question_id": f"q{i}", "answer": "resposta declarada"} for i in range(1, 6)]
        status, profile = self.request(
            "PUT",
            "/v1/profile/risk",
            {"declared_profile": "moderate", "answers": answers},
            token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(profile["risk_profile"]["declared_profile"], "moderate")

        status, opportunities = self.request("GET", "/v1/opportunities", token=token)
        self.assertEqual(status, 200)
        opportunity = opportunities["items"][0]

        status, simulation = self.request(
            "POST",
            "/v1/simulations",
            {
                "opportunity_id": opportunity["opportunity_id"],
                "amount": 1000,
                "asset": opportunity["asset"],
                "horizons_days": [30, 180, 365],
            },
            token,
        )
        self.assertEqual(status, 201)
        self.assertFalse(simulation["simulation"]["execution_supported"])

        consent = {"purpose": "conversation", "status": "granted", "policy_version": "consent-1.0"}
        status, conversation = self.request(
            "POST",
            "/v1/conversations",
            {"channel": "simulated", "consent": consent},
            token,
        )
        self.assertEqual(status, 201)
        conversation_id = conversation["conversation"]["conversation_id"]

        status, message = self.request(
            "POST",
            f"/v1/conversations/{conversation_id}/messages",
            {"text": "Quais riscos devo observar?", "channel": "simulated", "consent": consent},
            token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(message["assistant_message"]["channel"]["name"], "simulated")
        self.assertIn("disclaimer", message["assistant_message"])

        status, rejected = self.request(
            "POST",
            f"/v1/conversations/{conversation_id}/messages",
            {
                "text": "Use uma política diferente.",
                "channel": "simulated",
                "consent": {**consent, "policy_version": "client-overridden"},
            },
            token,
        )
        self.assertEqual(status, 422)
        self.assertEqual(rejected["error"]["code"], "CONSENT_REQUIRED")

    def test_recommendation_without_policy_is_fail_closed(self) -> None:
        status, requested = self.request(
            "POST",
            "/v1/auth/otp/request",
            {"email": "maria@example.com", "channel": "web_widget"},
        )
        otp = self.app.otp_sink.code_for(requested["challenge_id"])
        _, authenticated = self.request(
            "POST",
            "/v1/auth/otp/verify",
            {"challenge_id": requested["challenge_id"], "otp": otp},
        )
        token = authenticated["session"]["access_token"]
        self.request(
            "PUT",
            "/v1/profile/risk",
            {
                "declared_profile": "moderate",
                "answers": [
                    {"question_id": f"q{i}", "answer": "resposta declarada"}
                    for i in range(1, 6)
                ],
            },
            token,
        )
        status, response = self.request(
            "POST",
            "/v1/recommendations",
            {"intent": "discover"},
            token,
        )
        self.assertEqual(status, 201)
        self.assertEqual(response["recommendation"]["status"], "no_match")
        self.assertIn("POLICY_REQUIRED", response["recommendation"]["explanation"])
        self.assertEqual(response["recommendation"]["items"], [])

    def test_prohibited_operation_is_rejected_as_structured_error(self) -> None:
        status, response = self.request(
            "POST",
            "/v1/simulations",
            {"wallet_address": "0xnot-supported"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(response["error"]["code"], "OPERATION_NOT_SUPPORTED")
        self.assertIn("disclaimer", response["meta"])

    def test_sqlite_factory_reopens_same_file(self) -> None:
        with TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"AURAFI_DB_PATH": os.path.join(directory, "be015.sqlite3")},
            clear=False,
        ):
            first = create_app()
            self.assertIsNotNone(first.persistence)
            first.persistence.save_account(  # type: ignore[union-attr]
                {"account_id": "be015-account", "email": "be015@example.invalid"},
                created_at="2026-08-02T12:00:00Z",
            )
            first.close()

            second = create_app()
            try:
                self.assertIsNotNone(second.persistence)
                persisted = second.persistence.get_account("be015-account")  # type: ignore[union-attr]
                self.assertEqual(persisted["email"], "be015@example.invalid")
            finally:
                second.close()

    def test_sqlite_session_and_risk_profile_survive_app_restart(self) -> None:
        def authenticate(app):
            requested = app.handle(
                Request(
                    method="POST",
                    target="/v1/auth/otp/request",
                    headers={},
                    body={"email": "maria@example.com", "channel": "simulated"},
                )
            )
            self.assertEqual(requested.status, 202)
            otp = app.otp_sink.code_for(requested.payload["challenge_id"])
            self.assertIsNotNone(otp)
            verified = app.handle(
                Request(
                    method="POST",
                    target="/v1/auth/otp/verify",
                    headers={},
                    body={
                        "challenge_id": requested.payload["challenge_id"],
                        "otp": otp,
                    },
                )
            )
            self.assertEqual(verified.status, 200)
            return requested.payload["challenge_id"], verified.payload["session"]["access_token"]

        with TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"AURAFI_DB_PATH": os.path.join(directory, "be018.sqlite3")},
            clear=False,
        ):
            first = create_app()
            challenge_id, first_token = authenticate(first)
            stored_challenge = first.persistence.get_otp_challenge(challenge_id)
            self.assertIsNotNone(stored_challenge)
            self.assertTrue(stored_challenge["otp_digest"])
            self.assertNotIn("otp", stored_challenge)
            saved = first.handle(
                Request(
                    method="PUT",
                    target="/v1/profile/risk",
                    headers={"Authorization": f"Bearer {first_token}"},
                    body={
                        "declared_profile": "moderate",
                        "answers": [
                            {"question_id": f"q{i}", "answer": "resposta declarada"}
                            for i in range(1, 6)
                        ],
                    },
                )
            )
            self.assertEqual(saved.status, 200)
            persisted = first.persistence.get_latest_risk_profile("acc_maria")
            self.assertIsNotNone(persisted)
            self.assertEqual(len(persisted["answers"]), 5)
            consent = {
                "purpose": "conversation",
                "status": "granted",
                "policy_version": "consent-1.0",
            }
            created_conversation = first.handle(
                Request(
                    method="POST",
                    target="/v1/conversations",
                    headers={"Authorization": f"Bearer {first_token}"},
                    body={"channel": "simulated", "consent": consent},
                )
            )
            conversation_id = created_conversation.payload["conversation"]["conversation_id"]
            sent = first.handle(
                Request(
                    method="POST",
                    target=f"/v1/conversations/{conversation_id}/messages",
                    headers={"Authorization": f"Bearer {first_token}"},
                    body={
                        "text": "Explique os riscos.",
                        "channel": "simulated",
                        "consent": consent,
                    },
                )
            )
            self.assertEqual(sent.status, 200)
            first.close()

            second = create_app()
            try:
                restored = second.handle(
                    Request(
                        method="GET",
                        target="/v1/profile/risk",
                        headers={"Authorization": f"Bearer {first_token}"},
                    )
                )
                self.assertEqual(restored.status, 200)
                self.assertEqual(
                    restored.payload["risk_profile"]["declared_profile"],
                    "moderate",
                )
                profile = second.handle(
                    Request(
                        method="GET",
                        target="/v1/profile",
                        headers={"Authorization": f"Bearer {first_token}"},
                    )
                )
                self.assertEqual(profile.status, 200)
                self.assertTrue(profile.payload["account"]["email_verified"])
                conversation = second.handle(
                    Request(
                        method="GET",
                        target=f"/v1/conversations/{conversation_id}",
                        headers={"Authorization": f"Bearer {first_token}"},
                    )
                )
                self.assertEqual(conversation.status, 200)
                self.assertEqual(len(conversation.payload["conversation"]["messages"]), 2)
            finally:
                second.close()

    def test_network_opt_in_uses_public_defaults_and_auto_mode(self) -> None:
        with patch.dict(
            os.environ,
            {"AURAFI_ENABLE_MARKET_NETWORK": "true", "AURAFI_MARKET_MODE": ""},
        ):
            os.environ.pop("AURAFI_MARKET_BASE_URL", None)
            os.environ.pop("AURAFI_MARKET_ENDPOINT", None)
            app = create_app()

        self.assertEqual(app.market_mode, "auto")
        self.assertEqual(app.market.base_url, DEFAULT_MARKET_BASE_URL)
        self.assertEqual(app.market.endpoint, DEFAULT_MARKET_ENDPOINT)

    def test_production_defaults_to_live_and_rejects_synthetic_modes(self) -> None:
        delivery = self.FakeOtpDelivery()
        with patch.dict(
            os.environ,
            self.production_env(AURAFI_ENV="production", AURAFI_MARKET_MODE=""),
            clear=False,
        ):
            app = create_app(otp_delivery=delivery, llm=DeterministicMockLlm())
            self.assertEqual(app.environment, "production")
            self.assertTrue(app.is_production)
            self.assertEqual(app.market_mode, "live")
            self.assertEqual(app.market.base_url, DEFAULT_MARKET_BASE_URL)
            self.assertEqual(app.market.endpoint, DEFAULT_MARKET_ENDPOINT)

            with self.assertRaises(ValueError):
                create_app(market_mode="test", llm=DeterministicMockLlm())
            with self.assertRaises(ValueError):
                create_app(market_mode="fallback", llm=DeterministicMockLlm())

    def test_production_without_real_delivery_fails_closed(self) -> None:
        with patch.dict(
            os.environ,
            self.production_env(
                AURAFI_ENV="production",
                AURAFI_OTP_PROVIDER="",
                AURAFI_DEV_OTP_CODE="123456",
            ),
            clear=False,
        ):
            with self.assertRaises(ValueError):
                create_app()

    def test_production_requires_persistent_database_and_stable_pepper(self) -> None:
        delivery = self.FakeOtpDelivery()
        with patch.dict(os.environ, {"AURAFI_ENV": "production"}, clear=True):
            with self.assertRaisesRegex(ValueError, "AURAFI_DB_PATH"):
                create_app(otp_delivery=delivery, llm=DeterministicMockLlm())

        with patch.dict(
            os.environ,
            {
                "AURAFI_ENV": "production",
                "AURAFI_DB_PATH": os.path.join(self.production_data.name, "pepper.sqlite3"),
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "AURAFI_OTP_HMAC_PEPPER"):
                create_app(otp_delivery=delivery, llm=DeterministicMockLlm())

    def test_production_injected_delivery_never_uses_fixed_otp(self) -> None:
        delivery = self.FakeOtpDelivery()
        with patch.dict(
            os.environ,
            self.production_env(
                AURAFI_ENV="prod",
                AURAFI_OTP_PROVIDER="",
                AURAFI_DEV_OTP_CODE="123456",
            ),
            clear=False,
        ):
            app = create_app(otp_delivery=delivery, llm=DeterministicMockLlm())
            response = app.handle(
                Request(
                    method="POST",
                    target="/v1/auth/otp/request",
                    headers={},
                    body={"email": "maria@example.com", "channel": "web_widget"},
                )
            )

        self.assertEqual(response.status, 202)
        self.assertEqual(len(delivery.deliveries), 1)
        self.assertNotEqual(delivery.deliveries[0].otp, "123456")

    def test_provider_configuration_uses_injected_factory_without_network(self) -> None:
        delivery = self.FakeOtpDelivery()
        with patch.dict(
            os.environ,
            {"AURAFI_ENV": "test", "AURAFI_OTP_PROVIDER": "smtp"},
            clear=False,
        ), patch(
            "services.api.app.create_otp_delivery_from_env",
            return_value=delivery,
        ) as factory:
            app = create_app()

        factory.assert_called_once_with()
        self.assertIsNone(app.otp_sink)
        self.assertEqual(app.identity._delivery_mode, "email")

    def test_smtp_factory_uses_delivery_module_without_name_error(self) -> None:
        delivery = self.FakeOtpDelivery()
        with patch(
            "services.api.app.otp_delivery_module.SmtpOtpDelivery.from_env",
            return_value=delivery,
        ) as factory:
            result = create_otp_delivery_from_env({"AURAFI_OTP_PROVIDER": "smtp"})

        self.assertIs(result, delivery)
        factory.assert_called_once()

    def test_market_configuration_rejects_non_official_host(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AURAFI_ENABLE_MARKET_NETWORK": "true",
                "AURAFI_MARKET_BASE_URL": "https://attacker.example",
            },
            clear=False,
        ):
            with self.assertRaises(ValueError):
                create_app()

    def test_production_never_serves_synthetic_data_after_live_failure(self) -> None:
        class FailingHttpStub:
            def get(self, url: str, *, timeout_seconds: float):
                raise OSError("stub upstream unavailable")

        with patch.dict(
            os.environ,
            self.production_env(AURAFI_ENV="prod", AURAFI_MARKET_MODE=""),
            clear=False,
        ):
            app = create_app(otp_delivery=self.FakeOtpDelivery(), llm=DeterministicMockLlm())
            app.market.http_client = FailingHttpStub()
            with self.assertRaises(MarketDataError):
                app._read_market()

    def test_live_market_uses_http_stub_and_preserves_source_metadata(self) -> None:
        calls: list[tuple[str, float]] = []

        class HttpStub:
            def get(self, url: str, *, timeout_seconds: float):
                calls.append((url, timeout_seconds))
                return {
                    "data": [
                        {
                            "pool": "pool-live-1",
                            "project": "Aave",
                            "poolMeta": "USDC Supply",
                            "symbol": "USDC",
                            "chain": "Base",
                            "apy": 5.25,
                            "tvlUsd": 1_500_000,
                            "observed_at": "2026-08-02T12:00:00Z",
                        }
                    ]
                }

        self.app.market_mode = "live"
        self.app.market.base_url = "https://stub.defillama.invalid"
        self.app.market.endpoint = "/pools"
        self.app.market.http_client = HttpStub()

        status, requested = self.request(
            "POST",
            "/v1/auth/otp/request",
            {"email": "maria@example.com", "channel": "web_widget"},
        )
        self.assertEqual(status, 202)
        otp = self.app.otp_sink.code_for(requested["challenge_id"])
        status, authenticated = self.request(
            "POST",
            "/v1/auth/otp/verify",
            {"challenge_id": requested["challenge_id"], "otp": otp},
        )
        self.assertEqual(status, 200)

        status, response = self.request(
            "GET", "/v1/opportunities", token=authenticated["session"]["access_token"]
        )

        self.assertEqual(status, 200)
        self.assertEqual(calls[0][0], "https://stub.defillama.invalid/pools")
        source = response["meta"]["data_sources"][0]
        self.assertEqual(source["source"], "defillama")
        self.assertEqual(source["mode"], "live")
        self.assertTrue(source["read_only"])
        self.assertFalse(source["is_stale"])
        self.assertEqual(source["observed_at"], "2026-08-02T12:00:00Z")
        self.assertIn("retrieved_at", source)

    def test_live_market_failure_is_explicit_stale_fallback(self) -> None:
        class FailingHttpStub:
            def get(self, url: str, *, timeout_seconds: float):
                raise OSError("stub upstream unavailable")

        self.app.market_mode = "live"
        self.app.market.base_url = "https://stub.defillama.invalid"
        self.app.market.endpoint = "/pools"
        self.app.market.http_client = FailingHttpStub()

        status, requested = self.request(
            "POST",
            "/v1/auth/otp/request",
            {"email": "maria@example.com", "channel": "web_widget"},
        )
        otp = self.app.otp_sink.code_for(requested["challenge_id"])
        _, authenticated = self.request(
            "POST",
            "/v1/auth/otp/verify",
            {"challenge_id": requested["challenge_id"], "otp": otp},
        )

        status, response = self.request(
            "GET", "/v1/opportunities", token=authenticated["session"]["access_token"]
        )

        self.assertEqual(status, 200)
        source = response["meta"]["data_sources"][0]
        self.assertEqual(source["mode"], "fallback")
        self.assertTrue(source["is_stale"])
        self.assertNotEqual(source["mode"], "live")
        self.assertIn("fallback", source["freshness_note"].lower())


if __name__ == "__main__":
    unittest.main()
