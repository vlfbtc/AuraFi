"""Direitos do titular, limites de uso e trilha de auditoria da API.

Cobre "Baixar meus dados", "Apagar minha conta" (com confirmação por código
enviado ao e-mail), o limite de mensagens à Aura por conta, os cabeçalhos de
segurança das respostas, os eventos de auditoria e a rotina de retenção.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
import json
import os
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from services.api import create_app, create_server
from services.api.app import Request
from services.conversation import DeterministicMockLlm

CONSENT = {"purpose": "conversation", "status": "granted", "policy_version": "aurafi-privacy-2026-09"}
ANSWERS = [{"question_id": f"q{i}", "answer": "resposta declarada"} for i in range(1, 6)]


class AccountPrivacyTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        environment = patch.dict(
            os.environ,
            {
                "AURAFI_DB_PATH": os.path.join(directory.name, "privacy.sqlite3"),
                "AURAFI_ALLOW_SELF_SIGNUP": "true",
                "AURAFI_LLM_REQUEST_LIMIT": "3",
            },
            clear=False,
        )
        environment.start()
        self.addCleanup(environment.stop)
        self.app = create_app(market_mode="test", llm=DeterministicMockLlm())
        self.addCleanup(self.app.close)

    def call(self, method: str, path: str, body: dict | None = None, token: str | None = None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.app.handle(Request(method=method, target=path, headers=headers, body=body))

    def request_code(self, email: str) -> tuple[str, str]:
        requested = self.call("POST", "/v1/auth/otp/request", {"email": email, "channel": "web_widget"})
        self.assertEqual(requested.status, 202)
        challenge_id = requested.payload["challenge_id"]
        return challenge_id, self.app.otp_sink.code_for(challenge_id)

    def login(self, email: str) -> str:
        challenge_id, code = self.request_code(email)
        verified = self.call("POST", "/v1/auth/otp/verify", {"challenge_id": challenge_id, "otp": code})
        self.assertEqual(verified.status, 200)
        return verified.payload["session"]["access_token"]

    def populate(self, token: str) -> str:
        self.assertEqual(
            self.call(
                "PUT", "/v1/profile/risk", {"declared_profile": "moderate", "answers": ANSWERS}, token
            ).status,
            200,
        )
        created = self.call("POST", "/v1/conversations", {"channel": "web_widget", "consent": CONSENT}, token)
        self.assertEqual(created.status, 201)
        conversation_id = created.payload["conversation"]["conversation_id"]
        sent = self.call(
            "POST",
            f"/v1/conversations/{conversation_id}/messages",
            {"text": "Explique os riscos.", "channel": "web_widget", "consent": CONSENT},
            token,
        )
        self.assertEqual(sent.status, 201)
        return conversation_id

    def test_exportacao_traz_os_dados_da_conta_sem_segredos(self) -> None:
        token = self.login("dona@example.com")
        conversation_id = self.populate(token)
        other = self.login("vizinha@example.com")
        self.populate(other)

        exported = self.call("GET", "/v1/account/export", token=token)

        self.assertEqual(exported.status, 200)
        document = exported.payload
        self.assertEqual(document["export_version"], "1.0")
        self.assertEqual(document["account"]["email"], "dona@example.com")
        self.assertEqual([c["conversation_id"] for c in document["conversations"]], [conversation_id])
        self.assertEqual(len(document["conversations"][0]["messages"]), 2)
        self.assertEqual(len(document["risk_profiles"][0]["answers"]), 5)
        self.assertEqual(len(document["consents"]), 1)
        self.assertTrue(document["sessions"])
        self.assertIn("aurafi-meus-dados-", exported.headers["Content-Disposition"])
        serialized = json.dumps(document)
        for forbidden in ("access_token_digest", "refresh_token_digest", "otp_digest", token, "vizinha@example.com"):
            self.assertNotIn(forbidden, serialized)

    def test_exportacao_tem_limite_por_hora(self) -> None:
        token = self.login("limite@example.com")
        for _ in range(5):
            self.assertEqual(self.call("GET", "/v1/account/export", token=token).status, 200)
        self.assertEqual(self.call("GET", "/v1/account/export", token=token).status, 429)

    def test_exclusao_exige_codigo_novo_e_apaga_todos_os_dados(self) -> None:
        token = self.login("apagar@example.com")
        conversation_id = self.populate(token)
        other = self.login("fica@example.com")
        self.populate(other)
        account_id = self.app.persistence.find_account_by_email("apagar@example.com")["account_id"]

        missing = self.call("POST", "/v1/account/deletion", {}, token)
        self.assertEqual(missing.status, 400)
        challenge_id, code = self.request_code("apagar@example.com")
        wrong = self.call("POST", "/v1/account/deletion", {"challenge_id": challenge_id, "otp": "000000"}, token)
        self.assertEqual(wrong.status, 401)
        self.assertIsNotNone(self.app.persistence.get_account(account_id))

        deleted = self.call("POST", "/v1/account/deletion", {"challenge_id": challenge_id, "otp": code}, token)

        self.assertEqual(deleted.status, 200)
        self.assertEqual(deleted.payload["status"], "deleted")
        self.assertIsNone(self.app.persistence.get_account(account_id))
        self.assertIsNone(self.app.persistence.find_account_by_email("apagar@example.com"))
        self.assertIsNone(self.app.persistence.get_latest_risk_profile(account_id))
        self.assertEqual(self.app.persistence.list_messages(conversation_id), [])
        self.assertEqual(self.call("GET", "/v1/profile", token=token).status, 401)
        self.assertEqual(self.call("GET", "/v1/profile", token=other).status, 200)
        self.assertEqual(
            self.call("GET", "/v1/account/export", token=other).payload["account"]["email"], "fica@example.com"
        )
        again = self.login("apagar@example.com")
        fresh = self.call("GET", "/v1/account/export", token=again).payload
        self.assertEqual(fresh["conversations"], [])
        self.assertEqual(fresh["risk_profiles"], [])

    def test_exclusao_com_codigo_de_outro_email_e_recusada(self) -> None:
        token = self.login("alvo@example.com")
        self.login("intrusa@example.com")
        challenge_id, code = self.request_code("intrusa@example.com")

        refused = self.call("POST", "/v1/account/deletion", {"challenge_id": challenge_id, "otp": code}, token)

        self.assertEqual(refused.status, 401)
        self.assertIsNotNone(self.app.persistence.find_account_by_email("alvo@example.com"))

    def test_sessao_invalida_nao_revela_se_a_conversa_existe(self) -> None:
        token = self.login("existe@example.com")
        created = self.call("POST", "/v1/conversations", {"channel": "web_widget", "consent": CONSENT}, token)
        existing = created.payload["conversation"]["conversation_id"]
        message = {"text": "Oi", "channel": "web_widget", "consent": CONSENT}

        for conversation_id in (existing, "cnv_inexistente"):
            self.assertEqual(self.call("GET", f"/v1/conversations/{conversation_id}", token="invalido").status, 401)
            self.assertEqual(
                self.call("POST", f"/v1/conversations/{conversation_id}/messages", message, "invalido").status, 401
            )
        self.assertEqual(self.call("POST", "/v1/conversations", {"channel": "desconhecido"}, "invalido").status, 401)

    def test_limite_da_aura_vale_para_a_conta_e_nao_para_a_sessao(self) -> None:
        first = self.login("aura@example.com")
        second = self.login("aura@example.com")
        created = self.call("POST", "/v1/conversations", {"channel": "web_widget", "consent": CONSENT}, first)
        path = f"/v1/conversations/{created.payload['conversation']['conversation_id']}/messages"
        body = {"text": "Qual o risco?", "channel": "web_widget", "consent": CONSENT}

        statuses = [self.call("POST", path, body, token).status for token in (first, first, second, second)]

        self.assertEqual(statuses, [201, 201, 201, 429])

    def test_eventos_de_auditoria_nao_registram_dados_sensiveis(self) -> None:
        with self.assertLogs("aurafi.security", level="INFO") as captured:
            challenge_id, code = self.request_code("auditoria@example.com")
            self.call("POST", "/v1/auth/otp/verify", {"challenge_id": challenge_id, "otp": "000000"})
            verified = self.call("POST", "/v1/auth/otp/verify", {"challenge_id": challenge_id, "otp": code})
            token = verified.payload["session"]["access_token"]
            self.call("GET", "/v1/account/export", token=token)
            self.call("GET", "/v1/profile", token="token-invalido")
            with patch.object(self.app, "_opportunities", side_effect=RuntimeError("falhou auditoria@example.com")):
                self.assertEqual(self.call("GET", "/v1/opportunities", token=token).status, 500)

        events = [json.loads(line.split(":", 2)[2]) for line in captured.output]
        names = [event["event"] for event in events]
        for expected in (
            "retention.purge_completed",
            "auth.otp_requested",
            "auth.otp_verification_failed",
            "auth.account_created",
            "auth.login_succeeded",
            "privacy.data_exported",
            "auth.request_rejected",
            "system.internal_error",
        ):
            self.assertIn(expected, names)
        internal = next(event for event in events if event["event"] == "system.internal_error")
        self.assertEqual(internal["error_type"], "RuntimeError")
        self.assertEqual(internal["severity"], "error")
        text = "\n".join(captured.output)
        for secret in ("auditoria@example.com", code, token, "token-invalido"):
            self.assertNotIn(secret, text)

    def test_retencao_remove_codigos_vencidos_e_contas_nunca_confirmadas(self) -> None:
        repository = self.app.persistence
        # O primeiro acesso já dispara a limpeza automática da hora corrente.
        self.assertTrue(self.login("confirmada@example.com"))
        now = datetime.now(timezone.utc)
        repository.save_account(
            {"account_id": "acc_antiga", "email": "antiga@example.com", "created_at": now - timedelta(days=10)}
        )
        repository.save_account(
            {"account_id": "acc_recente", "email": "recente@example.com", "created_at": now - timedelta(days=1)}
        )
        repository.save_otp_challenge(
            {
                "challenge_id": "chl_vencido",
                "email": "antiga@example.com",
                "channel": "web_widget",
                "delivery": "mock",
                "otp_digest": "digest-de-teste",
                "created_at": now - timedelta(days=3),
                "expires_at": now - timedelta(days=3) + timedelta(minutes=5),
            }
        )
        counts = repository.purge_expired_records(keep_account_ids=("acc_maria",))

        self.assertEqual(counts["unverified_accounts"], 1)
        self.assertEqual(counts["otp_challenges"], 1)
        self.assertIsNone(repository.get_account("acc_antiga"))
        self.assertIsNotNone(repository.get_account("acc_recente"))
        self.assertIsNotNone(repository.get_account("acc_maria"))
        self.assertIsNotNone(repository.find_account_by_email("confirmada@example.com"))


class RetentionSwitchTests(unittest.TestCase):
    def test_limpeza_automatica_pode_ser_desligada(self) -> None:
        with TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"AURAFI_DB_PATH": os.path.join(directory, "off.sqlite3"), "AURAFI_RETENTION_PURGE": "off"},
            clear=False,
        ):
            app = create_app(market_mode="test", llm=DeterministicMockLlm())
            try:
                with self.assertLogs("aurafi.security", level="INFO") as captured:
                    app.handle(Request(method="GET", target="/health", headers={}, body=None))
                    app.handle(
                        Request(
                            method="POST",
                            target="/v1/auth/otp/request",
                            headers={},
                            body={"email": "maria@example.com", "channel": "web_widget"},
                        )
                    )
            finally:
                app.close()
        self.assertFalse(any("retention.purge_completed" in line for line in captured.output))


class SecurityHeadersTests(unittest.TestCase):
    def test_respostas_da_api_trazem_cabecalhos_de_seguranca(self) -> None:
        app = create_app(market_mode="test", llm=DeterministicMockLlm())
        server = create_server(app, port=0)
        server.start_background()
        connection = HTTPConnection(*server.address, timeout=3)
        try:
            connection.request("GET", "/health")
            response = connection.getresponse()
            response.read()
        finally:
            connection.close()
            server.shutdown()

        self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.getheader("X-Frame-Options"), "DENY")
        self.assertEqual(response.getheader("Referrer-Policy"), "no-referrer")
        self.assertIn("default-src 'none'", response.getheader("Content-Security-Policy"))
        self.assertIsNone(response.getheader("Strict-Transport-Security"))


if __name__ == "__main__":
    unittest.main()
