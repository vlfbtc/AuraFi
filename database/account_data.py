"""Regras de exportação, exclusão e retenção de dados de uma conta.

Compartilhadas pelos adapters SQLite e PostgreSQL para que os dois apliquem a
mesma ordem de exclusão (filhos antes dos pais, respeitando as chaves
estrangeiras ``ON DELETE RESTRICT``) e omitam as mesmas colunas secretas.
Cada adapter informa o prefixo de schema, o marcador de parâmetro e quais
tabelas existem no seu banco.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from typing import Any, Iterable, Mapping

EXPORT_VERSION = "1.0"

# Prazos de retenção aplicados pela rotina de limpeza.
OTP_CHALLENGE_GRACE = timedelta(hours=24)
IDEMPOTENCY_RETENTION = timedelta(hours=24)
UNVERIFIED_ACCOUNT_RETENTION = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class AccountTable:
    """Uma tabela com dados da conta, na ordem em que pode ser apagada."""

    table: str
    where: str
    """Condição com ``{s}`` (prefixo de schema) e ``{p}`` (marcador do parâmetro)."""
    parameter: str = "account"
    """``account`` usa o account_id; ``email`` usa o e-mail da conta."""
    section: str | None = None
    """Seção do arquivo exportado; ``None`` não exporta (cache ou estado interno)."""
    omit: tuple[str, ...] = ()
    """Colunas nunca exportadas, como resumos de tokens e de códigos."""


_ACCOUNT = "account_id = {p}"

ACCOUNT_TABLES: tuple[AccountTable, ...] = (
    AccountTable("decision_history", _ACCOUNT, section="decisions"),
    AccountTable("allocation_plans", _ACCOUNT, section="saved_plans"),
    AccountTable(
        "recommendation_items",
        "recommendation_id IN (SELECT recommendation_id FROM {s}recommendations WHERE account_id = {p})",
        section="recommendation_items",
    ),
    AccountTable("recommendations", _ACCOUNT, section="recommendations"),
    AccountTable("messages", _ACCOUNT, section="messages"),
    AccountTable("conversation_runtime_state", _ACCOUNT),
    AccountTable("conversations", _ACCOUNT, section="conversations"),
    AccountTable(
        "simulation_scenarios",
        "simulation_id IN (SELECT simulation_id FROM {s}simulations WHERE account_id = {p})",
        section="simulation_scenarios",
    ),
    AccountTable("simulations", _ACCOUNT, section="simulations"),
    AccountTable("alerts", _ACCOUNT, section="alerts"),
    AccountTable(
        "risk_profile_answers",
        "risk_profile_id IN (SELECT risk_profile_id FROM {s}risk_profiles WHERE account_id = {p})",
        section="risk_profile_answers",
    ),
    AccountTable("risk_profiles", _ACCOUNT, section="risk_profiles"),
    AccountTable("consents", _ACCOUNT, section="consents"),
    AccountTable("channel_identities", _ACCOUNT, section="channel_identities"),
    AccountTable(
        "idempotent_responses",
        "principal IN (SELECT access_token_digest FROM {s}sessions WHERE account_id = {p} "
        "UNION SELECT refresh_token_digest FROM {s}sessions WHERE account_id = {p})",
    ),
    AccountTable(
        "sessions",
        _ACCOUNT,
        section="sessions",
        omit=("access_token_digest", "refresh_token_digest"),
    ),
    AccountTable(
        "otp_challenges",
        "email = {p}",
        parameter="email",
        section="access_codes",
        omit=("otp_digest",),
    ),
    AccountTable("accounts", _ACCOUNT, section="account"),
)

# Tabelas que referenciam a conta; uma conta não verificada só é removida
# quando nenhuma delas tem linhas dela.
ACCOUNT_DEPENDENT_TABLES: tuple[str, ...] = tuple(
    spec.table
    for spec in ACCOUNT_TABLES
    if spec.where == _ACCOUNT and spec.table != "accounts"
)

_JSON_COLUMNS = frozenset(
    {"payload", "audit_llm", "audit_data_sources", "assumptions", "state", "response_payload", "risk_dimensions"}
)


def statements(
    available_tables: Iterable[str], *, schema: str, placeholder: str
) -> list[tuple[AccountTable, str, int]]:
    """Condições prontas por tabela existente, com a quantidade de parâmetros."""

    available = set(available_tables)
    prefix = f"{schema}." if schema else ""
    prepared: list[tuple[AccountTable, str, int]] = []
    for spec in ACCOUNT_TABLES:
        if spec.table not in available:
            continue
        condition = spec.where.format(s=prefix, p=placeholder)
        prepared.append((spec, condition, condition.count(placeholder)))
    return prepared


def build_export(
    sections: Mapping[str, list[Mapping[str, Any]]], *, generated_at: datetime
) -> dict[str, Any]:
    """Monta o arquivo "Baixar meus dados" a partir das linhas de cada seção."""

    def rows(name: str) -> list[dict[str, Any]]:
        return [_json_safe(dict(row)) for row in sections.get(name, [])]

    accounts = rows("account")
    messages = rows("messages")
    answers = rows("risk_profile_answers")
    scenarios = rows("simulation_scenarios")
    items = rows("recommendation_items")

    conversations = rows("conversations")
    for conversation in conversations:
        conversation["messages"] = [
            message for message in messages if message.get("conversation_id") == conversation.get("conversation_id")
        ]
    risk_profiles = rows("risk_profiles")
    for profile in risk_profiles:
        profile["answers"] = [
            answer for answer in answers if answer.get("risk_profile_id") == profile.get("risk_profile_id")
        ]
    simulations = rows("simulations")
    for simulation in simulations:
        simulation["scenarios"] = [
            scenario for scenario in scenarios if scenario.get("simulation_id") == simulation.get("simulation_id")
        ]
    recommendations = rows("recommendations")
    for recommendation in recommendations:
        recommendation["items"] = [
            item for item in items if item.get("recommendation_id") == recommendation.get("recommendation_id")
        ]

    return {
        "export_version": EXPORT_VERSION,
        "generated_at": _isoformat(generated_at),
        "account": accounts[0] if accounts else None,
        "consents": rows("consents"),
        "risk_profiles": risk_profiles,
        "conversations": conversations,
        "simulations": simulations,
        "recommendations": recommendations,
        "saved_plans": rows("saved_plans"),
        "decisions": rows("decisions"),
        "alerts": rows("alerts"),
        "sessions": rows("sessions"),
        "channel_identities": rows("channel_identities"),
        "access_codes": rows("access_codes"),
    }


def retention_cutoffs(now: datetime) -> dict[str, datetime]:
    """Instantes antes dos quais cada tipo de registro expira."""

    moment = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return {
        "otp_challenges": moment - OTP_CHALLENGE_GRACE,
        "idempotent_responses": moment - IDEMPOTENCY_RETENTION,
        "unverified_accounts": moment - UNVERIFIED_ACCOUNT_RETENTION,
    }


def _json_safe(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return _isoformat(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return None
    if isinstance(value, str) and key in _JSON_COLUMNS:
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _isoformat(value: datetime) -> str:
    moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
