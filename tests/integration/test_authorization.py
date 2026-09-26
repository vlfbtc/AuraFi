"""Testes negativos de autorização entre contas (OWASP Top 10:2025, A01).

Duas contas, criadas pelo fluxo completo de código por e-mail (pedido e
verificação), tentam ler e alterar dados uma da outra pela API. O que se
garante aqui:

* recurso de outra conta responde 404, com o mesmo erro de um recurso que não
  existe, e a resposta não carrega nenhum dado da dona do recurso;
* nenhuma tentativa negada altera o recurso da outra conta;
* sem sessão válida, cada rota protegida responde 401;
* depois do logout ou da renovação da sessão, o token antigo deixa de valer.

A mesma bateria roda com persistência SQLite em arquivo temporário e com o
modo em memória, porque cada um tem o próprio caminho de checagem de dono.
Nada acessa a rede: o mercado vem de um stub, o código OTP é lido do sink de
desenvolvimento e o hub usa o LLM determinístico.
"""

from __future__ import annotations

import json
import os
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from typing import Any, Iterable
from unittest.mock import patch

from services.api import create_app
from services.api.app import Request
from services.conversation import DeterministicMockLlm


POLICY_VERSION = "aurafi-privacy-2026-09"
RISK_ANSWERS = [
    {"question_id": f"q{index}", "answer": "resposta declarada"} for index in range(1, 6)
]
MESSAGE_IDEMPOTENCY_KEY = "mensagem-1"
MISSING_CONVERSATION_ID = "cnv_" + "0" * 32
MISSING_ALERT_ID = "00000000-0000-4000-8000-000000000000"
AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"


@dataclass(frozen=True)
class SignedInAccount:
    email: str
    account_id: str
    access_token: str
    refresh_token: str

    def secrets(self) -> tuple[str, ...]:
        """Valores da conta que nunca podem aparecer numa resposta dada a outra conta."""

        return (self.account_id, self.email, self.access_token, self.refresh_token)


@dataclass(frozen=True)
class ProtectedRoute:
    method: str
    target: str
    body: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"{self.method} {self.target}"


@dataclass(frozen=True)
class OwnedData:
    """Dados de uma conta e as rotas protegidas que apontam para eles."""

    conversation_id: str
    alert_id: str
    routes: tuple[ProtectedRoute, ...]


class MarketStub:
    """Faz o papel da DeFiLlama sem rede; cada publicação é uma observação mais nova."""

    POOL_ID = "pool-authz-usdc"

    def __init__(self) -> None:
        self._observed_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        self._pools: list[dict[str, Any]] = []
        self.publish(apy=5.0)

    def publish(self, *, apy: float) -> None:
        self._observed_at += timedelta(minutes=5)
        self._pools = [
            {
                "pool": self.POOL_ID,
                "project": "Aave",
                "poolMeta": "USDC Supply",
                "symbol": "USDC",
                "chain": "Ethereum",
                "apy": apy,
                "tvlUsd": 500_000_000,
                "observed_at": self._observed_at.isoformat().replace("+00:00", "Z"),
            }
        ]

    def get(self, url: str, *, timeout_seconds: float) -> dict[str, Any]:
        del timeout_seconds
        if not url.endswith("/pools"):
            raise OSError("rede indisponível nos testes de autorização")
        return {"data": [dict(pool) for pool in self._pools]}


class CrossAccountAuthorizationSuite:
    """Bateria comum; a subclasse concreta escolhe a persistência.

    Não herda de ``unittest.TestCase`` para não ser coletada sem persistência
    definida.
    """

    persistence_kind = ""

    def setUp(self) -> None:
        super().setUp()
        environment = {
            # Isola a bateria do ambiente de quem roda a suíte.
            "AURAFI_ENV": "test",
            "DATABASE_URL": "",
            "AURAFI_DB_PATH": "",
            "AURAFI_OTP_PROVIDER": "",
            "AURAFI_DEV_OTP_CODE": "",
            "AURAFI_ENABLE_MARKET_NETWORK": "",
            "AURAFI_MARKET_MODE": "",
            "AURAFI_OTP_REQUEST_LIMIT": "",
            "AURAFI_OTP_VERIFY_LIMIT": "",
            "AURAFI_LLM_REQUEST_LIMIT": "",
            # Contas novas nascem pelo próprio fluxo de código por e-mail.
            "AURAFI_ALLOW_SELF_SIGNUP": "true",
        }
        if self.persistence_kind == "sqlite":
            directory = TemporaryDirectory()
            self.addCleanup(directory.cleanup)
            environment["AURAFI_DB_PATH"] = os.path.join(
                directory.name, "authorization.sqlite3"
            )
        environment_patch = patch.dict(os.environ, environment)
        environment_patch.start()
        self.addCleanup(environment_patch.stop)

        self.app = create_app(llm=DeterministicMockLlm())
        self.addCleanup(self.app.close)
        self.assertEqual(self.app.persistence_kind, self.persistence_kind)
        self.market = MarketStub()
        self.app.market_mode = "live"
        self.app.market.base_url = "https://stub.defillama.invalid"
        self.app.market.endpoint = "/pools"
        self.app.market.http_client = self.market
        self.consent_captured_at = (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )

        self.ana = self.sign_in("ana@example.test", source_ip="198.51.100.10")
        self.bia = self.sign_in("bia@example.test", source_ip="198.51.100.20")
        self.assertNotEqual(self.ana.account_id, self.bia.account_id)

    # Chamadas e asserções -------------------------------------------------

    def call(
        self,
        method: str,
        target: str,
        body: Any = None,
        *,
        token: str | None = None,
        headers: dict[str, str] | None = None,
        source_ip: str | None = None,
    ) -> tuple[int, Any]:
        request_headers = dict(headers or {})
        if token is not None:
            request_headers["Authorization"] = f"Bearer {token}"
        response = self.app.handle(
            Request(
                method=method,
                target=target,
                headers=request_headers,
                body=body,
                source_ip=source_ip,
            )
        )
        return response.status, response.payload

    def assert_denied(
        self, status: int, payload: Any, expected_status: int, expected_code: str
    ) -> None:
        """Erro no envelope padrão, sem nenhum dado além de ``error`` e ``meta``."""

        self.assertEqual(status, expected_status, payload)
        self.assertEqual(set(payload), {"error", "meta"}, payload)
        self.assertEqual(payload["error"]["code"], expected_code, payload)

    def assert_no_trace(self, payload: Any, secrets: Iterable[str]) -> None:
        serialized = json.dumps(payload, ensure_ascii=False, default=str)
        for secret in secrets:
            self.assertNotIn(secret, serialized)

    # Fluxos ---------------------------------------------------------------

    def sign_in(self, email: str, *, source_ip: str) -> SignedInAccount:
        """Pedido de código e verificação, como fazem os clientes."""

        status, requested = self.call(
            "POST",
            "/v1/auth/otp/request",
            {"email": email, "channel": "web_widget"},
            source_ip=source_ip,
        )
        self.assertEqual(status, 202, requested)
        code = self.app.otp_sink.code_for(requested["challenge_id"])
        self.assertIsNotNone(code, "o código deveria chegar ao sink de desenvolvimento")
        status, verified = self.call(
            "POST",
            "/v1/auth/otp/verify",
            {"challenge_id": requested["challenge_id"], "otp": code},
            source_ip=source_ip,
        )
        self.assertEqual(status, 200, verified)
        session = verified["session"]
        # A conta só é lida depois da verificação, pela própria sessão.
        status, profile = self.call("GET", "/v1/profile", token=session["access_token"])
        self.assertEqual(status, 200, profile)
        self.assertEqual(profile["account"]["email"], email)
        return SignedInAccount(
            email=email,
            account_id=profile["account"]["account_id"],
            access_token=session["access_token"],
            refresh_token=session["refresh_token"],
        )

    def consent(self) -> dict[str, Any]:
        return {
            "purpose": "conversation",
            "status": "granted",
            "policy_version": POLICY_VERSION,
            "captured_at": self.consent_captured_at,
            "memory": False,
            "analytics": False,
        }

    def start_conversation(self, owner: SignedInAccount) -> tuple[str, dict[str, Any]]:
        """Abre uma conversa com uma troca de mensagens; devolve o id e o corpo enviado."""

        status, created = self.call(
            "POST",
            "/v1/conversations",
            {"channel": "web_widget", "consent": self.consent()},
            token=owner.access_token,
        )
        self.assertEqual(status, 201, created)
        conversation_id = created["conversation"]["conversation_id"]
        message = {
            "text": "Pergunta reservada sobre a pool USDC.",
            "channel": "web_widget",
            "consent": self.consent(),
            "external_message_id": "mensagem-externa-1",
        }
        status, sent = self.call(
            "POST",
            f"/v1/conversations/{conversation_id}/messages",
            message,
            token=owner.access_token,
            headers={"Idempotency-Key": MESSAGE_IDEMPOTENCY_KEY},
        )
        self.assertEqual(status, 201, sent)
        return conversation_id, message

    def conversation_secrets(
        self, owner: SignedInAccount, conversation_id: str
    ) -> tuple[str, ...]:
        """Identificadores e texto da conversa que só a dona pode ver."""

        status, payload = self.call(
            "GET", f"/v1/conversations/{conversation_id}", token=owner.access_token
        )
        self.assertEqual(status, 200, payload)
        conversation = payload["conversation"]
        self.assertEqual(len(conversation["messages"]), 2)
        secrets = {conversation["session"]["session_id"]}
        for message in conversation["messages"]:
            secrets.update((message["message_id"], message["correlation_id"]))
            channel_identity_id = message["identity"].get("channel_identity_id")
            if channel_identity_id:
                secrets.add(channel_identity_id)
        secrets.add(conversation["messages"][0]["payload"]["text"])
        return tuple(secrets) + owner.secrets()

    def alert_ids(self, owner: SignedInAccount, query: str = "") -> list[str]:
        status, payload = self.call(
            "GET", f"/v1/alerts?page_size=100{query}", token=owner.access_token
        )
        self.assertEqual(status, 200, payload)
        return [item["alert_id"] for item in payload["items"]]

    def give_alerts_to(self, owner: SignedInAccount) -> list[str]:
        """Faz ``owner`` observar uma mudança de APY e devolve os alertas novos dela."""

        before = set(self.alert_ids(owner))
        # De 5,0% para 8,5%: variação acima do limite de 2 pontos da política.
        for apy in (5.0, 8.5):
            self.market.publish(apy=apy)
            status, payload = self.call("GET", "/v1/opportunities", token=owner.access_token)
            self.assertEqual(status, 200, payload)
        created = [alert_id for alert_id in self.alert_ids(owner) if alert_id not in before]
        self.assertTrue(created, "a mudança de mercado deveria gerar alertas para quem a observou")
        return created

    def seed_owned_data(self, owner: SignedInAccount) -> OwnedData:
        """Dá à conta conversa e alertas e monta as rotas protegidas que apontam para eles."""

        conversation_id, _ = self.start_conversation(owner)
        alert_id = self.give_alerts_to(owner)[0]
        status, listing = self.call("GET", "/v1/opportunities", token=owner.access_token)
        self.assertEqual(status, 200, listing)
        opportunity = listing["items"][0]
        question = {
            "text": "Pergunta de controle.",
            "channel": "web_widget",
            "consent": self.consent(),
        }
        routes = (
            ProtectedRoute("GET", "/v1/profile"),
            ProtectedRoute("GET", "/v1/profile/risk"),
            ProtectedRoute(
                "PUT",
                "/v1/profile/risk",
                {"declared_profile": "moderate", "answers": RISK_ANSWERS},
            ),
            ProtectedRoute("GET", "/v1/opportunities"),
            ProtectedRoute("GET", f"/v1/opportunities/{opportunity['opportunity_id']}"),
            ProtectedRoute(
                "POST",
                "/v1/simulations",
                {
                    "opportunity_id": opportunity["opportunity_id"],
                    "amount": 1000,
                    "asset": opportunity["asset"],
                    "horizons_days": [30, 180, 365],
                },
            ),
            ProtectedRoute("POST", "/v1/recommendations", {"intent": "discover"}),
            ProtectedRoute(
                "POST",
                "/v1/conversations",
                {"channel": "web_widget", "consent": self.consent()},
            ),
            ProtectedRoute("GET", f"/v1/conversations/{conversation_id}"),
            ProtectedRoute("POST", f"/v1/conversations/{conversation_id}/messages", question),
            ProtectedRoute("GET", "/v1/alerts"),
            ProtectedRoute("PATCH", f"/v1/alerts/{alert_id}", {"status": "read"}),
            # Por último: com credencial válida, encerra a sessão.
            ProtectedRoute("POST", "/v1/auth/logout"),
        )
        return OwnedData(conversation_id=conversation_id, alert_id=alert_id, routes=routes)

    # Conversas ------------------------------------------------------------

    def test_other_account_cannot_read_conversation(self) -> None:
        conversation_id, _ = self.start_conversation(self.ana)
        secrets = self.conversation_secrets(self.ana, conversation_id)

        status, denied = self.call(
            "GET", f"/v1/conversations/{conversation_id}", token=self.bia.access_token
        )
        self.assert_denied(status, denied, 404, "CONVERSATION_NOT_FOUND")
        self.assert_no_trace(denied, secrets)

        # Mesmo erro de uma conversa inexistente: o 404 não confirma que ela existe.
        status, missing = self.call(
            "GET", f"/v1/conversations/{MISSING_CONVERSATION_ID}", token=self.bia.access_token
        )
        self.assert_denied(status, missing, 404, "CONVERSATION_NOT_FOUND")
        self.assertEqual(denied["error"], missing["error"])

    def test_other_account_cannot_post_into_conversation(self) -> None:
        conversation_id, ana_message = self.start_conversation(self.ana)
        secrets = self.conversation_secrets(self.ana, conversation_id)
        intrusion = "Mensagem da Bia na conversa da Ana."
        attempts = {
            "canal web": {**ana_message, "text": intrusion},
            "canal simulado": {**ana_message, "text": intrusion, "channel": "simulated"},
            # Mesmo corpo e mesma Idempotency-Key da Ana: não pode devolver a resposta dela.
            "repetição da mensagem da Ana": dict(ana_message),
        }
        for label, body in attempts.items():
            with self.subTest(tentativa=label):
                status, denied = self.call(
                    "POST",
                    f"/v1/conversations/{conversation_id}/messages",
                    body,
                    token=self.bia.access_token,
                    headers={"Idempotency-Key": MESSAGE_IDEMPOTENCY_KEY},
                )
                self.assert_denied(status, denied, 404, "CONVERSATION_NOT_FOUND")
                self.assert_no_trace(denied, secrets)

        status, conversation = self.call(
            "GET", f"/v1/conversations/{conversation_id}", token=self.ana.access_token
        )
        self.assertEqual(status, 200, conversation)
        self.assertEqual(len(conversation["conversation"]["messages"]), 2)
        self.assertNotIn(intrusion, json.dumps(conversation, ensure_ascii=False))

    # Alertas --------------------------------------------------------------

    def test_other_account_cannot_mark_alert_as_read(self) -> None:
        alert_id = self.give_alerts_to(self.ana)[0]

        status, denied = self.call(
            "PATCH", f"/v1/alerts/{alert_id}", {"status": "read"}, token=self.bia.access_token
        )
        self.assert_denied(status, denied, 404, "ALERT_NOT_FOUND")
        self.assert_no_trace(denied, self.ana.secrets())

        status, missing = self.call(
            "PATCH",
            f"/v1/alerts/{MISSING_ALERT_ID}",
            {"status": "read"},
            token=self.bia.access_token,
        )
        self.assert_denied(status, missing, 404, "ALERT_NOT_FOUND")
        self.assertEqual(denied["error"], missing["error"])

        self.assertIn(alert_id, self.alert_ids(self.ana, "&unread_only=true"))

    def test_market_change_alerts_every_account_that_follows_the_market(self) -> None:
        # As duas contas já acompanhavam o mercado antes da mudança.
        for reader in (self.ana, self.bia):
            status, payload = self.call("GET", "/v1/opportunities", token=reader.access_token)
            self.assertEqual(status, 200, payload)
        before = {reader.email: set(self.alert_ids(reader)) for reader in (self.ana, self.bia)}

        # De 5,0% para 8,5%: variação acima do limite de 2 pontos da política.
        self.market.publish(apy=8.5)
        created: dict[str, set[str]] = {}
        # A Ana vê a mudança primeiro; a Bia ainda precisa receber o próprio alerta.
        for reader in (self.ana, self.bia):
            with self.subTest(conta=reader.email):
                status, payload = self.call("GET", "/v1/opportunities", token=reader.access_token)
                self.assertEqual(status, 200, payload)
                created[reader.email] = set(self.alert_ids(reader)) - before[reader.email]
                self.assertTrue(
                    created[reader.email], "cada conta deveria receber o alerta da mudança que observou"
                )
        self.assertTrue(created[self.ana.email].isdisjoint(created[self.bia.email]))

    def test_alert_listing_only_returns_own_alerts(self) -> None:
        ana_alerts = set(self.give_alerts_to(self.ana))
        bia_alerts = set(self.give_alerts_to(self.bia))
        self.assertTrue(ana_alerts.isdisjoint(bia_alerts))

        for reader, other, other_alerts in (
            (self.bia, self.ana, ana_alerts),
            (self.ana, self.bia, bia_alerts),
        ):
            for query in ("", "&unread_only=true", "&status=unread"):
                with self.subTest(leitora=reader.email, filtro=query or "nenhum"):
                    status, listing = self.call(
                        "GET", f"/v1/alerts?page_size=100{query}", token=reader.access_token
                    )
                    self.assertEqual(status, 200, listing)
                    listed = {item["alert_id"] for item in listing["items"]}
                    self.assertTrue(listed, "a conta deveria ver os próprios alertas")
                    self.assertTrue(listed.isdisjoint(other_alerts), listed & other_alerts)
                    self.assert_no_trace(listing, other.secrets())

    # Perfil ---------------------------------------------------------------

    def test_profile_routes_only_return_own_data(self) -> None:
        status, saved = self.call(
            "PUT",
            "/v1/profile/risk",
            {"declared_profile": "conservative", "answers": RISK_ANSWERS},
            token=self.ana.access_token,
        )
        self.assertEqual(status, 200, saved)

        # A Bia ainda não declarou perfil e não pode herdar o da Ana.
        status, profile = self.call("GET", "/v1/profile", token=self.bia.access_token)
        self.assertEqual(status, 200, profile)
        self.assertEqual(profile["account"]["account_id"], self.bia.account_id)
        self.assertIsNone(profile["risk_profile"])
        self.assert_no_trace(profile, self.ana.secrets())
        status, risk = self.call("GET", "/v1/profile/risk", token=self.bia.access_token)
        self.assertEqual(status, 200, risk)
        self.assertIsNone(risk["risk_profile"])
        self.assert_no_trace(risk, self.ana.secrets())

        status, saved = self.call(
            "PUT",
            "/v1/profile/risk",
            {"declared_profile": "aggressive", "answers": RISK_ANSWERS},
            token=self.bia.access_token,
        )
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["account"]["account_id"], self.bia.account_id)

        for reader, other, declared in (
            (self.ana, self.bia, "conservative"),
            (self.bia, self.ana, "aggressive"),
        ):
            with self.subTest(leitora=reader.email):
                status, profile = self.call("GET", "/v1/profile", token=reader.access_token)
                self.assertEqual(status, 200, profile)
                self.assertEqual(profile["account"]["account_id"], reader.account_id)
                self.assertEqual(profile["account"]["email"], reader.email)
                self.assertEqual(profile["risk_profile"]["declared_profile"], declared)
                self.assert_no_trace(profile, other.secrets())
                status, risk = self.call("GET", "/v1/profile/risk", token=reader.access_token)
                self.assertEqual(status, 200, risk)
                self.assertEqual(risk["risk_profile"]["declared_profile"], declared)
                self.assert_no_trace(risk, other.secrets())

    def test_retaking_the_questionnaire_creates_the_next_version_for_that_account(self) -> None:
        versions = []
        for declared in ("conservative", "aggressive"):
            status, saved = self.call(
                "PUT",
                "/v1/profile/risk",
                {"declared_profile": declared, "answers": RISK_ANSWERS},
                token=self.ana.access_token,
            )
            self.assertEqual(status, 200, saved)
            versions.append(saved["risk_profile"]["version"])
        self.assertEqual(versions, ["profile-v1", "profile-v2"])

        status, risk = self.call("GET", "/v1/profile/risk", token=self.ana.access_token)
        self.assertEqual(status, 200, risk)
        self.assertEqual(risk["risk_profile"]["declared_profile"], "aggressive")
        self.assertEqual(risk["risk_profile"]["version"], "profile-v2")

        # A numeração é de cada conta: a primeira declaração da Bia é a v1.
        status, saved = self.call(
            "PUT",
            "/v1/profile/risk",
            {"declared_profile": "moderate", "answers": RISK_ANSWERS},
            token=self.bia.access_token,
        )
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["risk_profile"]["version"], "profile-v1")

    def test_identity_fields_in_body_do_not_change_the_owner(self) -> None:
        forged = {"account_id": self.ana.account_id, "email": self.ana.email}

        status, saved = self.call(
            "PUT",
            "/v1/profile/risk",
            {"declared_profile": "aggressive", "answers": RISK_ANSWERS, **forged},
            token=self.bia.access_token,
        )
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["account"]["account_id"], self.bia.account_id)
        status, ana_risk = self.call("GET", "/v1/profile/risk", token=self.ana.access_token)
        self.assertEqual(status, 200, ana_risk)
        self.assertIsNone(ana_risk["risk_profile"])

        status, created = self.call(
            "POST",
            "/v1/conversations",
            {"channel": "web_widget", "consent": self.consent(), **forged},
            token=self.bia.access_token,
        )
        self.assertEqual(status, 201, created)
        self.assert_no_trace(created, self.ana.secrets())
        conversation_id = created["conversation"]["conversation_id"]
        status, denied = self.call(
            "GET", f"/v1/conversations/{conversation_id}", token=self.ana.access_token
        )
        self.assert_denied(status, denied, 404, "CONVERSATION_NOT_FOUND")
        status, own = self.call(
            "GET", f"/v1/conversations/{conversation_id}", token=self.bia.access_token
        )
        self.assertEqual(status, 200, own)

    def test_idempotency_key_does_not_replay_other_account_response(self) -> None:
        body = {"declared_profile": "conservative", "answers": RISK_ANSWERS}
        headers = {"Idempotency-Key": "perfil-de-risco-1"}
        status, first = self.call(
            "PUT", "/v1/profile/risk", body, token=self.ana.access_token, headers=headers
        )
        self.assertEqual(status, 200, first)
        self.assertEqual(first["account"]["account_id"], self.ana.account_id)

        # Mesma chave e mesmo corpo vindos da Bia: processa para ela, sem reusar a resposta da Ana.
        status, second = self.call(
            "PUT", "/v1/profile/risk", body, token=self.bia.access_token, headers=headers
        )
        self.assertEqual(status, 200, second)
        self.assertEqual(second["account"]["account_id"], self.bia.account_id)
        self.assert_no_trace(second, self.ana.secrets())
        status, risk = self.call("GET", "/v1/profile/risk", token=self.bia.access_token)
        self.assertEqual(status, 200, risk)
        self.assertEqual(risk["risk_profile"]["declared_profile"], "conservative")

    def test_idempotency_key_still_replays_after_session_refresh(self) -> None:
        body = {"declared_profile": "conservative", "answers": RISK_ANSWERS}
        headers = {"Idempotency-Key": "perfil-apos-renovacao"}
        status, first = self.call(
            "PUT", "/v1/profile/risk", body, token=self.ana.access_token, headers=headers
        )
        self.assertEqual(status, 200, first)

        status, refreshed = self.call(
            "POST", "/v1/auth/refresh", {"refresh_token": self.ana.refresh_token}
        )
        self.assertEqual(status, 200, refreshed)
        new_token = refreshed["session"]["access_token"]
        self.assertNotEqual(new_token, self.ana.access_token)

        # O cliente repete o pedido com o token novo: devolve a resposta original.
        status, replayed = self.call(
            "PUT", "/v1/profile/risk", body, token=new_token, headers=headers
        )
        self.assertEqual(status, 200, replayed)
        self.assertEqual(replayed["risk_profile"], first["risk_profile"])
        status, risk = self.call("GET", "/v1/profile/risk", token=new_token)
        self.assertEqual(status, 200, risk)
        self.assertEqual(risk["risk_profile"]["declared_at"], first["risk_profile"]["declared_at"])

        status, conflict = self.call(
            "PUT",
            "/v1/profile/risk",
            {**body, "declared_profile": "aggressive"},
            token=new_token,
            headers=headers,
        )
        self.assert_denied(status, conflict, 409, "IDEMPOTENCY_KEY_CONFLICT")

    # Sessão ---------------------------------------------------------------

    def test_protected_routes_reject_missing_or_invalid_credentials(self) -> None:
        owned = self.seed_owned_data(self.ana)
        credentials = {
            "sem cabeçalho": {},
            "token desconhecido": {"Authorization": "Bearer token-que-nao-existe"},
            "Bearer sem token": {"Authorization": "Bearer "},
            "token sem esquema": {"Authorization": self.ana.access_token},
            "esquema Basic": {"Authorization": f"Basic {self.ana.access_token}"},
            "refresh token como access token": {
                "Authorization": f"Bearer {self.ana.refresh_token}"
            },
        }
        for route in owned.routes:
            for label, headers in credentials.items():
                with self.subTest(rota=str(route), credencial=label):
                    status, payload = self.call(
                        route.method, route.target, route.body, headers=headers
                    )
                    self.assert_denied(status, payload, 401, AUTHENTICATION_FAILED)
                    self.assert_no_trace(payload, self.ana.secrets())

        # Nenhuma tentativa negada mexeu nos dados da Ana.
        self.assertIn(owned.alert_id, self.alert_ids(self.ana, "&unread_only=true"))
        status, risk = self.call("GET", "/v1/profile/risk", token=self.ana.access_token)
        self.assertEqual(status, 200, risk)
        self.assertIsNone(risk["risk_profile"])
        status, conversation = self.call(
            "GET", f"/v1/conversations/{owned.conversation_id}", token=self.ana.access_token
        )
        self.assertEqual(status, 200, conversation)
        self.assertEqual(len(conversation["conversation"]["messages"]), 2)

        # Controle positivo: com a sessão da Ana, cada rota da tabela funciona.
        for route in owned.routes:
            with self.subTest(rota=str(route), credencial="sessão válida"):
                status, payload = self.call(
                    route.method, route.target, route.body, token=self.ana.access_token
                )
                self.assertTrue(200 <= status < 300, (status, payload))

    def test_logout_revokes_old_token_on_every_route(self) -> None:
        owned = self.seed_owned_data(self.ana)
        status, payload = self.call("POST", "/v1/auth/logout", token=self.ana.access_token)
        self.assertEqual(status, 204, payload)

        for route in owned.routes:
            with self.subTest(rota=str(route)):
                status, payload = self.call(
                    route.method, route.target, route.body, token=self.ana.access_token
                )
                self.assert_denied(status, payload, 401, AUTHENTICATION_FAILED)
        status, payload = self.call(
            "POST", "/v1/auth/refresh", {"refresh_token": self.ana.refresh_token}
        )
        self.assert_denied(status, payload, 401, AUTHENTICATION_FAILED)

        # O logout da Ana não derruba a sessão da Bia.
        status, payload = self.call("GET", "/v1/profile", token=self.bia.access_token)
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["account"]["account_id"], self.bia.account_id)

        # Novo login devolve acesso aos mesmos dados; o token antigo segue recusado.
        again = self.sign_in(self.ana.email, source_ip="198.51.100.11")
        self.assertEqual(again.account_id, self.ana.account_id)
        self.assertNotEqual(again.access_token, self.ana.access_token)
        status, payload = self.call(
            "GET", f"/v1/conversations/{owned.conversation_id}", token=again.access_token
        )
        self.assertEqual(status, 200, payload)
        status, payload = self.call("GET", "/v1/profile", token=self.ana.access_token)
        self.assert_denied(status, payload, 401, AUTHENTICATION_FAILED)

    def test_refresh_retires_previous_tokens(self) -> None:
        status, refreshed = self.call(
            "POST", "/v1/auth/refresh", {"refresh_token": self.ana.refresh_token}
        )
        self.assertEqual(status, 200, refreshed)
        session = refreshed["session"]

        status, payload = self.call("GET", "/v1/profile", token=self.ana.access_token)
        self.assert_denied(status, payload, 401, AUTHENTICATION_FAILED)
        status, payload = self.call(
            "POST", "/v1/auth/refresh", {"refresh_token": self.ana.refresh_token}
        )
        self.assert_denied(status, payload, 401, AUTHENTICATION_FAILED)

        status, payload = self.call("GET", "/v1/profile", token=session["access_token"])
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["account"]["account_id"], self.ana.account_id)


class SqliteAuthorizationTests(CrossAccountAuthorizationSuite, unittest.TestCase):
    """Isolamento entre contas com persistência SQLite em arquivo temporário."""

    persistence_kind = "sqlite"


class InMemoryAuthorizationTests(CrossAccountAuthorizationSuite, unittest.TestCase):
    """Isolamento entre contas no modo em memória do desenvolvimento local."""

    persistence_kind = "memory"


if __name__ == "__main__":
    unittest.main()
