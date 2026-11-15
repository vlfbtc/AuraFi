"""Conexão com o PostgreSQL: espera o banco ao iniciar e reabre a conexão que caiu.

Em 15/11/2026, um deploy falhou porque o banco reiniciava (troca de plano) e
recusou a conexão inicial; a versão anterior, com a única conexão aberta, não
reconectaria sozinha. Estes testes usam uma conexão simulada, sem psycopg.
"""

from __future__ import annotations

import unittest

from database.postgres.repository import (
    DEFAULT_CONNECT_RETRY_SECONDS,
    PostgresRepository,
    _connect_retry_seconds,
)


class FakeOperationalError(Exception):
    """Faz o papel do psycopg.OperationalError (conexão recusada ou caída)."""


class FakeConnection:
    def __init__(self) -> None:
        self.closed = False
        self.broken = False
        self.commits = 0
        self.rollbacks = 0

    def close(self) -> None:
        self.closed = True

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        if self.closed:
            raise FakeOperationalError("a conexão caiu")
        self.rollbacks += 1

    def drop(self) -> None:
        """O servidor reiniciou: o psycopg marca a conexão como quebrada e fechada."""
        self.broken = True
        self.closed = True


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class Connector:
    """Recusa as primeiras ``failures`` tentativas e depois abre conexões novas."""

    def __init__(self, failures: int = 0, error: type[BaseException] = FakeOperationalError) -> None:
        self.failures = failures
        self.error = error
        self.calls: list[dict] = []
        self.connections: list[FakeConnection] = []

    def __call__(self, dsn: str, **kwargs) -> FakeConnection:
        self.calls.append({"dsn": dsn, **kwargs})
        if self.failures > 0:
            self.failures -= 1
            raise self.error("connection refused")
        connection = FakeConnection()
        self.connections.append(connection)
        return connection


def repository(connector: Connector, clock: Clock, retry_seconds: float = 90.0) -> PostgresRepository:
    return PostgresRepository(
        "postgresql://aurafi@db/aurafi",
        connect=connector,
        retryable_errors=(FakeOperationalError,),
        connect_retry_seconds=retry_seconds,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )


class InitialConnectionTests(unittest.TestCase):
    def test_espera_o_banco_que_reinicia_em_vez_de_derrubar_o_deploy(self) -> None:
        connector, clock = Connector(failures=3), Clock()
        repo = repository(connector, clock)
        self.assertEqual(len(connector.calls), 4)
        self.assertEqual(clock.sleeps, [1.0, 2.0, 4.0])
        self.assertFalse(repo.is_closed)
        self.assertEqual(connector.calls[0]["autocommit"], False)
        self.assertEqual(connector.calls[0]["connect_timeout"], 10.0)

    def test_desiste_no_prazo_e_propaga_o_erro(self) -> None:
        connector, clock = Connector(failures=10_000), Clock()
        with self.assertRaises(FakeOperationalError):
            repository(connector, clock, retry_seconds=30.0)
        self.assertAlmostEqual(sum(clock.sleeps), 30.0)
        self.assertLessEqual(max(clock.sleeps), 8.0)

    def test_erro_que_nao_e_de_conexao_nao_e_repetido(self) -> None:
        connector, clock = Connector(failures=1, error=ValueError), Clock()
        with self.assertRaises(ValueError):
            repository(connector, clock)
        self.assertEqual(len(connector.calls), 1)
        self.assertEqual(clock.sleeps, [])

    def test_prazo_zero_mantem_o_comportamento_antigo(self) -> None:
        connector, clock = Connector(failures=1), Clock()
        with self.assertRaises(FakeOperationalError):
            repository(connector, clock, retry_seconds=0)
        self.assertEqual(len(connector.calls), 1)


class ReconnectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connector, self.clock = Connector(), Clock()
        self.repo = repository(self.connector, self.clock)

    def test_reabre_a_conexao_que_caiu(self) -> None:
        first = self.connector.connections[0]
        first.drop()
        connection = self.repo._require_connection()
        self.assertIsNot(connection, first)
        self.assertEqual(len(self.connector.calls), 2)
        self.assertFalse(self.repo.is_closed)

    def test_reabrir_espera_pouco_para_nao_segurar_as_requisicoes(self) -> None:
        self.connector.connections[0].drop()
        self.connector.failures = 10_000
        with self.assertRaises(FakeOperationalError):
            self.repo._require_connection()
        self.assertLessEqual(sum(self.clock.sleeps), 5.0)
        # Na tentativa seguinte, com o banco de volta, a conexão abre.
        self.connector.failures = 0
        self.assertIsInstance(self.repo._require_connection(), FakeConnection)

    def test_transacao_interrompida_propaga_o_erro_original(self) -> None:
        connection = self.connector.connections[0]
        with self.assertRaises(FakeOperationalError) as raised:
            with self.repo._transaction():
                connection.drop()
                raise FakeOperationalError("server closed the connection unexpectedly")
        self.assertIn("unexpectedly", str(raised.exception))
        self.assertEqual(connection.rollbacks, 0)
        # A operação seguinte já usa uma conexão nova.
        with self.repo._transaction() as fresh:
            self.assertIsNot(fresh, connection)
        self.assertEqual(self.connector.connections[-1].commits, 1)

    def test_transacao_com_erro_comum_ainda_faz_rollback(self) -> None:
        connection = self.connector.connections[0]
        with self.assertRaises(ValueError):
            with self.repo._transaction():
                raise ValueError("dado inválido")
        self.assertEqual(connection.rollbacks, 1)
        self.assertEqual(len(self.connector.calls), 1)

    def test_close_explicito_continua_definitivo(self) -> None:
        self.repo.close()
        self.assertTrue(self.repo.is_closed)
        with self.assertRaises(RuntimeError):
            self.repo._require_connection()
        self.assertEqual(len(self.connector.calls), 1)


class RetrySettingTests(unittest.TestCase):
    def test_variavel_de_ambiente(self) -> None:
        self.assertEqual(_connect_retry_seconds(None), DEFAULT_CONNECT_RETRY_SECONDS)
        self.assertEqual(_connect_retry_seconds(""), DEFAULT_CONNECT_RETRY_SECONDS)
        self.assertEqual(_connect_retry_seconds("45"), 45.0)
        self.assertEqual(_connect_retry_seconds("0"), 0.0)
        self.assertEqual(_connect_retry_seconds("abc"), DEFAULT_CONNECT_RETRY_SECONDS)
        self.assertEqual(_connect_retry_seconds("-5"), DEFAULT_CONNECT_RETRY_SECONDS)


if __name__ == "__main__":
    unittest.main()
