"""PostgreSQL adapter mirroring SQLiteRepository's contract method-for-method,
against the schema in database/migrations/*.sql. psycopg is imported lazily
so the SQLite/in-memory path stays dependency-free.
"""

from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from database import account_data

_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_SECRET_KEYS = {
    "otp",
    "one_time_password",
    "token",
    "access_token",
    "refresh_token",
    "private_key",
    "secret",
}
_RISK_DIMENSIONS = {
    "smart_contract",
    "liquidity",
    "volatility",
    "underlying_asset",
    "counterparty",
    "data_quality",
}
_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise TypeError("timestamp deve ser datetime ou ISO-8601")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_optional_datetime(value: Any) -> datetime | None:
    return None if value is None else _to_datetime(value)


def _format_timestamp(value: Any) -> str:
    return _to_datetime(value).strftime(_TIMESTAMP_FORMAT)


def _format_optional_timestamp(value: Any) -> str | None:
    return None if value is None else _format_timestamp(value)


def _stringify_timestamps(row: dict[str, Any] | None, fields: Iterable[str]) -> dict[str, Any] | None:
    if row is None:
        return None
    for field in fields:
        if row.get(field) is not None:
            row[field] = _format_timestamp(row[field])
    return row


class PostgresRepository:
    """One connection guarded by a lock, matching SQLiteRepository (single-replica MVP, no pooling)."""

    def __init__(
        self,
        dsn: str,
        *,
        now: Any = None,
        connect_timeout: float = 10.0,
    ) -> None:
        import psycopg
        from psycopg.rows import dict_row

        self._psycopg = psycopg
        self._dict_row = dict_row
        self.dsn = dsn
        self._lock = threading.RLock()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._connection = psycopg.connect(dsn, autocommit=False, connect_timeout=connect_timeout)

    @property
    def is_closed(self) -> bool:
        return self._connection is None or self._connection.closed

    def initialize(self, migrations_dir: str | Path | None = None) -> None:
        """Applies migrations not yet in aurafi.schema_migrations; safe to call on every startup."""

        directory = Path(migrations_dir) if migrations_dir else _MIGRATIONS_DIR
        migration_files = sorted(directory.glob("*.sql"))
        with self._lock:
            connection = self._require_connection()
            cursor = connection.cursor()
            cursor.execute("SELECT to_regclass('aurafi.schema_migrations')")
            (table_oid,) = cursor.fetchone()
            applied: set[str] = set()
            if table_oid is not None:
                cursor.execute("SELECT version FROM aurafi.schema_migrations")
                applied = {row[0] for row in cursor.fetchall()}
            for path in migration_files:
                version = path.stem
                if version in applied:
                    continue
                cursor.execute(path.read_text(encoding="utf-8"))
            connection.commit()

    def close(self) -> None:
        with self._lock:
            if self._connection is not None and not self._connection.closed:
                self._connection.close()

    def __enter__(self) -> "PostgresRepository":
        self._require_connection()
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.close()

    def save_account(
        self,
        account: Mapping[str, Any] | Any,
        email: str | None = None,
        *,
        email_verified: bool = False,
        created_at: Any = None,
    ) -> dict[str, Any]:
        values = self._mapping(account)
        account_id = str(values.get("account_id", account) if values else account)
        if values:
            email = values.get("email", email)
            email_verified = bool(values.get("email_verified", email_verified))
            created_at = values.get("created_at", created_at)
        if email is None:
            raise ValueError("email e obrigatorio")
        timestamp = _to_datetime(created_at) if created_at is not None else self._now()
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO aurafi.accounts (account_id, email, email_verified, created_at) VALUES (%s, %s, %s, %s)",
                (self._text(account_id, "account_id"), self._normalize_email(email), bool(email_verified), timestamp),
            )
        return self.get_account(account_id)  # type: ignore[return-value]

    create_account = save_account

    def get_account(self, account_id: str) -> dict[str, Any] | None:
        row = self._fetchone("SELECT * FROM aurafi.accounts WHERE account_id = %s", (account_id,))
        return _stringify_timestamps(row, ("created_at",))

    def find_account_by_email(self, email: str) -> dict[str, Any] | None:
        row = self._fetchone(
            "SELECT * FROM aurafi.accounts WHERE email = %s ORDER BY created_at, account_id LIMIT 1",
            (self._normalize_email(email),),
        )
        return _stringify_timestamps(row, ("created_at",))

    find_by_email = find_account_by_email

    def mark_email_verified(self, account_id: str, verified_at: Any = None) -> dict[str, Any] | None:
        del verified_at
        with self._transaction() as connection:
            connection.execute(
                "UPDATE aurafi.accounts SET email_verified = true WHERE account_id = %s", (account_id,)
            )
        return self.get_account(account_id)

    def save_otp_challenge(
        self,
        challenge: Mapping[str, Any] | Any,
        *,
        otp: str | None = None,
        otp_digest: str | None = None,
    ) -> dict[str, Any]:
        import hashlib

        values = self._mapping(challenge)
        if not values:
            raise TypeError("challenge deve ser um mapping ou objeto com atributos")
        digest = otp_digest or values.get("otp_digest") or values.get("otp_hash")
        if digest is None:
            otp = otp or values.get("otp")
            if otp is None:
                raise ValueError("otp_digest ou otp e obrigatorio")
            digest = hashlib.sha256(str(otp).encode("utf-8")).hexdigest()
        created_at = _to_datetime(values.get("created_at")) if values.get("created_at") else self._now()
        expires_at = _to_datetime(values["expires_at"])
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO aurafi.otp_challenges
                (challenge_id, email, channel, delivery, otp_digest, attempts, status, expires_at, created_at, verified_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    self._text(values.get("challenge_id"), "challenge_id"),
                    self._normalize_email(values.get("email")),
                    values.get("channel"),
                    values.get("delivery"),
                    self._text(digest, "otp_digest"),
                    int(values.get("attempts", 0)),
                    values.get("status", "pending"),
                    expires_at,
                    created_at,
                    _to_optional_datetime(values.get("verified_at")),
                ),
            )
        return self.get_otp_challenge(values["challenge_id"])  # type: ignore[return-value]

    create_otp_challenge = save_otp_challenge

    def get_otp_challenge(self, challenge_id: str) -> dict[str, Any] | None:
        row = self._fetchone(
            "SELECT * FROM aurafi.otp_challenges WHERE challenge_id = %s", (challenge_id,)
        )
        return _stringify_timestamps(row, ("expires_at", "created_at", "verified_at"))

    def update_otp_challenge(
        self,
        challenge_id: str,
        *,
        status: str,
        verified_at: Any = None,
        attempts: int = 0,
    ) -> dict[str, Any] | None:
        with self._transaction() as connection:
            connection.execute(
                "UPDATE aurafi.otp_challenges SET status = %s, verified_at = %s, attempts = %s WHERE challenge_id = %s",
                (status, _to_optional_datetime(verified_at), int(attempts), challenge_id),
            )
        return self.get_otp_challenge(challenge_id)

    def save_session(
        self,
        session: Mapping[str, Any] | Any,
        *,
        account_id: str | None = None,
        expires_at: Any = None,
        started_at: Any = None,
        status: str = "active",
        ended_at: Any = None,
        access_token_digest: str | None = None,
        refresh_token_digest: str | None = None,
    ) -> dict[str, Any]:
        import hashlib

        values = self._mapping(session)
        session_id = values.get("session_id", session) if values else session
        account_id = values.get("account_id", account_id)
        expires_at = values.get("expires_at", expires_at)
        started_at = values.get("started_at", started_at)
        status = values.get("status", status)
        ended_at = values.get("ended_at", ended_at)
        access_token_digest = values.get("access_token_digest", access_token_digest)
        refresh_token_digest = values.get("refresh_token_digest", refresh_token_digest)
        if access_token_digest is None and values.get("access_token") is not None:
            access_token_digest = hashlib.sha256(str(values["access_token"]).encode("utf-8")).hexdigest()
        if refresh_token_digest is None and values.get("refresh_token") is not None:
            refresh_token_digest = hashlib.sha256(str(values["refresh_token"]).encode("utf-8")).hexdigest()
        if account_id is None or expires_at is None:
            raise ValueError("account_id e expires_at sao obrigatorios")
        started = _to_datetime(started_at) if started_at is not None else self._now()
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO aurafi.sessions
                (session_id, account_id, started_at, expires_at, status, ended_at)
                VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    self._text(session_id, "session_id"),
                    self._text(account_id, "account_id"),
                    started,
                    _to_datetime(expires_at),
                    status,
                    _to_optional_datetime(ended_at),
                ),
            )
            self._save_session_digests(connection, session_id, access_token_digest, refresh_token_digest)
        return self.get_session(session_id)  # type: ignore[return-value]

    create_session = save_session

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self._fetchone("SELECT * FROM aurafi.sessions WHERE session_id = %s", (session_id,))
        return _stringify_timestamps(row, ("started_at", "expires_at", "ended_at"))

    def get_by_access_token_digest(self, digest: str) -> dict[str, Any] | None:
        row = self._fetchone(
            "SELECT * FROM aurafi.sessions WHERE access_token_digest = %s", (digest,)
        )
        return _stringify_timestamps(row, ("started_at", "expires_at", "ended_at"))

    def get_by_refresh_token_digest(self, digest: str) -> dict[str, Any] | None:
        row = self._fetchone(
            "SELECT * FROM aurafi.sessions WHERE refresh_token_digest = %s", (digest,)
        )
        return _stringify_timestamps(row, ("started_at", "expires_at", "ended_at"))

    def update_session(self, session: Mapping[str, Any] | Any) -> dict[str, Any]:
        import hashlib

        values = self._mapping(session)
        if not values or not values.get("session_id"):
            raise ValueError("session_id e obrigatorio")
        if "access_token_digest" not in values and values.get("access_token") is not None:
            values["access_token_digest"] = hashlib.sha256(str(values["access_token"]).encode("utf-8")).hexdigest()
        if "refresh_token_digest" not in values and values.get("refresh_token") is not None:
            values["refresh_token_digest"] = hashlib.sha256(str(values["refresh_token"]).encode("utf-8")).hexdigest()
        assignments: dict[str, Any] = {}
        if "expires_at" in values:
            assignments["expires_at"] = _to_datetime(values["expires_at"])
        if "status" in values:
            assignments["status"] = values["status"]
        if "ended_at" in values:
            assignments["ended_at"] = _to_optional_datetime(values["ended_at"])
        if "access_token_digest" in values:
            assignments["access_token_digest"] = values["access_token_digest"]
        if "refresh_token_digest" in values:
            assignments["refresh_token_digest"] = values["refresh_token_digest"]
        if not assignments:
            return self.get_session(values["session_id"])  # type: ignore[return-value]
        with self._transaction() as connection:
            digests = {
                key: assignments.pop(key)
                for key in ("access_token_digest", "refresh_token_digest")
                if key in assignments
            }
            if assignments:
                clause = ", ".join(f"{key} = %s" for key in assignments)
                connection.execute(
                    f"UPDATE aurafi.sessions SET {clause} WHERE session_id = %s",
                    (*assignments.values(), values["session_id"]),
                )
            if digests:
                self._save_session_digests(
                    connection,
                    values["session_id"],
                    digests.get("access_token_digest"),
                    digests.get("refresh_token_digest"),
                )
        return self.get_session(values["session_id"])  # type: ignore[return-value]

    def _save_session_digests(
        self, connection: Any, session_id: str, access_token_digest: Any, refresh_token_digest: Any
    ) -> None:
        if access_token_digest is None and refresh_token_digest is None:
            return
        assignments = {}
        if access_token_digest is not None:
            assignments["access_token_digest"] = access_token_digest
        if refresh_token_digest is not None:
            assignments["refresh_token_digest"] = refresh_token_digest
        clause = ", ".join(f"{key} = %s" for key in assignments)
        connection.execute(
            f"UPDATE aurafi.sessions SET {clause} WHERE session_id = %s",
            (*assignments.values(), session_id),
        )

    def save_channel_identity(self, association: Mapping[str, Any] | Any) -> dict[str, Any]:
        values = self._mapping(association)
        channel = self._mapping(values.get("channel", {}))
        channel_name = values.get("channel_name", channel.get("name"))
        adapter = values.get("adapter", channel.get("adapter"))
        created_at = _to_datetime(values["created_at"]) if values.get("created_at") else self._now()
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO aurafi.channel_identities
                (channel_identity_id, account_id, channel_name, adapter, created_at)
                VALUES (%s, %s, %s, %s, %s)""",
                (
                    self._text(values.get("channel_identity_id"), "channel_identity_id"),
                    self._text(values.get("account_id"), "account_id"),
                    channel_name,
                    self._text(adapter, "adapter"),
                    created_at,
                ),
            )
        return self.get_channel_identity(values["channel_identity_id"])  # type: ignore[return-value]

    create_channel_identity = save_channel_identity

    def get_channel_identity(self, channel_identity_id: str) -> dict[str, Any] | None:
        return self._decode_channel_identity(
            self._fetchone(
                "SELECT * FROM aurafi.channel_identities WHERE channel_identity_id = %s",
                (channel_identity_id,),
            )
        )

    def find_channel_identity(self, account_id: str, channel_name: str, adapter: str) -> dict[str, Any] | None:
        return self._decode_channel_identity(
            self._fetchone(
                """SELECT * FROM aurafi.channel_identities
                WHERE account_id = %s AND channel_name = %s AND adapter = %s""",
                (account_id, channel_name, adapter),
            )
        )

    def first_channel_identity(self, account_id: str) -> dict[str, Any] | None:
        return self._decode_channel_identity(
            self._fetchone(
                """SELECT * FROM aurafi.channel_identities
                WHERE account_id = %s ORDER BY created_at, channel_identity_id LIMIT 1""",
                (account_id,),
            )
        )

    @staticmethod
    def _decode_channel_identity(row: dict[str, Any] | None) -> dict[str, Any] | None:
        row = _stringify_timestamps(row, ("created_at",))
        if row is None:
            return None
        simulated = row["channel_name"] == "simulated"
        row["simulated"] = simulated
        row["channel"] = {"name": row["channel_name"], "adapter": row["adapter"], "simulated": simulated}
        return row

    def save_consent(self, consent: Mapping[str, Any] | Any, **overrides: Any) -> dict[str, Any]:
        values = self._mapping(consent)
        values.update(overrides)
        required = ("consent_id", "account_id", "purpose", "status", "policy_version")
        for key in required:
            if values.get(key) is None:
                raise ValueError(f"{key} e obrigatorio")
        captured_at = _to_datetime(values["captured_at"]) if values.get("captured_at") else self._now()
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO aurafi.consents
                (consent_id, account_id, purpose, status, policy_version, captured_at, memory, analytics)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    values["consent_id"],
                    values["account_id"],
                    values["purpose"],
                    values["status"],
                    values["policy_version"],
                    captured_at,
                    self._bool_or_none(values.get("memory")),
                    self._bool_or_none(values.get("analytics")),
                ),
            )
        return self.get_consent(values["consent_id"])  # type: ignore[return-value]

    create_consent = save_consent

    def get_consent(self, consent_id: str) -> dict[str, Any] | None:
        row = self._fetchone("SELECT * FROM aurafi.consents WHERE consent_id = %s", (consent_id,))
        return _stringify_timestamps(row, ("captured_at",))

    def save_risk_profile(
        self,
        risk_profile: Mapping[str, Any] | Any,
        *,
        answers: Iterable[Mapping[str, Any] | Any] | None = None,
    ) -> dict[str, Any]:
        values = self._mapping(risk_profile)
        if not values:
            raise TypeError("risk_profile deve ser um mapping ou objeto com atributos")
        answer_values = list(answers if answers is not None else values.get("answers", ()))
        status = values.get("status", "declared")
        if status == "declared" and len(answer_values) != 5:
            raise ValueError("perfil declarado exige exatamente cinco respostas")
        if status == "missing" and answer_values:
            raise ValueError("perfil ausente nao aceita respostas")
        declared_at = _to_datetime(values["declared_at"]) if values.get("declared_at") else self._now()
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO aurafi.risk_profiles
                (risk_profile_id, account_id, declared_profile, status, version, declared_at, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    values.get("risk_profile_id"),
                    values.get("account_id"),
                    values.get("declared_profile"),
                    status,
                    values.get("version"),
                    declared_at,
                    values.get("source", "questionnaire" if status == "declared" else None),
                ),
            )
            for answer in answer_values:
                answer_map = self._mapping(answer)
                connection.execute(
                    "INSERT INTO aurafi.risk_profile_answers (risk_profile_id, question_id, answer) VALUES (%s, %s, %s)",
                    (values["risk_profile_id"], answer_map.get("question_id"), answer_map.get("answer")),
                )
        return self.get_risk_profile(values["risk_profile_id"])  # type: ignore[return-value]

    create_risk_profile = save_risk_profile

    def get_risk_profile(self, risk_profile_id: str) -> dict[str, Any] | None:
        row = self._fetchone(
            "SELECT * FROM aurafi.risk_profiles WHERE risk_profile_id = %s", (risk_profile_id,)
        )
        result = _stringify_timestamps(row, ("declared_at",))
        if result is not None:
            result["answers"] = self._fetchall(
                "SELECT question_id, answer FROM aurafi.risk_profile_answers WHERE risk_profile_id = %s ORDER BY question_id",
                (risk_profile_id,),
            )
        return result

    def get_latest_risk_profile(self, account_id: str) -> dict[str, Any] | None:
        row = self._fetchone(
            "SELECT risk_profile_id FROM aurafi.risk_profiles WHERE account_id = %s ORDER BY declared_at DESC, version DESC LIMIT 1",
            (account_id,),
        )
        return self.get_risk_profile(row["risk_profile_id"]) if row else None

    def save_opportunity_snapshot(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        observation = self._mapping(snapshot.get("data_source", {}))
        apy = self._mapping(snapshot.get("apy", {}))
        tvl = self._mapping(snapshot.get("tvl", {}))
        liquidity = self._mapping(snapshot.get("liquidity", {}))
        risk = self._mapping(snapshot.get("risk", {}))
        eligibility = self._mapping(snapshot.get("eligibility", {}))
        opportunity_id = self._text(snapshot.get("opportunity_id"), "opportunity_id")
        observation_id = snapshot.get("market_observation_id") or snapshot.get("observation_id")
        observation_id = observation_id or observation.get("observation_id") or f"observation:{opportunity_id}"
        observed_at = _to_datetime(observation.get("observed_at", snapshot.get("observed_at")))
        retrieved_at = _to_datetime(observation.get("retrieved_at", snapshot.get("retrieved_at")))
        apy_value = apy.get("value", snapshot.get("apy_value"))
        tvl_value = tvl.get("value", snapshot.get("tvl_value"))
        liquidity_level = liquidity.get("level", snapshot.get("liquidity_level", "unknown"))
        liquidity_observed_at = _to_datetime(liquidity.get("observed_at", observed_at))
        apy_observed_at = _to_datetime(apy.get("observed_at", observed_at))
        tvl_observed_at = _to_datetime(tvl.get("observed_at", observed_at))
        risk_score = risk.get("score", snapshot.get("risk_score"))
        risk_level = risk.get("level", snapshot.get("risk_level"))
        dimensions = list(risk.get("dimensions", snapshot.get("risk_dimensions", [])))
        self._validate_risk_dimensions(dimensions)
        stale = bool(observation.get("is_stale", snapshot.get("is_stale", False)))
        freshness_note = observation.get("freshness_note", snapshot.get("freshness_note"))
        if stale and not freshness_note:
            raise ValueError("snapshot stale exige freshness_note")
        disclaimer = self._text(snapshot.get("disclaimer"), "disclaimer")
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO aurafi.defi_market_observations
                (market_observation_id, source, mode, observed_at, retrieved_at, cache_expires_at,
                 read_only, is_stale, freshness_note, protocol, pool, asset, blockchain,
                 apy_value, apy_unit, apy_observed_at, tvl_value, tvl_currency, tvl_observed_at,
                 liquidity_level, liquidity_value, liquidity_currency, liquidity_observed_at,
                 risk_score, risk_level, risk_dimensions, audit_status)
                VALUES (%s, %s, %s, %s, %s, %s, true, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    observation_id,
                    observation.get("source", "defillama"),
                    observation.get("mode", snapshot.get("mode", "test")),
                    observed_at,
                    retrieved_at,
                    _to_optional_datetime(observation.get("cache_expires_at")),
                    stale,
                    freshness_note,
                    snapshot.get("protocol"),
                    snapshot.get("pool"),
                    snapshot.get("asset"),
                    snapshot.get("blockchain"),
                    apy_value,
                    apy.get("unit", snapshot.get("apy_unit", "percent_annualized")),
                    apy_observed_at,
                    tvl_value,
                    tvl.get("currency", snapshot.get("tvl_currency")),
                    tvl_observed_at,
                    liquidity_level,
                    liquidity.get("value", snapshot.get("liquidity_value")),
                    liquidity.get("currency", snapshot.get("liquidity_currency")),
                    liquidity_observed_at,
                    risk.get("score", snapshot.get("observation_risk_score", risk_score)),
                    risk_level,
                    dimensions,
                    snapshot.get("audit_status"),
                ),
            )
            connection.execute(
                """INSERT INTO aurafi.opportunities
                (opportunity_id, market_observation_id, protocol, pool, asset, blockchain,
                 apy_value, apy_unit, apy_observed_at, tvl_value, tvl_currency, tvl_observed_at,
                 liquidity_level, liquidity_value, liquidity_currency, liquidity_observed_at,
                 risk_score, risk_level, risk_dimensions, audit_status, eligibility_status,
                 eligibility_reason, disclaimer, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    opportunity_id,
                    observation_id,
                    snapshot.get("protocol"),
                    snapshot.get("pool"),
                    snapshot.get("asset"),
                    snapshot.get("blockchain"),
                    apy_value,
                    apy.get("unit", snapshot.get("apy_unit", "percent_annualized")),
                    apy_observed_at,
                    tvl_value,
                    tvl.get("currency", snapshot.get("tvl_currency")),
                    tvl_observed_at,
                    liquidity_level,
                    liquidity.get("value", snapshot.get("liquidity_value")),
                    liquidity.get("currency", snapshot.get("liquidity_currency")),
                    liquidity_observed_at,
                    risk_score,
                    risk_level,
                    dimensions,
                    snapshot.get("audit_status"),
                    eligibility.get("status", snapshot.get("eligibility_status")),
                    eligibility.get("reason", snapshot.get("eligibility_reason")),
                    disclaimer,
                    self._now(),
                ),
            )
        return self.get_opportunity_snapshot(opportunity_id)  # type: ignore[return-value]

    create_opportunity_snapshot = save_opportunity_snapshot

    def get_opportunity(self, opportunity_id: str) -> dict[str, Any] | None:
        row = self._fetchone(
            "SELECT * FROM aurafi.opportunities WHERE opportunity_id = %s", (opportunity_id,)
        )
        return _stringify_timestamps(row, ("apy_observed_at", "tvl_observed_at", "liquidity_observed_at", "created_at"))

    def get_opportunity_snapshot(self, opportunity_id: str) -> dict[str, Any] | None:
        opportunity = self.get_opportunity(opportunity_id)
        if opportunity is None:
            return None
        observation = _stringify_timestamps(
            self._fetchone(
                "SELECT * FROM aurafi.defi_market_observations WHERE market_observation_id = %s",
                (opportunity["market_observation_id"],),
            ),
            ("observed_at", "retrieved_at", "cache_expires_at", "apy_observed_at", "tvl_observed_at", "liquidity_observed_at"),
        )
        if observation is None:
            return opportunity
        result = dict(opportunity)
        result["data_source"] = {
            "observation_id": observation["market_observation_id"],
            "source": observation["source"],
            "mode": observation["mode"],
            "observed_at": observation["observed_at"],
            "retrieved_at": observation["retrieved_at"],
            "cache_expires_at": observation["cache_expires_at"],
            "read_only": bool(observation["read_only"]),
            "is_stale": bool(observation["is_stale"]),
            "freshness_note": observation["freshness_note"],
        }
        result["apy"] = {"value": result.pop("apy_value"), "unit": result.pop("apy_unit"), "observed_at": result.pop("apy_observed_at")}
        result["tvl"] = {"value": result.pop("tvl_value"), "currency": result.pop("tvl_currency"), "observed_at": result.pop("tvl_observed_at")}
        result["liquidity"] = {
            "level": result.pop("liquidity_level"), "value": result.pop("liquidity_value"),
            "currency": result.pop("liquidity_currency"), "observed_at": result.pop("liquidity_observed_at"),
        }
        result["risk"] = {"score": result.pop("risk_score"), "level": result.pop("risk_level"), "dimensions": result.pop("risk_dimensions")}
        result["eligibility"] = {"status": result.pop("eligibility_status"), "reason": result.pop("eligibility_reason")}
        return result

    def list_opportunities(self) -> list[dict[str, Any]]:
        rows = self._fetchall("SELECT opportunity_id FROM aurafi.opportunities ORDER BY created_at, opportunity_id")
        return [self.get_opportunity_snapshot(row["opportunity_id"]) for row in rows]

    def save_simulation(
        self, simulation: Mapping[str, Any], scenarios: Iterable[Mapping[str, Any]] | None = None
    ) -> dict[str, Any]:
        from psycopg.types.json import Jsonb

        input_data = self._mapping(simulation.get("input", {}))
        scenario_values = list(scenarios if scenarios is not None else simulation.get("scenarios", ()))
        horizons = input_data.get("horizons_days", simulation.get("horizons_days"))
        if not horizons or len(horizons) not in range(1, 4) or len(set(horizons)) != len(horizons) or not set(horizons).issubset({30, 180, 365}):
            raise ValueError("horizons_days deve conter 1 a 3 valores unicos entre 30, 180 e 365")
        if bool(simulation.get("execution_supported", False)):
            raise ValueError("simulacao local nunca suporta execucao")
        generated_at = _to_datetime(simulation["generated_at"]) if simulation.get("generated_at") else self._now()
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO aurafi.simulations
                (simulation_id, account_id, opportunity_id, input_amount, input_asset, horizons_days,
                 compare_idle_stablecoin, assumptions, data_source_observation_id, generated_at,
                 execution_supported, disclaimer)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, false, %s)""",
                (
                    simulation.get("simulation_id"),
                    simulation.get("account_id"),
                    simulation.get("opportunity_id"),
                    input_data.get("amount", input_data.get("input_amount", simulation.get("amount", simulation.get("input_amount")))),
                    input_data.get("asset", input_data.get("input_asset", simulation.get("asset", simulation.get("input_asset")))),
                    list(horizons),
                    bool(input_data.get("compare_idle_stablecoin", simulation.get("compare_idle_stablecoin", True))),
                    Jsonb(list(simulation.get("assumptions", []))),
                    simulation.get("data_source_observation_id"),
                    generated_at,
                    self._text(simulation.get("disclaimer"), "disclaimer"),
                ),
            )
            for scenario in scenario_values:
                scenario_map = self._mapping(scenario)
                connection.execute(
                    """INSERT INTO aurafi.simulation_scenarios
                    (simulation_id, horizon_days, projected_value, projected_yield, idle_stablecoin_value, currency)
                    VALUES (%s, %s, %s, %s, %s, %s)""",
                    (
                        simulation["simulation_id"],
                        scenario_map.get("horizon_days"),
                        scenario_map.get("projected_value"),
                        scenario_map.get("projected_yield"),
                        scenario_map.get("idle_stablecoin_value"),
                        scenario_map.get("currency"),
                    ),
                )
        return self.get_simulation(simulation["simulation_id"])  # type: ignore[return-value]

    create_simulation = save_simulation

    def get_simulation(self, simulation_id: str) -> dict[str, Any] | None:
        result = self._fetchone("SELECT * FROM aurafi.simulations WHERE simulation_id = %s", (simulation_id,))
        if result is None:
            return None
        result = _stringify_timestamps(result, ("generated_at",))
        result["horizons_days"] = list(result["horizons_days"])
        result["scenarios"] = self._fetchall(
            "SELECT * FROM aurafi.simulation_scenarios WHERE simulation_id = %s ORDER BY horizon_days",
            (simulation_id,),
        )
        result["input"] = {
            "amount": result.pop("input_amount"),
            "asset": result.pop("input_asset"),
            "horizons_days": result["horizons_days"],
            "compare_idle_stablecoin": result["compare_idle_stablecoin"],
        }
        return result

    def save_conversation(self, conversation: Mapping[str, Any]) -> dict[str, Any]:
        channel = self._mapping(conversation.get("channel", {}))
        values = {
            **conversation,
            "channel_name": conversation.get("channel_name", channel.get("name")),
            "adapter": conversation.get("adapter", channel.get("adapter")),
            "simulated": conversation.get("simulated", channel.get("simulated", False)),
        }
        last_activity_at = _to_datetime(values["last_activity_at"]) if values.get("last_activity_at") else self._now()
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO aurafi.conversations
                (conversation_id, account_id, session_id, consent_id, correlation_id, channel_name,
                 adapter, simulated, status, last_activity_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    values.get("conversation_id"), values.get("account_id"), values.get("session_id"),
                    values.get("consent_id"), self._text(values.get("correlation_id"), "correlation_id"),
                    values.get("channel_name"), values.get("adapter"), bool(values.get("simulated", False)),
                    values.get("status", "active"), last_activity_at,
                ),
            )
        return self.get_conversation(values["conversation_id"])  # type: ignore[return-value]

    create_conversation = save_conversation

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        result = self._fetchone(
            "SELECT * FROM aurafi.conversations WHERE conversation_id = %s", (conversation_id,)
        )
        result = _stringify_timestamps(result, ("last_activity_at",))
        if result:
            result["channel"] = {"name": result["channel_name"], "adapter": result["adapter"], "simulated": result["simulated"]}
        return result

    def update_conversation(self, conversation: Mapping[str, Any]) -> dict[str, Any]:
        channel = self._mapping(conversation.get("channel", {}))
        values = {
            **conversation,
            "channel_name": conversation.get("channel_name", channel.get("name")),
            "adapter": conversation.get("adapter", channel.get("adapter")),
            "simulated": conversation.get("simulated", channel.get("simulated", False)),
        }
        last_activity_at = _to_datetime(values["last_activity_at"]) if values.get("last_activity_at") else self._now()
        with self._transaction() as connection:
            cursor = connection.execute(
                """UPDATE aurafi.conversations
                SET channel_name = %s, adapter = %s, simulated = %s, status = %s,
                    last_activity_at = %s
                WHERE conversation_id = %s AND account_id = %s""",
                (
                    values.get("channel_name"),
                    values.get("adapter"),
                    bool(values.get("simulated", False)),
                    values.get("status", "active"),
                    last_activity_at,
                    values.get("conversation_id"),
                    values.get("account_id"),
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(values.get("conversation_id"))
        return self.get_conversation(values["conversation_id"])  # type: ignore[return-value]

    def save_message(self, message: Mapping[str, Any]) -> dict[str, Any]:
        from psycopg.types.json import Jsonb

        conversation = self.get_conversation(message.get("conversation_id"))
        if conversation is None:
            raise ValueError("conversation_id desconhecido")
        account = self.get_account(conversation["account_id"])
        payload = message.get("payload", {})
        self._reject_secrets(payload)
        audit = self._mapping(message.get("audit", {}))
        channel = self._mapping(message.get("channel", {}))
        occurred_at = _to_datetime(message["occurred_at"]) if message.get("occurred_at") else self._now()
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO aurafi.messages
                (message_id, conversation_id, account_id, session_id, envelope_version, message_type,
                 occurred_at, request_id, correlation_id, subject_type, email_verified, channel_name,
                 channel_adapter, channel_simulated, consent_id, payload, disclaimer, audit_source,
                 audit_schema_version, trace_id, audit_actor, audit_redaction, audit_llm, audit_data_sources)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'account', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    message.get("message_id"), message["conversation_id"], conversation["account_id"],
                    conversation["session_id"], message.get("envelope_version", "1.0"), message.get("message_type"),
                    occurred_at, message.get("request_id"),
                    message.get("correlation_id", conversation["correlation_id"]), bool(account and account["email_verified"]),
                    channel.get("name", conversation["channel_name"]), channel.get("adapter", conversation["adapter"]),
                    bool(channel.get("simulated", conversation["simulated"])), conversation["consent_id"], Jsonb(payload),
                    self._text(message.get("disclaimer"), "disclaimer"), audit.get("source", "local.repository"),
                    audit.get("schema_version", "1.0"), audit.get("trace_id"),
                    audit.get("actor", "user" if message.get("message_type") == "user_message" else "hub"),
                    audit.get("redaction", "not_required"), Jsonb(audit.get("llm", {})), Jsonb(audit.get("data_sources", [])),
                ),
            )
        return self.get_message(message["message_id"])  # type: ignore[return-value]

    create_message = save_message

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        result = self._fetchone("SELECT * FROM aurafi.messages WHERE message_id = %s", (message_id,))
        return self._decode_message(result)

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            "SELECT * FROM aurafi.messages WHERE conversation_id = %s ORDER BY occurred_at, message_id",
            (conversation_id,),
        )
        return [self._decode_message(row) for row in rows]

    @staticmethod
    def _decode_message(result: dict[str, Any] | None) -> dict[str, Any] | None:
        result = _stringify_timestamps(result, ("occurred_at",))
        if result is None:
            return None
        result["email_verified"] = bool(result["email_verified"])
        result["channel_simulated"] = bool(result["channel_simulated"])
        return result

    def save_conversation_runtime_state(
        self, conversation_id: str, account_id: str, state: Mapping[str, Any]
    ) -> None:
        from psycopg.types.json import Jsonb

        self._reject_secrets(state)
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO aurafi.conversation_runtime_state
                (conversation_id, account_id, state, updated_at)
                VALUES (%s, %s, %s, %s)""",
                (
                    self._text(conversation_id, "conversation_id"),
                    self._text(account_id, "account_id"),
                    Jsonb(dict(state)),
                    self._now(),
                ),
            )

    def get_conversation_runtime_state(self, conversation_id: str) -> dict[str, Any] | None:
        row = self._fetchone(
            "SELECT state FROM aurafi.conversation_runtime_state WHERE conversation_id = %s",
            (conversation_id,),
        )
        return row["state"] if row is not None else None

    def latest_conversation_runtime_state(self, account_id: str) -> dict[str, Any] | None:
        row = self._fetchone(
            """SELECT state FROM aurafi.conversation_runtime_state
            WHERE account_id = %s ORDER BY updated_at DESC, conversation_id DESC
            LIMIT 1""",
            (account_id,),
        )
        return row["state"] if row is not None else None

    def update_conversation_runtime_state(
        self, conversation_id: str, account_id: str, state: Mapping[str, Any]
    ) -> None:
        from psycopg.types.json import Jsonb

        self._reject_secrets(state)
        with self._transaction() as connection:
            cursor = connection.execute(
                """UPDATE aurafi.conversation_runtime_state
                SET account_id = %s, state = %s, updated_at = %s
                WHERE conversation_id = %s""",
                (
                    self._text(account_id, "account_id"),
                    Jsonb(dict(state)),
                    self._now(),
                    self._text(conversation_id, "conversation_id"),
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(conversation_id)

    def save_alert(self, alert: Mapping[str, Any]) -> dict[str, Any]:
        source = self._mapping(alert.get("data_source", {}))
        observation_id = alert.get("data_source_observation_id") or source.get("observation_id")
        created_at = _to_datetime(alert["created_at"]) if alert.get("created_at") else self._now()
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO aurafi.alerts
                (alert_id, account_id, opportunity_id, data_source_observation_id, type, title, message,
                 status, created_at, observed_at, suggested_action, disclaimer)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    alert.get("alert_id"), alert.get("account_id"), alert.get("opportunity_id"), observation_id,
                    alert.get("type"), alert.get("title"), alert.get("message"), alert.get("status", "unread"),
                    created_at, _to_optional_datetime(alert.get("observed_at", source.get("observed_at"))),
                    alert.get("suggested_action", "none"), self._text(alert.get("disclaimer"), "disclaimer"),
                ),
            )
        return self.get_alert(alert["alert_id"])  # type: ignore[return-value]

    create_alert = save_alert

    def get_alert(self, alert_id: str) -> dict[str, Any] | None:
        row = self._fetchone("SELECT * FROM aurafi.alerts WHERE alert_id = %s", (alert_id,))
        return _stringify_timestamps(row, ("created_at", "observed_at"))

    def list_alerts(self, account_id: str, *, status: str | None = None) -> list[dict[str, Any]]:
        if status is None:
            rows = self._fetchall(
                "SELECT * FROM aurafi.alerts WHERE account_id = %s ORDER BY created_at, alert_id", (account_id,)
            )
        else:
            rows = self._fetchall(
                "SELECT * FROM aurafi.alerts WHERE account_id = %s AND status = %s ORDER BY created_at, alert_id",
                (account_id, status),
            )
        return [_stringify_timestamps(row, ("created_at", "observed_at")) for row in rows]

    def mark_alert_read(self, alert_id: str) -> dict[str, Any] | None:
        with self._transaction() as connection:
            connection.execute("UPDATE aurafi.alerts SET status = 'read' WHERE alert_id = %s", (alert_id,))
        return self.get_alert(alert_id)

    def get_idempotent_response(
        self, principal: str, route: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        return self._fetchone(
            """SELECT * FROM aurafi.idempotent_responses
            WHERE principal = %s AND route = %s AND idempotency_key = %s""",
            (principal, route, idempotency_key),
        )

    def save_idempotent_response(
        self,
        *,
        principal: str,
        route: str,
        idempotency_key: str,
        request_hash: str,
        response_status: int,
        response_payload: Any,
        created_at: Any = None,
    ) -> dict[str, Any]:
        from psycopg.types.json import Jsonb

        timestamp = _to_datetime(created_at) if created_at is not None else self._now()
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO aurafi.idempotent_responses
                (principal, route, idempotency_key, request_hash, response_status, response_payload, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    self._text(principal, "principal"),
                    self._text(route, "route"),
                    self._text(idempotency_key, "idempotency_key"),
                    self._text(request_hash, "request_hash"),
                    int(response_status),
                    Jsonb(response_payload),
                    timestamp,
                ),
            )
        return self.get_idempotent_response(principal, route, idempotency_key)  # type: ignore[return-value]

    # Dados da conta: exportação, exclusão e retenção (regras em database/account_data.py).

    def export_account_rows(self, account_id: str) -> dict[str, list[dict[str, Any]]]:
        """Linhas de cada seção exportável da conta, sem colunas secretas."""

        account = self.get_account(account_id)
        if account is None:
            return {}
        sections: dict[str, list[dict[str, Any]]] = {}
        for spec, condition, count in account_data.statements(self._table_names(), schema="aurafi", placeholder="%s"):
            if spec.section is None:
                continue
            parameter = account["email"] if spec.parameter == "email" else account_id
            rows = self._fetchall(f"SELECT * FROM aurafi.{spec.table} WHERE {condition}", (parameter,) * count)
            sections[spec.section] = [
                {key: value for key, value in row.items() if key not in spec.omit} for row in rows
            ]
        return sections

    def delete_account(self, account_id: str) -> dict[str, int]:
        """Apaga a conta e todos os dados dela numa única transação."""

        account = self.get_account(account_id)
        if account is None:
            return {}
        tables = self._table_names()
        counts: dict[str, int] = {}
        with self._transaction() as connection:
            # Liberado pela migration 003 só enquanto esta transação durar.
            connection.execute("SELECT set_config('aurafi.account_erasure', 'on', true)")
            for spec, condition, count in account_data.statements(tables, schema="aurafi", placeholder="%s"):
                parameter = account["email"] if spec.parameter == "email" else account_id
                cursor = connection.execute(
                    f"DELETE FROM aurafi.{spec.table} WHERE {condition}", (parameter,) * count
                )
                counts[spec.table] = cursor.rowcount
        return counts

    def purge_expired_records(
        self, now: datetime | None = None, *, keep_account_ids: Iterable[str] = ()
    ) -> dict[str, int]:
        """Remove códigos vencidos, respostas de idempotência antigas e contas nunca confirmadas."""

        cutoffs = account_data.retention_cutoffs(now or self._now())
        keep = tuple(keep_account_ids)
        tables = self._table_names()
        dependents = " AND ".join(
            f"NOT EXISTS (SELECT 1 FROM aurafi.{table} d WHERE d.account_id = a.account_id)"
            for table in account_data.ACCOUNT_DEPENDENT_TABLES
            if table in tables
        )
        keep_clause = " AND NOT (a.account_id = ANY(%s))" if keep else ""
        counts: dict[str, int] = {}
        with self._transaction() as connection:
            counts["otp_challenges"] = connection.execute(
                "DELETE FROM aurafi.otp_challenges WHERE expires_at < %s", (cutoffs["otp_challenges"],)
            ).rowcount
            counts["idempotent_responses"] = connection.execute(
                "DELETE FROM aurafi.idempotent_responses WHERE created_at < %s",
                (cutoffs["idempotent_responses"],),
            ).rowcount
            counts["unverified_accounts"] = connection.execute(
                "DELETE FROM aurafi.accounts a WHERE a.email_verified = false AND a.created_at < %s"
                f"{keep_clause} AND {dependents}",
                (cutoffs["unverified_accounts"], *((list(keep),) if keep else ())),
            ).rowcount
        return counts

    def _table_names(self) -> set[str]:
        rows = self._fetchall(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'aurafi'"
        )
        return {str(row["table_name"]) for row in rows}

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self._lock:
            connection = self._require_connection()
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _fetchone(self, query: str, parameters: tuple[Any, ...]) -> dict[str, Any] | None:
        with self._lock:
            connection = self._require_connection()
            with connection.cursor(row_factory=self._dict_row) as cursor:
                cursor.execute(query, parameters)
                return cursor.fetchone()

    def _fetchall(self, query: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            connection = self._require_connection()
            with connection.cursor(row_factory=self._dict_row) as cursor:
                cursor.execute(query, parameters)
                return cursor.fetchall()

    def _require_connection(self) -> Any:
        if self._connection is None or self._connection.closed:
            raise RuntimeError("PostgresRepository ja foi fechado")
        return self._connection

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)
        if value is None:
            return {}
        if hasattr(value, "to_dict"):
            mapped = value.to_dict()
            return dict(mapped) if isinstance(mapped, Mapping) else {}
        return {name: getattr(value, name) for name in dir(value) if not name.startswith("_") and not callable(getattr(value, name))}

    @staticmethod
    def _text(value: Any, name: str) -> str:
        if value is None or not str(value).strip():
            raise ValueError(f"{name} e obrigatorio")
        return str(value)

    @staticmethod
    def _normalize_email(email: Any) -> str:
        if email is None or not str(email).strip():
            raise ValueError("email e obrigatorio")
        return str(email).strip().lower()

    @staticmethod
    def _bool_or_none(value: Any) -> bool | None:
        return None if value is None else bool(value)

    @staticmethod
    def _validate_risk_dimensions(dimensions: Iterable[str]) -> None:
        invalid = set(dimensions) - _RISK_DIMENSIONS
        if invalid:
            raise ValueError(f"dimensoes de risco invalidas: {sorted(invalid)}")

    @classmethod
    def _reject_secrets(cls, value: Any) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                normalized = re.sub(r"[^a-z0-9_]", "_", str(key).lower())
                if normalized in _SECRET_KEYS:
                    raise ValueError(f"campo secreto nao pode ser persistido: {key}")
                cls._reject_secrets(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                cls._reject_secrets(nested)


def create_repository(database_url: str | None) -> PostgresRepository | None:
    """Cria e migra o adapter PostgreSQL quando ``DATABASE_URL`` foi configurada.

    Sem URL, retorna ``None``. Erros de conexao ou de migracao sao propagados;
    nao ha fallback silencioso para outro armazenamento.
    """

    if database_url is None or not str(database_url).strip():
        return None
    repository = PostgresRepository(str(database_url).strip())
    repository.initialize()
    return repository


__all__ = ["PostgresRepository", "create_repository"]
