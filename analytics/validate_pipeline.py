"""Validate the checked-in analytical contract without external services.

The validator is deliberately static: it reads the controlled CSV and model
files only. It does not import dbt, open a database connection, use the
network, or execute SQL.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


REQUIRED_SEED_COLUMNS = {
    "event_id", "event_type", "test_case_id", "is_test_data", "source_system",
    "occurred_at", "user_pseudo_id", "user_version", "user_valid_from",
    "user_valid_to", "market_source", "market_mode", "observed_at",
    "retrieved_at", "is_stale", "read_only",
}

REQUIRED_MODELS = {
    "stg_test_events", "dim_tempo", "dim_usuario", "dim_perfil_risco",
    "dim_protocolo", "dim_ativo", "dim_blockchain", "dim_canal",
    "fato_recomendacao", "fato_yield_observacao",
    "fato_interacao_conversacional", "aura_star_schema", "mvp_metrics",
}

TIMESTAMP_COLUMNS = ("occurred_at", "user_valid_from")
MARKET_TIMESTAMP_COLUMNS = ("observed_at", "retrieved_at")

# Values and identifiers are checked separately. Generic words such as
# "token" are intentionally not forbidden because token counts are metrics.
PII_VALUE_PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    "phone": re.compile(r"(?<!\d)(?!\d{4}-\d{2}-\d{2}(?:T|\b))(?:\+?\d[\d ()-]{7,}\d)(?!\d)"),
    "wallet": re.compile(r"\b0x[a-fA-F0-9]{40}\b"),
}
PII_IDENTIFIER_PATTERN = re.compile(
    r"\b(?:email|email_address|phone_number|telephone|cpf|cnpj|full_name|"
    r"first_name|last_name|wallet_address|private_key|access_token|secret|"
    r"conversation_text|message_text)\b",
    re.IGNORECASE,
)


def value_text(value: object) -> str:
    return "" if value is None else str(value).strip()


class PipelineValidator:
    def __init__(self, analytics_root: Path) -> None:
        self.analytics_root = analytics_root
        self.dbt_root = analytics_root / "dbt"
        self.errors: list[str] = []
        self.checks: list[str] = []

    def passed(self, message: str) -> None:
        self.checks.append(message)

    def failed(self, message: str) -> None:
        self.errors.append(message)

    def check_pii(self, values: list[str], location: str) -> None:
        joined = "\n".join(values)
        for kind, pattern in PII_VALUE_PATTERNS.items():
            if pattern.search(joined):
                self.failed(f"{location}: padrão de {kind} encontrado")
        if PII_IDENTIFIER_PATTERN.search(joined):
            self.failed(f"{location}: identificador de PII encontrado")

    @staticmethod
    def parse_timestamp(value: str) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else None

    def validate_seed(self) -> None:
        seed_path = self.dbt_root / "seeds" / "mvp_test_events.csv"
        if not seed_path.is_file():
            self.failed(f"seed ausente: {seed_path}")
            return

        try:
            with seed_path.open(newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                headers = set(reader.fieldnames or [])
                rows = list(reader)
        except (OSError, csv.Error) as error:
            self.failed(f"seed não pôde ser lido: {error}")
            return

        missing = sorted(REQUIRED_SEED_COLUMNS - headers)
        if missing:
            self.failed(f"seed sem colunas obrigatórias: {', '.join(missing)}")
        else:
            self.passed(f"seed tem {len(rows)} registros e contrato mínimo completo")
        if not rows:
            self.failed("seed vazio")
            return

        event_ids: set[str] = set()
        users: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
        market_modes: set[str] = set()

        for line_number, row in enumerate(rows, start=2):
            location = f"seed linha {line_number}"
            self.check_pii([value_text(value) for value in row.values()], location)

            event_id = value_text(row.get("event_id"))
            if not event_id:
                self.failed(f"{location}: event_id vazio")
            elif event_id in event_ids:
                self.failed(f"{location}: event_id duplicado: {event_id}")
            event_ids.add(event_id)

            if value_text(row.get("is_test_data")).lower() != "true":
                self.failed(f"{location}: is_test_data precisa ser true")
            if value_text(row.get("source_system")) != "synthetic_fixture":
                self.failed(f"{location}: source_system precisa ser synthetic_fixture")

            user_pseudo_id = value_text(row.get("user_pseudo_id"))
            if not re.fullmatch(r"user_pseudo_[a-z0-9_]+", user_pseudo_id):
                self.failed(f"{location}: user_pseudo_id não parece pseudonimizado")
            users[user_pseudo_id].append(row)

            for column in TIMESTAMP_COLUMNS:
                value = value_text(row.get(column))
                if not value:
                    self.failed(f"{location}: timestamp obrigatório ausente em {column}")
                elif self.parse_timestamp(value) is None:
                    self.failed(f"{location}: timestamp inválido ou sem timezone em {column}")

            event_type = value_text(row.get("event_type"))
            if event_type == "yield_observation":
                for column in MARKET_TIMESTAMP_COLUMNS:
                    value = value_text(row.get(column))
                    if not value:
                        self.failed(f"{location}: {column} obrigatório para yield_observation")
                    elif self.parse_timestamp(value) is None:
                        self.failed(f"{location}: timestamp inválido ou sem timezone em {column}")

                if not value_text(row.get("market_source")):
                    self.failed(f"{location}: market_source ausente")
                market_mode = value_text(row.get("market_mode"))
                if not market_mode:
                    self.failed(f"{location}: market_mode ausente")
                else:
                    market_modes.add(market_mode)
                if value_text(row.get("read_only")).lower() != "true":
                    self.failed(f"{location}: read_only precisa ser true para observação de mercado")

                observed = self.parse_timestamp(value_text(row.get("observed_at")))
                retrieved = self.parse_timestamp(value_text(row.get("retrieved_at")))
                if observed and retrieved and retrieved < observed:
                    self.failed(f"{location}: retrieved_at anterior a observed_at")
            elif any(value_text(row.get(column)) for column in ("market_source", *MARKET_TIMESTAMP_COLUMNS)):
                self.failed(f"{location}: metadados de mercado só podem existir em yield_observation")

        if {"test", "fallback"}.issubset(market_modes):
            self.passed("seed cobre os modos de mercado test e fallback")
        else:
            self.failed("seed precisa cobrir os modos de mercado test e fallback")

        scd2_ok = True
        for user_id, user_rows in users.items():
            if not user_id:
                scd2_ok = False
                continue
            if any(not value_text(row.get("user_version")) for row in user_rows):
                self.failed(f"usuário {user_id}: user_version ausente")
                scd2_ok = False
            if not any(not value_text(row.get("user_valid_to")) for row in user_rows):
                self.failed(f"usuário {user_id}: SCD2 sem versão corrente")
                scd2_ok = False
        if scd2_ok:
            self.passed("seed preserva pseudonimização e versão corrente SCD2")

    def validate_models(self) -> None:
        models_root = self.dbt_root / "models"
        model_paths = sorted(models_root.rglob("*.sql")) if models_root.is_dir() else []
        model_names = {path.stem for path in model_paths}
        missing = sorted(REQUIRED_MODELS - model_names)
        if missing:
            self.failed(f"modelos obrigatórios ausentes: {', '.join(missing)}")
        else:
            self.passed(f"{len(REQUIRED_MODELS)} modelos obrigatórios encontrados")

        contents: dict[str, str] = {}
        for path in model_paths:
            try:
                content = path.read_text(encoding="utf-8")
            except OSError as error:
                self.failed(f"modelo {path.name} não pôde ser lido: {error}")
                continue
            contents[path.stem] = content
            self.check_pii([content], f"modelo {path.relative_to(self.analytics_root)}")

        required_fragments = {
            "stg_test_events": ("is_test_data", "where is_test_data = true", "source_system"),
            "fato_yield_observacao": ("is_test_data", "observed_at", "retrieved_at", "market_source"),
            "fato_recomendacao": ("is_test_data", "source_system"),
            "fato_interacao_conversacional": ("is_test_data", "source_system"),
            "aura_star_schema": ("is_test_data", "event_at"),
            "mvp_metrics": ("is_test_data", "where f.is_test_data = true"),
        }
        evidence_ok = True
        for model, fragments in required_fragments.items():
            content = contents.get(model, "").lower()
            for fragment in fragments:
                if fragment.lower() not in content:
                    self.failed(f"modelo {model}: evidência ausente de {fragment}")
                    evidence_ok = False
        if evidence_ok:
            self.passed("modelos preservam is_test_data, fonte e timestamps exigidos")

        user_model = contents.get("dim_usuario", "").lower()
        missing_scd2 = [
            fragment for fragment in ("md5(", "valid_from", "valid_to", "is_current")
            if fragment not in user_model
        ]
        if missing_scd2:
            self.failed(f"modelo dim_usuario: marcadores SCD2 ausentes: {', '.join(missing_scd2)}")
        else:
            self.passed("dim_usuario contém os marcadores SCD2 esperados")

    def validate_schema(self) -> None:
        schema_path = self.dbt_root / "models" / "schema.yml"
        if not schema_path.is_file():
            self.failed(f"schema.yml ausente: {schema_path}")
            return
        try:
            schema = schema_path.read_text(encoding="utf-8")
            metrics_schema = (schema_path.parent / "marts" / "mvp_metrics.yml").read_text(encoding="utf-8")
        except OSError as error:
            self.failed(f"schema.yml não pôde ser lido: {error}")
            return
        documented_schema = f"{schema}\n{metrics_schema}"
        missing_models = sorted(model for model in REQUIRED_MODELS if f"name: {model}" not in documented_schema)
        if missing_models:
            self.failed(f"schema.yml sem modelos obrigatórios: {', '.join(missing_models)}")
        else:
            self.passed("schema.yml documenta os modelos obrigatórios")
        for column in ("is_test_data", "source_system"):
            if column not in documented_schema:
                self.failed(f"schema.yml sem contrato para {column}")

    def run(self) -> int:
        self.validate_seed()
        self.validate_models()
        self.validate_schema()
        for check in self.checks:
            print(f"PASS  {check}")
        for error in self.errors:
            print(f"FAIL  {error}")
        print(f"\nResultado: {len(self.checks)} validações aprovadas; {len(self.errors)} falhas.")
        if self.errors:
            print("Ação: corrija o contrato e execute novamente; este validador não acessa dbt, banco ou rede.")
            return 1
        print("Limite: a execução real de dbt/PostgreSQL permanece fora deste validador estático.")
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
