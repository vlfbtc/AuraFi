"""Convenção de origem e contagem agregada dos cadastros, sem dado pessoal."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest

from database.local.repository import SQLiteRepository
from services.acquisition import (
    CAMPAIGNS,
    DIRECT,
    MEDIUMS,
    OTHER,
    SOURCES,
    TEST_SOURCE,
    Attribution,
    InMemoryAcquisitionCounter,
    normalize_attribution,
    week_start,
)

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "database" / "migrations" / "004_acquisition_counts.sql"
LOCAL_SCHEMA = ROOT / "database" / "local" / "schema.sql"
COLUMNS = {"week_start", "utm_source", "utm_medium", "utm_campaign", "code_requests", "accounts_created"}
# Nada que identifique uma pessoa, um aparelho, uma sessão ou um instante exato.
IDENTIFYING = re.compile(
    r"(_id$|^id$|mail|^ip$|_ip$|^ip_|address|user|agent|cookie|session|challenge|token|device|"
    r"_at$|time|referr|clid|term|content)"
)
MONDAY = date(2026, 10, 19)


def check_values(sql: str, column: str) -> set[str]:
    match = re.search(rf"CHECK \({column} IN \((.*?)\)\)", sql, re.S)
    if match is None:
        raise AssertionError(f"lista fechada de {column} ausente")
    return set(re.findall(r"'([^']*)'", match.group(1)))


class NormalizeAttributionTests(unittest.TestCase):
    def test_valores_da_convencao_passam_normalizados(self) -> None:
        self.assertEqual(
            normalize_attribution(
                {"utm_source": " Perfil_A ", "utm_medium": "INFLUENCIADOR", "utm_campaign": "entenda_onda1"}
            ),
            Attribution("perfil_a", "influenciador", "entenda_onda1"),
        )
        for source in SOURCES:
            self.assertEqual(normalize_attribution({"utm_source": source}).source, source)
        for medium in MEDIUMS:
            self.assertEqual(normalize_attribution({"utm_medium": medium}).medium, medium)
        for campaign in CAMPAIGNS:
            self.assertEqual(normalize_attribution({"utm_campaign": campaign}).campaign, campaign)

    def test_sem_origem_conta_como_direto(self) -> None:
        self.assertEqual(normalize_attribution(None), Attribution(DIRECT, DIRECT, DIRECT))
        self.assertEqual(normalize_attribution({}), Attribution(DIRECT, DIRECT, DIRECT))
        self.assertEqual(
            normalize_attribution({"utm_source": "  ", "utm_medium": "", "utm_campaign": None}),
            Attribution(DIRECT, DIRECT, DIRECT),
        )
        self.assertEqual(normalize_attribution({"utm_source": "youtube"}), Attribution("youtube", DIRECT, DIRECT))

    def test_valor_fora_da_lista_vira_outro_e_nenhum_texto_livre_passa(self) -> None:
        cases = (
            "maria.silva@example.com",  # e-mail colado no link
            "x" * 5000,  # texto longo
            "perfil_a; DROP TABLE accounts",
            "Instagram",
            "perfil_e",
            "entenda_onda4",
            "pérfil_a",
        )
        for raw in cases:
            with self.subTest(raw=raw[:30]):
                result = normalize_attribution({"utm_source": raw, "utm_medium": raw, "utm_campaign": raw})
                self.assertEqual(result, Attribution(OTHER, OTHER, OTHER))
        self.assertEqual(normalize_attribution({"utm_source": 7, "utm_medium": ["x"]}).source, OTHER)
        self.assertEqual(normalize_attribution({"utm_medium": {"a": 1}}).medium, OTHER)
        self.assertEqual(normalize_attribution("utm_source=perfil_a"), Attribution(OTHER, OTHER, OTHER))

    def test_outros_parametros_sao_descartados(self) -> None:
        result = normalize_attribution(
            {"utm_source": "google", "gclid": "abc", "fbclid": "def", "utm_term": "stablecoin", "email": "a@b.c"}
        )
        self.assertEqual(result, Attribution("google", DIRECT, DIRECT))

    def test_fonte_teste_e_reservada_e_aceita(self) -> None:
        self.assertIn(TEST_SOURCE, SOURCES)
        self.assertEqual(normalize_attribution({"utm_source": "teste"}).source, "teste")


class WeekStartTests(unittest.TestCase):
    def test_semana_comeca_na_segunda_em_utc(self) -> None:
        for offset in range(7):
            moment = datetime(2026, 10, 19, 12, tzinfo=timezone.utc) + timedelta(days=offset)
            self.assertEqual(week_start(moment), MONDAY)
        self.assertEqual(week_start(datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc)), date(2026, 10, 26))
        # Domingo 23h30 em Brasília já é segunda-feira em UTC.
        brasilia = timezone(timedelta(hours=-3))
        self.assertEqual(week_start(datetime(2026, 10, 25, 23, 30, tzinfo=brasilia)), date(2026, 10, 26))
        self.assertEqual(week_start(datetime(2026, 10, 25, 20, 0)), MONDAY)


class InMemoryCounterTests(unittest.TestCase):
    def test_soma_por_semana_e_origem(self) -> None:
        counter = InMemoryAcquisitionCounter()
        counter.record_acquisition(MONDAY, "teste", "video_organico", "entenda_onda1", code_requests=1)
        counter.record_acquisition(MONDAY, "teste", "video_organico", "entenda_onda1", accounts_created=1)
        counter.record_acquisition(MONDAY, DIRECT, DIRECT, DIRECT, code_requests=1)
        self.assertEqual(
            counter.list_acquisition_counts(),
            [
                {"week_start": "2026-10-19", "utm_source": "direto", "utm_medium": "direto", "utm_campaign": "direto", "code_requests": 1, "accounts_created": 0},
                {"week_start": "2026-10-19", "utm_source": "teste", "utm_medium": "video_organico", "utm_campaign": "entenda_onda1", "code_requests": 1, "accounts_created": 1},
            ],
        )

    def test_recusa_valor_fora_da_convencao_e_contagem_vazia(self) -> None:
        counter = InMemoryAcquisitionCounter()
        with self.assertRaises(ValueError):
            counter.record_acquisition(MONDAY, "maria@example.com", DIRECT, DIRECT, code_requests=1)
        with self.assertRaises(ValueError):
            counter.record_acquisition(MONDAY, DIRECT, DIRECT, DIRECT)
        with self.assertRaises(ValueError):
            counter.record_acquisition(MONDAY, DIRECT, DIRECT, DIRECT, code_requests=-1, accounts_created=2)
        self.assertEqual(counter.list_acquisition_counts(), [])


class AcquisitionSchemaTests(unittest.TestCase):
    def test_listas_do_banco_sao_as_mesmas_do_codigo_nos_dois_adaptadores(self) -> None:
        expected = {
            "utm_source": SOURCES | {DIRECT, OTHER},
            "utm_medium": MEDIUMS | {DIRECT, OTHER},
            "utm_campaign": CAMPAIGNS | {DIRECT, OTHER},
        }
        for path in (MIGRATION, LOCAL_SCHEMA):
            sql = path.read_text(encoding="utf-8")
            for column, values in expected.items():
                with self.subTest(arquivo=path.name, coluna=column):
                    self.assertEqual(check_values(sql, column), set(values))

    def test_migration_e_aditiva_guardada_e_registrada(self) -> None:
        sql = MIGRATION.read_text(encoding="utf-8")
        statements = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
        self.assertNotRegex(statements.upper(), r"\b(DROP|TRUNCATE|DELETE|ALTER TABLE)\b")
        self.assertIn("WHERE version = '004_acquisition_counts'", sql)
        self.assertIn("RAISE EXCEPTION", sql)
        self.assertIn("INSERT INTO aurafi.schema_migrations", sql)
        self.assertIn("'004_acquisition_counts'", sql.split("INSERT INTO aurafi.schema_migrations", 1)[1])

    def test_tabela_nao_tem_coluna_identificadora(self) -> None:
        create = re.search(r"CREATE TABLE aurafi\.acquisition_weekly \((.*?)\n\);", MIGRATION.read_text(encoding="utf-8"), re.S)
        self.assertIsNotNone(create)
        # Colunas são as linhas com quatro espaços e nome em minúsculas.
        declared = {line.split()[0] for line in create.group(1).splitlines() if re.match(r"\s{4}[a-z_]+\s", line)}
        self.assertEqual(declared, COLUMNS)
        for column in COLUMNS:
            self.assertIsNone(IDENTIFYING.search(column), column)


class SQLiteAcquisitionTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "counts.sqlite3"
        self.repository = SQLiteRepository(self.path)
        self.repository.initialize()
        self.addCleanup(self.repository.close)

    def test_soma_na_mesma_linha_e_lista_por_semana(self) -> None:
        repo = self.repository
        repo.record_acquisition(MONDAY, "perfil_a", "influenciador", "entenda_onda1", code_requests=1)
        repo.record_acquisition(MONDAY, "perfil_a", "influenciador", "entenda_onda1", code_requests=1)
        repo.record_acquisition(MONDAY, "perfil_a", "influenciador", "entenda_onda1", accounts_created=1)
        repo.record_acquisition(MONDAY + timedelta(days=7), DIRECT, DIRECT, DIRECT, accounts_created=1)
        self.assertEqual(
            repo.list_acquisition_counts(),
            [
                {"week_start": "2026-10-19", "utm_source": "perfil_a", "utm_medium": "influenciador", "utm_campaign": "entenda_onda1", "code_requests": 2, "accounts_created": 1},
                {"week_start": "2026-10-26", "utm_source": "direto", "utm_medium": "direto", "utm_campaign": "direto", "code_requests": 0, "accounts_created": 1},
            ],
        )

    def test_banco_recusa_texto_livre_semana_errada_e_contagem_invalida(self) -> None:
        repo = self.repository
        with self.assertRaises(sqlite3.IntegrityError):
            repo.record_acquisition(MONDAY, "maria@example.com", DIRECT, DIRECT, code_requests=1)
        with self.assertRaises(sqlite3.IntegrityError):
            repo.record_acquisition(MONDAY, DIRECT, "texto livre", DIRECT, code_requests=1)
        with self.assertRaises(sqlite3.IntegrityError):
            repo.record_acquisition(MONDAY + timedelta(days=2), DIRECT, DIRECT, DIRECT, code_requests=1)
        with self.assertRaises(TypeError):
            repo.record_acquisition(datetime(2026, 10, 19, tzinfo=timezone.utc), DIRECT, DIRECT, DIRECT, code_requests=1)
        with self.assertRaises(ValueError):
            repo.record_acquisition(MONDAY, DIRECT, DIRECT, DIRECT)
        with self.assertRaises(ValueError):
            repo.record_acquisition(MONDAY, DIRECT, DIRECT, DIRECT, code_requests=-1, accounts_created=1)
        self.assertEqual(repo.list_acquisition_counts(), [])

    def test_estrutura_sem_coluna_identificadora(self) -> None:
        connection = sqlite3.connect(self.path)
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(acquisition_weekly)")}
            foreign_keys = connection.execute("PRAGMA foreign_key_list(acquisition_weekly)").fetchall()
        finally:
            connection.close()
        self.assertEqual(columns, COLUMNS)
        self.assertEqual(foreign_keys, [])

    def test_schema_local_pode_ser_reaplicado(self) -> None:
        self.repository.record_acquisition(MONDAY, DIRECT, DIRECT, DIRECT, code_requests=1)
        self.repository.initialize()
        self.assertEqual(self.repository.list_acquisition_counts()[0]["code_requests"], 1)


if __name__ == "__main__":
    unittest.main()
