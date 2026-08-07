"""Invariantes estáticas do OpenAPI e do envelope canônico (BE-009).

Este módulo não instala parser YAML nem gera código. A validação intencionalmente
usa texto normativo e fixtures, evitando dependência de rede ou de ferramentas
externas durante o gate.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPENAPI = ROOT / "contracts" / "openapi.yaml"
ENVELOPE = ROOT / "contracts" / "message-envelope.md"


def schema_block(document: str, schema_name: str) -> str:
    """Extrai um bloco de schema por indentação, sem interpretar YAML."""

    marker = f"    {schema_name}:"
    start = document.find(marker)
    if start < 0:
        raise AssertionError(f"schema {schema_name!r} ausente no OpenAPI")
    tail = document[start + len(marker) :]
    next_schema = re.search(r"\n    [A-Za-z][A-Za-z0-9_]*:\n", tail)
    return tail[: next_schema.start() if next_schema else len(tail)]


class ContractStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.openapi = OPENAPI.read_text(encoding="utf-8")
        cls.envelope = ENVELOPE.read_text(encoding="utf-8")

    def test_openapi_declara_escopo_mvp_sem_wallet_open_finance_ou_execucao(self) -> None:
        self.assertIn("openapi: 3.0.3", self.openapi)
        self.assertIn("authentication: internal_email_otp", self.openapi)
        self.assertIn("wallet_execution: excluded", self.openapi)
        self.assertIn("open_finance: excluded", self.openapi)
        self.assertIn("access: read_only", self.openapi)
        self.assertIn("mockable: true", self.openapi)
        paths = self.openapi.split("components:", 1)[0]
        self.assertNotRegex(paths, r"(?im)^  /[^\n]*(wallet|open[-_]finance|transaction)")

    def test_openapi_schemas_preservam_guardrails_obrigatorios(self) -> None:
        simulation = schema_block(self.openapi, "Simulation")
        for field in ("simulation_id", "opportunity_id", "input", "scenarios", "assumptions", "execution_supported", "disclaimer"):
            self.assertIn(field, simulation, f"Simulation deve expor {field}")
        self.assertIn("enum: [false]", simulation)
        self.assertIn("enum: [30, 180, 365]", schema_block(self.openapi, "SimulationInput"))

        recommendation = schema_block(self.openapi, "RecommendationItem")
        for field in ("opportunity_id", "suitability", "rationale", "risks", "disclaimer"):
            self.assertIn(field, recommendation, f"RecommendationItem deve expor {field}")
        self.assertIn("[aligned, caution, not_aligned, unavailable]", recommendation)

        alert = schema_block(self.openapi, "Alert")
        for field in ("alert_id", "type", "status", "created_at", "observed_at", "data_source", "suggested_action", "disclaimer"):
            self.assertIn(field, alert, f"Alert deve expor {field}")
        for event_type in ("apy_change", "risk_change", "new_opportunity", "data_stale"):
            self.assertIn(event_type, self.openapi)

    def test_openapi_envelope_tem_campos_e_tipos_normativos(self) -> None:
        envelope = schema_block(self.openapi, "MessageEnvelope")
        required = "".join(envelope.split("required:", 1)[1].split("properties:", 1)[0])
        for field in ("envelope_version", "message_id", "message_type", "occurred_at", "request_id", "correlation_id", "identity", "session", "channel", "consent", "payload", "disclaimer", "audit"):
            self.assertIn(field, required)
        self.assertIn("request_id:", envelope, "request_id deve permanecer disponível para correlação")
        self.assertIn("pattern: '^[0-9]+\\.[0-9]+$'", envelope)
        self.assertIn("[user_message, assistant_message, system_event, alert]", envelope)
        self.assertIn("additionalProperties: true", envelope)

    def test_envelope_markdown_e_openapi_repetem_regras_de_canal_fonte_e_exclusoes(self) -> None:
        for field in ("envelope_version", "message_id", "message_type", "occurred_at", "correlation_id", "identity", "session", "channel", "consent", "payload", "disclaimer", "audit"):
            self.assertIn(f"`{field}`", self.envelope)
        for channel in ("web_widget", "ios_app", "simulated"):
            self.assertIn(channel, self.envelope)
        self.assertIn("`mode: live`", self.envelope)
        for mode in ("cache", "test", "fallback"):
            self.assertIn(f"`{mode}`", self.envelope)
        self.assertIn("`read_only: true`", self.envelope)
        self.assertIn("`is_stale`", self.envelope)
        self.assertIn("não transporta wallet", self.envelope)
        self.assertIn("Open Finance", self.envelope)
        self.assertIn("execução de transação", self.envelope)

    def test_openapi_respostas_de_erro_e_correlacao_estao_documentadas(self) -> None:
        error = schema_block(self.openapi, "ErrorResponse")
        self.assertIn("required: [error, meta]", error)
        detail = schema_block(self.openapi, "ErrorDetail")
        for field in ("code", "message", "retryable"):
            self.assertIn(field, detail)
        self.assertIn("RequestIdHeader", self.openapi)
        self.assertIn("CorrelationIdHeader", self.openapi)

    def test_detalhe_documenta_historico_real_e_ptax_fail_soft(self) -> None:
        detail = schema_block(self.openapi, "OpportunityDetail")
        self.assertIn("required: [history, currency_display]", detail)
        listing = schema_block(self.openapi, "OpportunityListItem")
        self.assertIn("required: [currency_display]", listing)
        history = schema_block(self.openapi, "OpportunityHistory")
        self.assertIn("[available, unavailable]", history)
        self.assertIn("7d:", history)
        self.assertIn("30d:", history)
        apy = schema_block(self.openapi, "ApyWindowMetrics")
        for field in ("average", "minimum", "maximum", "change_percentage_points", "trend"):
            self.assertIn(field, apy)
        fx = schema_block(self.openapi, "FxQuote")
        self.assertIn("enum: [bcb_ptax]", fx)
        self.assertIn("enum: [midpoint_buy_sell]", fx)
        self.assertIn("latest_closing_bulletin", fx)
        self.assertIn("enum: [live, cache]", fx)


if __name__ == "__main__":
    unittest.main()
