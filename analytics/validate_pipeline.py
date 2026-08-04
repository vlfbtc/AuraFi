"""Dependency-free validation for the checked-in AuraFi analytical contract.

The gate validates fixtures, dimensional coverage, hub observability measures,
LGPD minimization and dbt contract files without opening a database or network.
It complements, but does not replace, ``dbt seed && dbt run && dbt test``.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


REQUIRED_MODELS = {
    "stg_test_events", "stg_fact_enrichment", "dim_tempo", "dim_usuario",
    "dim_perfil_risco", "dim_protocolo", "dim_ativo", "dim_blockchain",
    "dim_canal", "fato_recomendacao", "fato_yield_observacao",
    "fato_interacao_conversacional", "aura_star_schema", "mvp_metrics",
    "recommendation_metrics", "market_metrics", "hub_metrics",
    "cross_channel_metrics", "product_metric_targets",
}

SEED_CONTRACTS = {
    "mvp_test_events.csv": {
        "event_id", "event_type", "test_case_id", "is_test_data", "source_system",
        "occurred_at", "user_pseudo_id", "user_version", "channel_name",
        "channel_adapter", "market_source", "market_mode", "observed_at",
        "retrieved_at", "is_stale", "read_only",
    },
    "mvp_fact_enrichment.csv": {
        "event_id", "prompt_version", "base_apr_percent", "incentive_apy_percent",
        "protocol_tvl_snapshot_usd", "apy_volatility_30d",
        "impermanent_loss_30d_percent", "liquidity_score", "recommendable_flag",
        "user_message_count", "aura_message_count", "main_topic", "csat_score",
        "generated_recommendation", "resumption_time_seconds", "context_loss_events",
        "premium_conversion_flag", "session_input_tokens", "session_output_tokens",
        "session_llm_cost_usd", "is_test_data",
    },
    "mvp_users.csv": {
        "user_pseudo_id", "user_version", "age_band", "gender", "state_code",
        "city_size", "plan", "registered_on", "acquisition_channel",
        "wallet_connected", "crypto_experience", "valid_from", "valid_to",
        "is_current", "is_test_data",
    },
    "mvp_risk_profiles.csv": {
        "risk_profile", "profile_code", "max_loss_tolerance_percent",
        "max_healthy_apy_percent", "minimum_tvl_usd", "audit_required", "is_test_data",
    },
    "mvp_protocols.csv": {
        "protocol_name", "category", "primary_blockchain", "current_tvl_usd",
        "security_score", "audit_status", "primary_auditor", "launch_year",
        "governance_token", "insurance_available", "is_test_data",
    },
    "mvp_assets.csv": {
        "asset_symbol", "full_name", "asset_type", "issuer", "backing_type",
        "peg_target", "regulation", "market_cap_usd", "launch_date", "is_test_data",
    },
    "mvp_blockchains.csv": {
        "blockchain_name", "blockchain_type", "consensus", "native_token",
        "average_gas_fee_usd", "average_tps", "finality_seconds", "mainnet_date",
        "official_bridge", "is_test_data",
    },
    "mvp_channels.csv": {
        "channel_name", "channel_type", "adapter", "adapter_version", "launch_date",
        "push_supported", "attachment_supported", "estimated_message_cost_usd",
        "simulated", "is_test_data",
    },
    "mvp_product_targets.csv": {
        "target_year", "metric_name", "target_operator", "target_value",
        "target_unit", "is_test_data",
    },
}

REQUIRED_DBT_TESTS = {
    "assert_fact_measure_ranges.sql", "assert_scd2_integrity.sql",
    "assert_cross_channel_continuity.sql", "assert_metric_ranges.sql",
    "assert_dimension_coverage.sql",
}

MODEL_FRAGMENTS = {
    "dim_tempo": ("generate_series", "2020-01-01", "2040-12-31", "hour_of_day"),
    "dim_usuario": ("user_pseudo_id", "valid_from", "valid_to", "is_current", "plan"),
    "dim_perfil_risco": ("profile_code", "max_healthy_apy_percent", "minimum_tvl_usd"),
    "fato_recomendacao": ("prompt_version", "confidence_score", "decision_time_seconds"),
    "fato_yield_observacao": (
        "risk_profile_key", "base_apr_percent", "incentive_apy_percent",
        "apy_volatility_30d", "impermanent_loss_30d_percent", "recommendable_flag",
    ),
    "fato_interacao_conversacional": (
        "user_message_count", "aura_message_count", "total_llm_tokens", "main_topic",
        "csat_score", "generated_recommendation", "resumption_time_seconds",
        "context_loss_events", "premium_conversion_flag",
    ),
    "recommendation_metrics": ("acceptance_rate", "average_simulated_ticket_usd"),
    "market_metrics": ("average_observed_apy_percent", "recommendable_pool_rate"),
    "hub_metrics": (
        "channel_engagement_share", "human_escalation_rate", "average_csat",
        "premium_conversion_rate", "context_loss_session_rate",
    ),
    "cross_channel_metrics": (
        "cross_channel_handoff_rate", "average_session_resumption_seconds",
        "context_loss_handoff_rate",
    ),
}

PII_VALUE_PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    "phone": re.compile(r"(?:\+\d[\d ()-]{7,}\d|\b\d{2,3}[- ()]\d[\d ()-]{6,}\d\b)"),
    "wallet": re.compile(r"\b0x[a-fA-F0-9]{40}\b"),
}
PII_IDENTIFIER_PATTERN = re.compile(
    r"\b(?:email|email_address|phone_number|telephone|cpf|cnpj|first_name|last_name|"
    r"wallet_address|private_key|access_token|conversation_text|message_text|raw_message)\b",
    re.IGNORECASE,
)


def text(value: object) -> str:
    return "" if value is None else str(value).strip()


def timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def decimal(value: str) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


class PipelineValidator:
    def __init__(self, analytics_root: Path) -> None:
        self.analytics_root = analytics_root
        self.dbt_root = analytics_root / "dbt"
        self.errors: list[str] = []
        self.checks: list[str] = []
        self.seeds: dict[str, list[dict[str, str]]] = {}

    def passed(self, message: str) -> None:
        self.checks.append(message)

    def failed(self, message: str) -> None:
        self.errors.append(message)

    def check_pii(self, values: list[str], location: str, *, identifiers: bool = False) -> None:
        joined = "\n".join(values)
        for kind, pattern in PII_VALUE_PATTERNS.items():
            if pattern.search(joined):
                self.failed(f"{location}: padrão de {kind} encontrado")
        if identifiers and PII_IDENTIFIER_PATTERN.search(joined):
            self.failed(f"{location}: identificador de PII encontrado")

    def load_seeds(self) -> None:
        seed_root = self.dbt_root / "seeds"
        for filename, required in SEED_CONTRACTS.items():
            path = seed_root / filename
            if not path.is_file():
                self.failed(f"seed ausente: {filename}")
                continue
            try:
                with path.open(newline="", encoding="utf-8-sig") as handle:
                    reader = csv.DictReader(handle)
                    headers = list(reader.fieldnames or [])
                    rows = list(reader)
            except (OSError, csv.Error) as error:
                self.failed(f"seed {filename} não pôde ser lido: {error}")
                continue
            missing = sorted(required - set(headers))
            if missing:
                self.failed(f"seed {filename} sem colunas: {', '.join(missing)}")
            if not rows:
                self.failed(f"seed {filename} vazio")
            if any(None in row for row in rows):
                self.failed(f"seed {filename} contém linha com colunas excedentes")
            self.check_pii(headers, f"seed {filename}/cabeçalho", identifiers=True)
            for line_number, row in enumerate(rows, 2):
                self.check_pii([text(value) for value in row.values()], f"seed {filename}:{line_number}")
                if text(row.get("is_test_data")).lower() != "true":
                    self.failed(f"seed {filename}:{line_number}: is_test_data precisa ser true")
            self.seeds[filename] = rows
            self.passed(f"seed {filename}: {len(rows)} registros e contrato completo")

    def validate_events(self) -> None:
        rows = self.seeds.get("mvp_test_events.csv", [])
        enrichment = {
            row["event_id"]: row for row in self.seeds.get("mvp_fact_enrichment.csv", [])
        }
        users = {
            (row["user_pseudo_id"], row["user_version"])
            for row in self.seeds.get("mvp_users.csv", [])
        }
        event_ids: set[str] = set()
        modes: set[str] = set()
        accepted: set[str] = set()
        session_ids: dict[str, dict[str, str]] = {}

        for line_number, row in enumerate(rows, 2):
            location = f"mvp_test_events.csv:{line_number}"
            event_id = row["event_id"]
            if not event_id or event_id in event_ids:
                self.failed(f"{location}: event_id vazio ou duplicado")
            event_ids.add(event_id)
            if event_id not in enrichment:
                self.failed(f"{location}: enriquecimento ausente")
                continue
            extra = enrichment[event_id]
            if row["event_type"] not in {"recommendation", "yield_observation", "conversation_session"}:
                self.failed(f"{location}: event_type inválido")
            if row["source_system"] != "synthetic_fixture":
                self.failed(f"{location}: source_system inválido")
            if timestamp(row["occurred_at"]) is None:
                self.failed(f"{location}: occurred_at inválido ou sem timezone")
            if not re.fullmatch(r"user_pseudo_[a-z0-9_]+", row["user_pseudo_id"]):
                self.failed(f"{location}: usuário não pseudonimizado")
            if (row["user_pseudo_id"], row["user_version"]) not in users:
                self.failed(f"{location}: versão de usuário não existe em mvp_users")

            if row["event_type"] == "recommendation":
                for field in ("recommendation_id", "protocol_name", "asset_symbol", "blockchain_name"):
                    if not row[field]:
                        self.failed(f"{location}: {field} obrigatório")
                if not extra["prompt_version"]:
                    self.failed(f"{location}: prompt_version obrigatório")
                if row["decision_accepted"]:
                    accepted.add(row["decision_accepted"].lower())

            if row["event_type"] == "yield_observation":
                for field in ("observed_at", "retrieved_at"):
                    if timestamp(row[field]) is None:
                        self.failed(f"{location}: {field} inválido")
                observed, retrieved = timestamp(row["observed_at"]), timestamp(row["retrieved_at"])
                if observed and retrieved and retrieved < observed:
                    self.failed(f"{location}: retrieved_at anterior a observed_at")
                modes.add(row["market_mode"])
                if row["market_source"] != "defillama" or row["read_only"].lower() != "true":
                    self.failed(f"{location}: fonte de mercado deve ser DeFiLlama read-only")
                for field in (
                    "base_apr_percent", "incentive_apy_percent", "protocol_tvl_snapshot_usd",
                    "apy_volatility_30d", "impermanent_loss_30d_percent",
                    "liquidity_score", "recommendable_flag",
                ):
                    if not extra[field]:
                        self.failed(f"{location}: medida {field} ausente")
                apy = decimal(row["yield_apy_percent"])
                base = decimal(extra["base_apr_percent"])
                incentive = decimal(extra["incentive_apy_percent"])
                if None not in (apy, base, incentive) and apy != base + incentive:
                    self.failed(f"{location}: APY não fecha com APR base + incentivos")

            if row["event_type"] == "conversation_session":
                session_ids[row["session_id"]] = row
                for field in (
                    "user_message_count", "aura_message_count", "main_topic",
                    "generated_recommendation", "context_loss_events",
                    "premium_conversion_flag", "session_input_tokens",
                    "session_output_tokens", "session_llm_cost_usd",
                ):
                    if not extra[field]:
                        self.failed(f"{location}: medida conversacional {field} ausente")
                user_messages = decimal(extra["user_message_count"])
                aura_messages = decimal(extra["aura_message_count"])
                total_messages = decimal(row["message_count"])
                if None not in (user_messages, aura_messages, total_messages) and total_messages != user_messages + aura_messages:
                    self.failed(f"{location}: message_count difere de usuário + Aura")
                csat = decimal(extra["csat_score"])
                if csat is not None and not Decimal(1) <= csat <= Decimal(5):
                    self.failed(f"{location}: CSAT fora de 1..5")

        if set(enrichment) != event_ids:
            self.failed("mvp_fact_enrichment precisa ter exatamente uma linha por evento")
        else:
            self.passed("enriquecimento possui cardinalidade 1:1 com os eventos")
        if not {"true", "false"}.issubset(accepted):
            self.failed("fixture precisa cobrir recomendação aceita e recusada")
        if not {"test", "fallback"}.issubset(modes):
            self.failed("fixture precisa cobrir mercado test e fallback")

        cross_channel_ok = False
        for session_id, row in session_ids.items():
            previous_id = row["previous_session_id"]
            if not previous_id:
                continue
            previous = session_ids.get(previous_id)
            if previous is None or previous["user_pseudo_id"] != row["user_pseudo_id"]:
                self.failed(f"sessão {session_id}: vínculo anterior inválido")
                continue
            if previous["channel_name"] != row["channel_name"]:
                cross_channel_ok = True
                expected = int((timestamp(row["session_started_at"]) - timestamp(previous["session_ended_at"])).total_seconds())
                actual = int(enrichment[row["event_id"]]["resumption_time_seconds"])
                if actual != expected:
                    self.failed(f"sessão {session_id}: tempo de retomada inconsistente")
        if cross_channel_ok:
            self.passed("fixture prova handoff cross-channel e tempo de retomada")
        else:
            self.failed("fixture não contém handoff cross-channel")

    def validate_scd2(self) -> None:
        by_user: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
        for row in self.seeds.get("mvp_users.csv", []):
            by_user[row["user_pseudo_id"]].append(row)
        for user_id, rows in by_user.items():
            if sum(row["is_current"].lower() == "true" for row in rows) != 1:
                self.failed(f"usuário {user_id}: SCD2 precisa de uma versão corrente")
            intervals = sorted(rows, key=lambda row: timestamp(row["valid_from"]))
            for current, following in zip(intervals, intervals[1:]):
                current_end = timestamp(current["valid_to"])
                following_start = timestamp(following["valid_from"])
                if current_end is None or following_start is None or current_end > following_start:
                    self.failed(f"usuário {user_id}: versões SCD2 sobrepostas ou abertas")
        if by_user and not any(len(rows) > 1 for rows in by_user.values()):
            self.failed("fixture SCD2 não cobre mudança de plano")
        elif by_user:
            self.passed("SCD2 cobre mudança de plano sem sobreposição")

    def validate_models(self) -> None:
        model_paths = sorted((self.dbt_root / "models").rglob("*.sql"))
        contents = {path.stem: path.read_text(encoding="utf-8") for path in model_paths}
        missing = sorted(REQUIRED_MODELS - set(contents))
        if missing:
            self.failed(f"modelos dbt ausentes: {', '.join(missing)}")
        else:
            self.passed(f"{len(REQUIRED_MODELS)} modelos dbt obrigatórios encontrados")
        for path in model_paths:
            self.check_pii([contents[path.stem]], f"modelo {path.name}", identifiers=True)
        for model, fragments in MODEL_FRAGMENTS.items():
            content = contents.get(model, "").lower()
            for fragment in fragments:
                if fragment.lower() not in content:
                    self.failed(f"modelo {model}: campo/medida ausente: {fragment}")
        if not any(error.startswith("modelo ") for error in self.errors):
            self.passed("modelos preservam o dicionário dimensional e métricas do hub")

    def validate_schema_and_tests(self) -> None:
        schema_files = sorted((self.dbt_root / "models").rglob("*.yml"))
        schema = "\n".join(path.read_text(encoding="utf-8") for path in schema_files)
        missing = sorted(model for model in REQUIRED_MODELS if f"name: {model}" not in schema)
        if missing:
            self.failed(f"schema dbt não documenta: {', '.join(missing)}")
        else:
            self.passed("schema dbt documenta todos os modelos obrigatórios")
        test_root = self.dbt_root / "tests"
        present = {path.name for path in test_root.glob("*.sql")} if test_root.is_dir() else set()
        missing_tests = sorted(REQUIRED_DBT_TESTS - present)
        if missing_tests:
            self.failed(f"testes singulares dbt ausentes: {', '.join(missing_tests)}")
        else:
            self.passed("testes dbt cobrem medidas, SCD2, dimensões, métricas e continuidade")

    def run(self) -> int:
        self.load_seeds()
        self.validate_events()
        self.validate_scd2()
        self.validate_models()
        self.validate_schema_and_tests()
        for check in self.checks:
            print(f"PASS  {check}")
        for error in self.errors:
            print(f"FAIL  {error}")
        print(f"\nResultado: {len(self.checks)} validações aprovadas; {len(self.errors)} falhas.")
        if self.errors:
            print("Ação: corrija o contrato; este gate não acessa dbt, banco ou rede.")
            return 1
        print("Limite: execute dbt seed/run/test quando um profile PostgreSQL estiver disponível.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--analytics-root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="raiz de analytics (padrão: diretório deste script)",
    )
    args = parser.parse_args()
    return PipelineValidator(args.analytics_root.resolve()).run()


if __name__ == "__main__":
    sys.exit(main())
