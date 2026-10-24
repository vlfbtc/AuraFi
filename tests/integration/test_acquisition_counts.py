"""Contagem agregada da origem dos cadastros pela API, de ponta a ponta.

Cobre os critérios da convenção de origem: a campanha de teste soma um pedido
de código e uma conta na semana; sem origem conta como "direto"; entrar numa
conta existente não soma conta criada; valores fora da lista, inclusive um
e-mail e um texto longo, viram "outro"; a origem não fica gravada junto do
pedido de código nem da conta e não aparece no registro de eventos; e uma
falha da contagem não interrompe o login.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from services.acquisition import week_start
from services.api import create_app
from services.api.app import Request
from services.conversation import DeterministicMockLlm

CAMPAIGN = {"utm_source": "teste", "utm_medium": "video_organico", "utm_campaign": "entenda_onda1"}
EMAIL_IN_LINK = "maria.silva@example.com"
LONG_TEXT = "campanha-" + "x" * 4000


class AcquisitionCountApiTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db_path = Path(directory.name) / "acquisition.sqlite3"
        environment = patch.dict(
            os.environ,
            {"AURAFI_DB_PATH": str(self.db_path), "AURAFI_ALLOW_SELF_SIGNUP": "true"},
            clear=False,
        )
        environment.start()
        self.addCleanup(environment.stop)
        self.app = create_app(market_mode="test", llm=DeterministicMockLlm())
        self.addCleanup(self.app.close)
        self.week = week_start(datetime.now(timezone.utc)).isoformat()

    def call(self, path: str, body: dict) -> object:
        return self.app.handle(Request(method="POST", target=path, headers={}, body=body))

    def sign_in(self, email: str, attribution: object = None, *, channel: str = "web_widget") -> dict:
        body = {"email": email, "channel": channel}
        if attribution is not None:
            body["attribution"] = attribution
        requested = self.call("/v1/auth/otp/request", body)
        self.assertEqual(requested.status, 202)
        self.assertEqual(set(requested.payload), {"challenge_id", "expires_at", "delivery", "meta"})
        challenge_id = requested.payload["challenge_id"]
        verify = {"challenge_id": challenge_id, "otp": self.app.otp_sink.code_for(challenge_id)}
        if attribution is not None:
            verify["attribution"] = attribution
        verified = self.call("/v1/auth/otp/verify", verify)
        self.assertEqual(verified.status, 200)
        self.assertEqual(set(verified.payload), {"session", "meta"})
        return verified.payload

    def counts(self) -> dict[tuple[str, str, str], tuple[int, int]]:
        rows = self.app.persistence.list_acquisition_counts()
        for row in rows:
            self.assertEqual(row["week_start"], self.week)
        return {
            (row["utm_source"], row["utm_medium"], row["utm_campaign"]): (row["code_requests"], row["accounts_created"])
            for row in rows
        }

    def test_campanha_de_teste_soma_um_pedido_e_uma_conta_na_semana(self) -> None:
        self.sign_in("nova@example.com", CAMPAIGN)
        self.assertEqual(self.counts(), {("teste", "video_organico", "entenda_onda1"): (1, 1)})

    def test_sem_origem_conta_como_direto_inclusive_no_app(self) -> None:
        self.sign_in("site@example.com")
        self.sign_in("app@example.com", channel="ios_app")
        self.assertEqual(self.counts(), {("direto", "direto", "direto"): (2, 2)})

    def test_reenvio_do_codigo_soma_pedido_mas_uma_so_conta(self) -> None:
        first = self.call("/v1/auth/otp/request", {"email": "reenvio@example.com", "channel": "web_widget", "attribution": CAMPAIGN})
        self.assertEqual(first.status, 202)
        self.sign_in("reenvio@example.com", CAMPAIGN)
        self.assertEqual(self.counts(), {("teste", "video_organico", "entenda_onda1"): (2, 1)})

    def test_entrar_em_conta_existente_nao_soma_conta_nem_pedido_de_cadastro(self) -> None:
        self.sign_in("volta@example.com", CAMPAIGN)
        before = self.counts()
        self.sign_in("volta@example.com", CAMPAIGN)
        self.sign_in("volta@example.com")
        self.sign_in("maria@example.com", {"utm_source": "google"})  # conta semente, já existente
        self.assertEqual(self.counts(), before)

    def test_valor_fora_da_convencao_vira_outro_inclusive_email_e_texto_longo(self) -> None:
        self.sign_in("email@example.com", {"utm_source": EMAIL_IN_LINK, "utm_medium": "influenciador", "utm_campaign": LONG_TEXT})
        self.sign_in("malformado@example.com", "utm_source=perfil_a")
        self.sign_in("numero@example.com", {"utm_source": 42, "utm_medium": None, "gclid": "abc123", "fbclid": "def456"})
        self.assertEqual(
            self.counts(),
            {
                ("outro", "influenciador", "outro"): (1, 1),
                ("outro", "outro", "outro"): (1, 1),
                ("outro", "direto", "direto"): (1, 1),
            },
        )
        dump = self.database_dump()
        for raw in (EMAIL_IN_LINK, "campanha-xxxx", "abc123", "def456"):
            self.assertNotIn(raw, dump)

    def test_origem_nao_fica_no_pedido_de_codigo_na_conta_nem_no_registro(self) -> None:
        with self.assertLogs("aurafi.security", level="INFO") as captured:
            self.sign_in("privada@example.com", CAMPAIGN)
        for record in captured.output:
            for value in ("video_organico", "entenda_onda1", "utm_"):
                self.assertNotIn(value, record)
        inserts = [line for line in self.database_dump().splitlines() if line.startswith("INSERT INTO")]
        self.assertTrue(any(line.startswith('INSERT INTO "acquisition_weekly"') for line in inserts))
        for line in inserts:
            if not line.startswith('INSERT INTO "acquisition_weekly"'):
                self.assertNotIn("entenda_onda1", line)
                self.assertNotIn("video_organico", line)

    def test_cadastro_fechado_nao_conta_pedido(self) -> None:
        with patch.dict(os.environ, {"AURAFI_ALLOW_SELF_SIGNUP": "false"}):
            closed = create_app(market_mode="test", llm=DeterministicMockLlm())
        self.addCleanup(closed.close)
        requested = closed.handle(
            Request(
                method="POST",
                target="/v1/auth/otp/request",
                headers={},
                body={"email": "desconhecida@example.com", "channel": "web_widget", "attribution": CAMPAIGN},
            )
        )
        self.assertEqual(requested.status, 202)
        self.assertEqual(closed.persistence.list_acquisition_counts(), [])

    def test_falha_da_contagem_nao_interrompe_o_login(self) -> None:
        with patch.object(self.app._acquisition, "record_acquisition", side_effect=RuntimeError("banco indisponível")):  # noqa: SLF001
            with self.assertLogs("aurafi.security", level="WARNING") as captured:
                session = self.sign_in("resiliente@example.com", CAMPAIGN)
        self.assertTrue(session["session"]["access_token"])
        self.assertTrue(any('"event": "acquisition.count_failed"' in record for record in captured.output))
        self.assertEqual(self.counts(), {})

    def test_modo_sem_banco_conta_em_memoria(self) -> None:
        with patch.dict(os.environ, {"AURAFI_DB_PATH": ""}):
            memory = create_app(market_mode="test", llm=DeterministicMockLlm())
        self.addCleanup(memory.close)
        self.assertIsNone(memory.persistence)
        requested = memory.handle(
            Request(method="POST", target="/v1/auth/otp/request", headers={}, body={"email": "memoria@example.com", "channel": "web_widget", "attribution": CAMPAIGN})
        )
        challenge_id = requested.payload["challenge_id"]
        memory.handle(
            Request(method="POST", target="/v1/auth/otp/verify", headers={}, body={"challenge_id": challenge_id, "otp": memory.otp_sink.code_for(challenge_id), "attribution": CAMPAIGN})
        )
        rows = memory._acquisition.list_acquisition_counts()  # noqa: SLF001
        self.assertEqual([(row["utm_source"], row["code_requests"], row["accounts_created"]) for row in rows], [("teste", 1, 1)])

    def database_dump(self) -> str:
        connection = sqlite3.connect(self.db_path)
        try:
            return "\n".join(connection.iterdump())
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
