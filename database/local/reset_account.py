"""Remove uma conta e todos os seus dados do SQLite operacional.

Uso (local ou no shell do serviço publicado):

    AURAFI_DB_PATH=/data/aurafi.sqlite3 \
        python -m database.local.reset_account --email pessoa@exemplo.com

Passe ``--dry-run`` para apenas listar o que seria apagado. Dados de mercado
compartilhados (oportunidades, observações) não são tocados.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys


_APPEND_ONLY_DELETE_TRIGGER = (
    "CREATE TRIGGER IF NOT EXISTS risk_profiles_append_only_delete\n"
    "BEFORE DELETE ON risk_profiles\n"
    "BEGIN\n"
    "    SELECT RAISE(ABORT, 'risk profiles are append-only');\n"
    "END"
)


def _delete(cursor: sqlite3.Cursor, account_id: str, email: str, dry_run: bool) -> dict[str, int]:
    steps: list[tuple[str, str, tuple]] = [
        ("messages", "DELETE FROM messages WHERE account_id = ?", (account_id,)),
        ("conversation_runtime_state", "DELETE FROM conversation_runtime_state WHERE account_id = ?", (account_id,)),
        ("conversations", "DELETE FROM conversations WHERE account_id = ?", (account_id,)),
        (
            "simulation_scenarios",
            "DELETE FROM simulation_scenarios WHERE simulation_id IN "
            "(SELECT simulation_id FROM simulations WHERE account_id = ?)",
            (account_id,),
        ),
        ("simulations", "DELETE FROM simulations WHERE account_id = ?", (account_id,)),
        ("alerts", "DELETE FROM alerts WHERE account_id = ?", (account_id,)),
        (
            "risk_profile_answers",
            "DELETE FROM risk_profile_answers WHERE risk_profile_id IN "
            "(SELECT risk_profile_id FROM risk_profiles WHERE account_id = ?)",
            (account_id,),
        ),
        ("risk_profiles", "DELETE FROM risk_profiles WHERE account_id = ?", (account_id,)),
        ("consents", "DELETE FROM consents WHERE account_id = ?", (account_id,)),
        ("channel_identities", "DELETE FROM channel_identities WHERE account_id = ?", (account_id,)),
        ("sessions", "DELETE FROM sessions WHERE account_id = ?", (account_id,)),
        ("otp_challenges", "DELETE FROM otp_challenges WHERE email = ?", (email,)),
        ("accounts", "DELETE FROM accounts WHERE account_id = ?", (account_id,)),
    ]
    counts: dict[str, int] = {}
    if not dry_run:
        cursor.execute("DROP TRIGGER IF EXISTS risk_profiles_append_only_delete")
    try:
        for label, statement, params in steps:
            if dry_run:
                count_sql = statement.replace("DELETE FROM", "SELECT COUNT(*) FROM", 1)
                counts[label] = int(cursor.execute(count_sql, params).fetchone()[0])
            else:
                counts[label] = cursor.execute(statement, params).rowcount
    finally:
        if not dry_run:
            cursor.execute(_APPEND_ONLY_DELETE_TRIGGER)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apaga uma conta AuraFi e todos os seus dados.")
    parser.add_argument("--email", required=True, help="E-mail da conta a remover.")
    parser.add_argument("--db", default=os.environ.get("AURAFI_DB_PATH"), help="Caminho do SQLite (ou AURAFI_DB_PATH).")
    parser.add_argument("--dry-run", action="store_true", help="Apenas mostra o que seria apagado.")
    args = parser.parse_args(argv)

    if not args.db:
        parser.error("informe --db ou defina AURAFI_DB_PATH")
    email = args.email.strip().lower()

    connection = sqlite3.connect(args.db)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        cursor = connection.cursor()
        row = cursor.execute(
            "SELECT account_id FROM accounts WHERE email = ? ORDER BY created_at, account_id",
            (email,),
        ).fetchone()
        if row is None:
            print(f"Nenhuma conta encontrada para {email}.")
            return 1
        account_id = row[0]
        counts = _delete(cursor, account_id, email, args.dry_run)
        if args.dry_run:
            connection.rollback()
            print(f"[dry-run] conta {account_id} ({email}) seria removida:")
        else:
            connection.commit()
            print(f"Conta {account_id} ({email}) removida:")
        for label, count in counts.items():
            if count:
                print(f"  {label}: {count}")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
