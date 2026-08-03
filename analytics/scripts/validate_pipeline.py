"""Validate the AuraFi analytical contract without dbt or a database.

This is intentionally a static, dependency-free gate for the controlled dataset.
It does not replace ``dbt seed/run/test`` against PostgreSQL. It proves that the
checked-in seed and model contract are safe to hand off to that environment.
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
    "event_id",
    "event_type",
    "test_case_id",
    "is_test_data",
    "source_system",
    "occurred_at",
    "user_pseudo_id",
    "user_version",
    "user_valid_from",
    "user_valid_to",
    "market_source",
    "market_mode",
    "observed_at",
    "retrieved_at",
    "is_stale",
    "read_only",
}

REQUIRED_MODELS = {
    "stg_test_events",
    "dim_tempo",
    "dim_usuario",
    "dim_perfil_risco",
    "dim_protocolo",
    "dim_ativo",
    "dim_blockchain",
    "dim_canal",
    "fato_recomendacao",
    "fato_yield_observacao",
    "fato_interacao_conversacional",
    "aura_star_schema",
    "mvp_metrics",
}

FORBIDDEN_PII_PATTERNS = {
    "email": re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
    "phone": re.compile(r"(?<!\d)(?:\+?\d[\d ()-]{7,}\d)(?!\d)"),
    "wallet": re.compile(r"\b0x[a-fA-F0-9]{40}\b"),
}


class ContractValidation:
    def __init__(self, analytics_root: Path) -> None:
        self.analytics_root = analytics_root
        self.dbt_root = analytics_root / "dbt"
        self.errors: list[str] = []
        self.checks: list[str] = []

    def ok(self, message: str) -> None:
        self.checks.append(message)

    def fail(self, message: str) -> None:
        self.errors.append(message)

    def validate_seed(self) -> None:
        seed_path = self.dbt_root / "seeds" / "mvp_test_events.csv"
        if not seed_path.exists():
            self.fail(f"seed ausente: {seed_path}")
            return

        with seed_path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
            headers = set(rows[0].keys()) if rows else set()

        missing = sorted(REQUIRED_SEED_COLUMNS - headers)
        if missing:
            self.fail(f"seed sem colunas obrigatórias: {', '.join(missing)}")
        else:
            self.ok(f"seed tem {len(rows)} registros e contrato mínimo completo")

        if not rows:
            self.fail("seed vazio")
            return

        event_ids: set[str] = set()
        users: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
        modes: set[str] = set()
        for line_number, row in enumerate(rows, start=2):
            event_id = row.get("event_id", "").strip()
            if not event_id:
                self.fail(f"linha {line_number}: event_id vazio")
            elif event_id in event_ids:
                self.fail(f"linha {line_number}: event_id duplicado: {event_id}")
            event_ids.add(event_id)

            if row.get("is_test_data", "").strip().lower() != "true":
                self.fail(f"linha {line_number}: is_test_data precisa ser true")
            if row.get("source_system", "").strip() != "synthetic_fixture":
                self.fail(f"linha {line_number}: source_system precisa identificar dataset controlado")

            pseudo_id = row.get("user_pseudo_id", "").strip()
            if not re.fullmatch(r"user_pseudo_[a-z0-9_]+", pseudo_id):
                self.fail(f"linha {line_number}: user_pseudo_id não parece pseudonimizado: {pseudo_id!r}")
            users[pseudo_id].append(row)

            for column in ("occurred_at", "user_valid_from", "observed_at", "retrieved_at"):
                value = row.get(column, "").strip()
                if value:
                    try:
                        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    except ValueError:
                        self.fail(f"linha {line_number}: timestamp inválido em {column}: {value!r}")
                    else:
                        if parsed.tzinfo is None:
                            self.fail(f"linha {line_number}: timestamp sem timezone em {column}")

            observed = row.get("observed_at", "").strip()
            retrieved = row.get("retrieved_at", "").strip()
            if observed and retrieved:
                observed_at = datetime.fromisoformat(observed.replace("Z", "+00:00"))
                retrieved_at = datetime.fromisoformat(retrieved.replace("Z", "+00:00"))
                if retrieved_at < observed_at:
                    self.fail(f"linha {line_number}: retrieved_at anterior a observed_at")

            mode = row.get("market_mode", "").strip()
            if mode:
                modes.add(mode)
            for field, pattern in FORBIDDEN_PII_PATTERNS.items():
                if any(pattern.search(value or "") for value in row.values()):
                    self.fail(f"linha {line_number}: padrão de {field} encontrado no dataset")

        if modes >= {"test", "fallback"}:
            self.ok("seed cobre degradação controlada com modos test e fallback")
        else:
            self.fail("seed precisa cobrir os modos test e fallback")

        for pseudo_id, user_rows in users.items():
            versions = {row.get("user_version", "").strip() for row in user_rows}
            if not versions or "" in versions:
                self.fail(f"usuário {pseudo_id}: user_version ausente")
            for row in user_rows:
                if not row.get("user_valid_from", "").strip():
                    self.fail(f"usuário {pseudo_id}: user_valid_from ausente")
            valid_to_values = {row.get("user_valid_to", "").strip() for row in user_rows}
            if "" not in valid_to_values:
                self.fail(f"usuário {pseudo_id}: SCD2 precisa de uma versão corrente sem valid_to")
        if not self.errors:
            self.ok("pseudonimização e marcadores de versão SCD2 verificados no seed")

    def validate_models(self) -> None:
        model_paths = sorted(self.dbt_root.glob("models/**/*.sql"))
        model_names = {path.stem for path in model_paths}
        missing = sorted(REQUIRED_MODELS - model_names)
        if missing:
            self.fail(f"modelos dbt ausentes: {', '.join(missing)}")
        else:
            self.ok(f"{len(REQUIRED_MODELS)} modelos dbt esperados encontrados")

        all_sql = "\n".join(path.read_text(encoding="utf-8") for path in model_paths)
        required_fragments = {
            "is_test_data": "is_test_data",
            "source metadata": "market_source",
            "observed timestamp": "observed_at",
            "retrieved timestamp": "retrieved_at",
            "SCD2 current marker": "is_current",
            "pseudonymous key": "user_pseudo_id",
        }
        for label, fragment in required_fragments.items():
            if fragment not in all_sql:
                self.fail(f"modelos sem evidência estática de {label}: {fragment}")
            else:
                self.ok(f"modelos preservam {label}")

        for path in model_paths:
            content = path.read_text(encoding="utf-8")
            for field, pattern in FORBIDDEN_PII_PATTERNS.items():
                if pattern.search(content):
                    self.fail(f"modelo {path.name}: padrão de {field} encontrado")

        user_model = self.dbt_root / "models" / "dimensions" / "dim_usuario.sql"
        user_sql = user_model.read_text(encoding="utf-8") if user_model.exists() else ""
        for fragment in ("md5(", "valid_from", "valid_to", "is_current"):
            if fragment not in user_sql:
                self.fail(f"dim_usuario sem marcador SCD2 esperado: {fragment}")

    def validate_schema(self) -> None:
        schema_path = self.dbt_root / "models" / "schema.yml"
        if not schema_path.exists():
            self.fail(f"schema.yml ausente: {schema_path}")
            return
        schema = schema_path.read_text(encoding="utf-8")
        missing = [model for model in REQUIRED_MODELS if f"name: {model}" not in schema]
        if missing:
            self.fail(f"schema.yml sem modelos documentados: {', '.join(sorted(missing))}")
        else:
            self.ok("schema.yml documenta todos os modelos do contrato")
        for required in ("is_test_data", "observed_at", "retrieved_at", "user_pseudo_id", "is_current"):
            if required not in schema:
                self.fail(f"schema.yml sem coluna/contrato obrigatório: {required}")

    def validate(self) -> int:
        self.validate_seed()
        self.validate_models()
        self.validate_schema()
        for check in self.checks:
            print(f"PASS  {check}")
        for error in self.errors:
            print(f"FAIL  {error}")
        print(f"\nResultado: {len(self.checks)} validações aprovadas; {len(self.errors)} falhas.")
        if self.errors:
            print("Ação: corrija os contratos acima e execute novamente; este comando não acessa dbt nem PostgreSQL.")
            return 1
        print("Limite: dbt seed/run/test contra PostgreSQL ainda precisa ser executado em ambiente com profile fornecido.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--analytics-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="raiz de analytics (padrão: diretório pai de scripts)",
    )
    args = parser.parse_args()
    return ContractValidation(args.analytics_root.resolve()).validate()


if __name__ == "__main__":
    sys.exit(main())
