"""Limpeza de retenção em produção (pendência da banca).

Em produção, a API só apaga registros vencidos com ``AURAFI_RETENTION_PURGE``
igual a ``true``, e o ``render.yaml`` não declarava a variável: a limpeza
ficava desligada. Os testes sobem a API com as variáveis de produção do
``render.yaml``, gravam registros vencidos e válidos e mostram quais sobram
depois da primeira requisição.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from services.api import create_app
from services.api.app import Request
from services.conversation import DeterministicMockLlm
from tests.unit.test_render_blueprint import render_env


class _FakeOtpDelivery:
    def deliver(self, message) -> None:
        del message


class ProductionRetentionTests(unittest.TestCase):
    def production_app(self, *, from_render: bool):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        render = render_env("aurafi-api")
        environment = {
            "AURAFI_ENV": render["AURAFI_ENV"],
            "AURAFI_DB_PATH": os.path.join(directory.name, "production.sqlite3"),
            "AURAFI_OTP_HMAC_PEPPER": "test-only-pepper-with-at-least-32-bytes",
            "DATABASE_URL": "",
            "AURAFI_RETENTION_PURGE": render.get("AURAFI_RETENTION_PURGE", "") if from_render else "",
        }
        patcher = patch.dict(os.environ, environment, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        app = create_app(otp_delivery=_FakeOtpDelivery(), llm=DeterministicMockLlm())
        self.addCleanup(app.close)
        self.assertTrue(app.is_production)
        return app

    def seed(self, repository) -> None:
        now = datetime.now(timezone.utc)
        repository.save_account(
            {"account_id": "acc_antiga", "email": "antiga@example.com", "created_at": now - timedelta(days=10)}
        )
        repository.save_account(
            {"account_id": "acc_recente", "email": "recente@example.com", "created_at": now - timedelta(days=1)}
        )
        for challenge_id, created in (("chl_vencido", now - timedelta(days=3)), ("chl_valido", now)):
            repository.save_otp_challenge(
                {
                    "challenge_id": challenge_id,
                    "email": "recente@example.com",
                    "channel": "web_widget",
                    "delivery": "email",
                    "otp_digest": f"digest-{challenge_id}",
                    "created_at": created,
                    "expires_at": created + timedelta(minutes=5),
                }
            )
        for key, created in (("idem_antiga", now - timedelta(days=2)), ("idem_recente", now)):
            repository.save_idempotent_response(
                principal="acc_recente",
                route="POST /v1/simulations",
                idempotency_key=key,
                request_hash="hash",
                response_status=201,
                response_payload={"ok": True},
                created_at=created,
            )

    @staticmethod
    def records(repository) -> dict[str, bool]:
        return {
            "conta nunca confirmada há 10 dias": repository.get_account("acc_antiga") is not None,
            "conta nunca confirmada há 1 dia": repository.get_account("acc_recente") is not None,
            "código vencido há 3 dias": repository.get_otp_challenge("chl_vencido") is not None,
            "código válido": repository.get_otp_challenge("chl_valido") is not None,
            "idempotência de 2 dias": repository.get_idempotent_response(
                "acc_recente", "POST /v1/simulations", "idem_antiga"
            ) is not None,
            "idempotência recente": repository.get_idempotent_response(
                "acc_recente", "POST /v1/simulations", "idem_recente"
            ) is not None,
            "conta inicial": repository.get_account("acc_maria") is not None,
        }

    def test_producao_com_o_render_yaml_descarta_os_registros_vencidos(self) -> None:
        app = self.production_app(from_render=True)
        repository = app.persistence
        self.seed(repository)
        before = self.records(repository)
        self.assertTrue(all(before.values()), before)

        with self.assertLogs("aurafi.security", level="INFO") as captured:
            response = app.handle(Request(method="GET", target="/health", headers={}, body=None))
        self.assertEqual(response.status, 200)

        after = self.records(repository)
        self.assertEqual(
            after,
            {
                "conta nunca confirmada há 10 dias": False,
                "conta nunca confirmada há 1 dia": True,
                "código vencido há 3 dias": False,
                "código válido": True,
                "idempotência de 2 dias": False,
                "idempotência recente": True,
                "conta inicial": True,
            },
        )
        events = [json.loads(line.split(":", 2)[2]) for line in captured.output]
        purge = next(event for event in events if event["event"] == "retention.purge_completed")
        self.assertEqual(purge["removed_unverified_accounts"], 1)
        self.assertEqual(purge["removed_otp_challenges"], 1)
        self.assertEqual(purge["removed_idempotent_responses"], 1)

    def test_producao_sem_a_variavel_mantinha_tudo(self) -> None:
        # Como estava antes: em produção, sem AURAFI_RETENTION_PURGE, nada é apagado.
        app = self.production_app(from_render=False)
        repository = app.persistence
        self.seed(repository)
        app.handle(Request(method="GET", target="/health", headers={}, body=None))
        self.assertTrue(all(self.records(repository).values()))


if __name__ == "__main__":
    unittest.main()
