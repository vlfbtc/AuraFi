"""Small stdlib-only SQLite repository for the AuraFi MVP local/demo journey.

The repository is intentionally an adapter, not a domain service. Its schema is
compatible with the approved PostgreSQL model where the local MVP needs it, but
it is not a PostgreSQL/RDS migration or a production database implementation.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping

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


class SQLiteRepository:
    """Transaction-safe local adapter with an explicit close lifecycle.

    One connection is owned by the repository and guarded by a lock. This is
    suitable for a local/demo process and intentionally does not attempt to be
    a connection pool or a multi-process writer abstraction.
    """

    def __init__(
        self,
        database_path: str | Path,
        *,
        now: Callable[[], datetime] | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.database_path = str(database_path)
        self._lock = threading.RLock()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._connection: sqlite3.Connection | None = sqlite3.connect(
            self.database_path,
            timeout=timeout,
            isolation_level=None,
            # The API uses ThreadingHTTPServer. Every connection access remains
            # serialized by self._lock, so allowing the owning connection to be
            # used by request threads is safe for this single-process adapter.
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")

    @property
    def is_closed(self) -> bool:
        return self._connection is None

    def initialize(self, schema_path: str | Path | None = None) -> None:
        """Apply the local schema; running it again is safe."""

        path = Path(schema_path) if schema_path else Path(__file__).with_name("schema.sql")
        with self._lock:
            connection = self._require_connection()
            connection.executescript(path.read_text(encoding="utf-8"))
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(otp_challenges)").fetchall()
            }
            if "attempts" not in columns:
                connection.execute(
                    "ALTER TABLE otp_challenges ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0)"
                )

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def __enter__(self) -> "SQLiteRepository":
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
        timestamp = self._timestamp(created_at)
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO accounts (account_id, email, email_verified, created_at) VALUES (?, ?, ?, ?)",
                (self._text(account_id, "account_id"), self._normalize_email(email), int(email_verified), timestamp),
            )
        return self.get_account(account_id)  # type: ignore[return-value]

    create_account = save_account

    def get_account(self, account_id: str) -> dict[str, Any] | None:
        row = self._fetchone("SELECT * FROM accounts WHERE account_id = ?", (account_id,))
        return self._row(row)

    def find_account_by_email(self, email: str) -> dict[str, Any] | None:
        row = self._fetchone(
            "SELECT * FROM accounts WHERE email = ? ORDER BY created_at, account_id LIMIT 1",
            (self._normalize_email(email),),
        )
        return self._row(row)

    find_by_email = find_account_by_email

    def mark_email_verified(self, account_id: str, verified_at: Any = None) -> dict[str, Any] | None:
        del verified_at  # The local contract only changes the boolean state.
        with self._transaction() as connection:
            connection.execute("UPDATE accounts SET email_verified = 1 WHERE account_id = ?", (account_id,))
        return self.get_account(account_id)

    def save_otp_challenge(
        self,
        challenge: Mapping[str, Any] | Any,
        *,
        otp: str | None = None,
        otp_digest: str | None = None,
    ) -> dict[str, Any]:
        values = self._mapping(challenge)
        if not values:
            raise TypeError("challenge deve ser um mapping ou objeto com atributos")
        digest = otp_digest or values.get("otp_digest") or values.get("otp_hash")
        if digest is None:
            otp = otp or values.get("otp")
            if otp is None:
                raise ValueError("otp_digest ou otp e obrigatorio")
            digest = hashlib.sha256(str(otp).encode("utf-8")).hexdigest()
        # The clear OTP is accepted only as an input convenience for the
        # standalone adapter. It is removed before any SQL parameter is built.
        if "otp" in values:
            values = dict(values)
            values.pop("otp", None)
        created_at = self._timestamp(values.get("created_at"))
        expires_at = self._timestamp(values.get("expires_at"))
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO otp_challenges
                (challenge_id, email, channel, delivery, otp_digest, attempts, status, expires_at, created_at, verified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    self._optional_timestamp(values.get("verified_at")),
                ),
            )
        return self.get_otp_challenge(values["challenge_id"])  # type: ignore[return-value]

    create_otp_challenge = save_otp_challenge

    def get_otp_challenge(self, challenge_id: str) -> dict[str, Any] | None:
        return self._row(self._fetchone("SELECT * FROM otp_challenges WHERE challenge_id = ?", (challenge_id,)))

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
                "UPDATE otp_challenges SET status = ?, verified_at = ?, attempts = ? WHERE challenge_id = ?",
                (status, self._optional_timestamp(verified_at), int(attempts), challenge_id),
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
        values = self._mapping(session)
        session_id = values.get("session_id", session) if values else session
        account_id = values.get("account_id", account_id)
        expires_at = values.get("expires_at", expires_at)
        started_at = values.get("started_at", started_at)
        status = values.get("status", status)
        ended_at = values.get("ended_at", ended_at)
        access_token_digest = values.get("access_token_digest", access_token_digest)
        refresh_token_digest = values.get("refresh_token_digest", refresh_token_digest)
        # Keep the repository boundary safe for callers that still have a raw
        # token: only its digest can reach the sessions table.
        if access_token_digest is None and values.get("access_token") is not None:
            access_token_digest = self._digest_secret(values["access_token"])
        if refresh_token_digest is None and values.get("refresh_token") is not None:
            refresh_token_digest = self._digest_secret(values["refresh_token"])
        if account_id is None or expires_at is None:
            raise ValueError("account_id e expires_at sao obrigatorios")
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO sessions
                (session_id, account_id, started_at, expires_at, status, ended_at,
                 access_token_digest, refresh_token_digest)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self._text(session_id, "session_id"),
                    self._text(account_id, "account_id"),
                    self._timestamp(started_at),
                    self._timestamp(expires_at),
                    status,
                    self._optional_timestamp(ended_at),
                    access_token_digest,
                    refresh_token_digest,
                ),
            )
        return self.get_session(session_id)  # type: ignore[return-value]

    create_session = save_session

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self._row(self._fetchone("SELECT * FROM sessions WHERE session_id = ?", (session_id,)))

    def get_by_access_token_digest(self, digest: str) -> dict[str, Any] | None:
        return self._row(self._fetchone("SELECT * FROM sessions WHERE access_token_digest = ?", (digest,)))

    def get_by_refresh_token_digest(self, digest: str) -> dict[str, Any] | None:
        return self._row(self._fetchone("SELECT * FROM sessions WHERE refresh_token_digest = ?", (digest,)))

    def update_session(self, session: Mapping[str, Any] | Any) -> dict[str, Any]:
        values = self._mapping(session)
        if not values or not values.get("session_id"):
            raise ValueError("session_id e obrigatorio")
        if "access_token_digest" not in values and values.get("access_token") is not None:
            values["access_token_digest"] = self._digest_secret(values["access_token"])
        if "refresh_token_digest" not in values and values.get("refresh_token") is not None:
            values["refresh_token_digest"] = self._digest_secret(values["refresh_token"])
        assignments = {
            key: values[key]
            for key in ("expires_at", "status", "ended_at", "access_token_digest", "refresh_token_digest")
            if key in values
        }
        if "expires_at" in assignments:
            assignments["expires_at"] = self._timestamp(assignments["expires_at"])
        if "ended_at" in assignments:
            assignments["ended_at"] = self._optional_timestamp(assignments["ended_at"])
        if not assignments:
            return self.get_session(values["session_id"])  # type: ignore[return-value]
        clause = ", ".join(f"{key} = ?" for key in assignments)
        with self._transaction() as connection:
            connection.execute(
                f"UPDATE sessions SET {clause} WHERE session_id = ?",
                (*assignments.values(), values["session_id"]),
            )
        return self.get_session(values["session_id"])  # type: ignore[return-value]

    def save_channel_identity(
        self, association: Mapping[str, Any] | Any
    ) -> dict[str, Any]:
        values = self._mapping(association)
        channel = self._mapping(values.get("channel", {}))
        channel_name = values.get("channel_name", channel.get("name"))
        adapter = values.get("adapter", channel.get("adapter"))
        simulated = values.get("simulated", channel.get("simulated", False))
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO channel_identities
                (channel_identity_id, account_id, channel_name, adapter, simulated, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    self._text(values.get("channel_identity_id"), "channel_identity_id"),
                    self._text(values.get("account_id"), "account_id"),
                    channel_name,
                    self._text(adapter, "adapter"),
                    int(bool(simulated)),
                    self._timestamp(values.get("created_at")),
                ),
            )
        return self.get_channel_identity(values["channel_identity_id"])  # type: ignore[return-value]

    create_channel_identity = save_channel_identity

    def get_channel_identity(self, channel_identity_id: str) -> dict[str, Any] | None:
        return self._decode_channel_identity(
            self._row(
                self._fetchone(
                    "SELECT * FROM channel_identities WHERE channel_identity_id = ?",
                    (channel_identity_id,),
                )
            )
        )

    def find_channel_identity(
        self, account_id: str, channel_name: str, adapter: str
    ) -> dict[str, Any] | None:
        return self._decode_channel_identity(
            self._row(
                self._fetchone(
                    """SELECT * FROM channel_identities
                    WHERE account_id = ? AND channel_name = ? AND adapter = ?""",
                    (account_id, channel_name, adapter),
                )
            )
        )

    def first_channel_identity(self, account_id: str) -> dict[str, Any] | None:
        return self._decode_channel_identity(
            self._row(
                self._fetchone(
                    """SELECT * FROM channel_identities
                    WHERE account_id = ? ORDER BY created_at, channel_identity_id LIMIT 1""",
                    (account_id,),
                )
            )
        )

    def save_consent(self, consent: Mapping[str, Any] | Any, **overrides: Any) -> dict[str, Any]:
        values = self._mapping(consent)
        values.update(overrides)
        required = ("consent_id", "account_id", "purpose", "status", "policy_version")
        for key in required:
            if values.get(key) is None:
                raise ValueError(f"{key} e obrigatorio")
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO consents
                (consent_id, account_id, purpose, status, policy_version, captured_at, memory, analytics)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    values["consent_id"],
                    values["account_id"],
                    values["purpose"],
                    values["status"],
                    values["policy_version"],
                    self._timestamp(values.get("captured_at")),
                    self._bool_or_none(values.get("memory")),
                    self._bool_or_none(values.get("analytics")),
                ),
            )
        return self.get_consent(values["consent_id"])  # type: ignore[return-value]

    create_consent = save_consent

    def get_consent(self, consent_id: str) -> dict[str, Any] | None:
        return self._row(self._fetchone("SELECT * FROM consents WHERE consent_id = ?", (consent_id,)))

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
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO risk_profiles
                (risk_profile_id, account_id, declared_profile, status, version, declared_at, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    values.get("risk_profile_id"),
                    values.get("account_id"),
                    values.get("declared_profile"),
                    status,
                    values.get("version"),
                    self._timestamp(values.get("declared_at")),
                    values.get("source", "questionnaire" if status == "declared" else None),
                ),
            )
            for answer in answer_values:
                answer_values_map = self._mapping(answer)
                connection.execute(
                    "INSERT INTO risk_profile_answers (risk_profile_id, question_id, answer) VALUES (?, ?, ?)",
                    (values["risk_profile_id"], answer_values_map.get("question_id"), answer_values_map.get("answer")),
                )
        return self.get_risk_profile(values["risk_profile_id"])  # type: ignore[return-value]

    create_risk_profile = save_risk_profile

    def get_risk_profile(self, risk_profile_id: str) -> dict[str, Any] | None:
        row = self._fetchone("SELECT * FROM risk_profiles WHERE risk_profile_id = ?", (risk_profile_id,))
        result = self._row(row)
        if result is not None:
            result["answers"] = [
                self._row(answer)
                for answer in self._fetchall(
                    "SELECT question_id, answer FROM risk_profile_answers WHERE risk_profile_id = ? ORDER BY question_id",
                    (risk_profile_id,),
                )
            ]
        return result

    def get_latest_risk_profile(self, account_id: str) -> dict[str, Any] | None:
        row = self._fetchone(
            "SELECT * FROM risk_profiles WHERE account_id = ? ORDER BY declared_at DESC, version DESC LIMIT 1",
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
        observed_at = self._timestamp(observation.get("observed_at", snapshot.get("observed_at")))
        retrieved_at = self._timestamp(observation.get("retrieved_at", snapshot.get("retrieved_at")))
        apy_value = apy.get("value", snapshot.get("apy_value"))
        tvl_value = tvl.get("value", snapshot.get("tvl_value"))
        liquidity_level = liquidity.get("level", snapshot.get("liquidity_level", "unknown"))
        liquidity_observed_at = self._timestamp(liquidity.get("observed_at", observed_at))
        apy_observed_at = self._timestamp(apy.get("observed_at", observed_at))
        tvl_observed_at = self._timestamp(tvl.get("observed_at", observed_at))
        risk_score = risk.get("score", snapshot.get("risk_score"))
        risk_level = risk.get("level", snapshot.get("risk_level"))
        dimensions = risk.get("dimensions", snapshot.get("risk_dimensions", []))
        self._validate_risk_dimensions(dimensions)
        stale = bool(observation.get("is_stale", snapshot.get("is_stale", False)))
        freshness_note = observation.get("freshness_note", snapshot.get("freshness_note"))
        if stale and not freshness_note:
            raise ValueError("snapshot stale exige freshness_note")
        disclaimer = self._text(snapshot.get("disclaimer"), "disclaimer")
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO defi_market_observations
                (market_observation_id, source, mode, observed_at, retrieved_at, cache_expires_at,
                 read_only, is_stale, freshness_note, protocol, pool, asset, blockchain,
                 apy_value, apy_unit, apy_observed_at, tvl_value, tvl_currency, tvl_observed_at,
                 liquidity_level, liquidity_value, liquidity_currency, liquidity_observed_at,
                 risk_score, risk_level, risk_dimensions, audit_status)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    observation_id,
                    observation.get("source", "defillama"),
                    observation.get("mode", snapshot.get("mode", "test")),
                    observed_at,
                    retrieved_at,
                    self._optional_timestamp(observation.get("cache_expires_at")),
                    int(stale),
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
                    self._json(dimensions),
                    snapshot.get("audit_status"),
                ),
            )
            connection.execute(
                """INSERT INTO opportunities
                (opportunity_id, market_observation_id, protocol, pool, asset, blockchain,
                 apy_value, apy_unit, apy_observed_at, tvl_value, tvl_currency, tvl_observed_at,
                 liquidity_level, liquidity_value, liquidity_currency, liquidity_observed_at,
                 risk_score, risk_level, risk_dimensions, audit_status, eligibility_status,
                 eligibility_reason, disclaimer, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    self._json(dimensions),
                    snapshot.get("audit_status"),
                    eligibility.get("status", snapshot.get("eligibility_status")),
                    eligibility.get("reason", snapshot.get("eligibility_reason")),
                    disclaimer,
                    self._timestamp(snapshot.get("created_at")),
                ),
            )
        return self.get_opportunity_snapshot(opportunity_id)  # type: ignore[return-value]

    create_opportunity_snapshot = save_opportunity_snapshot

    def get_opportunity(self, opportunity_id: str) -> dict[str, Any] | None:
        return self._row(self._fetchone("SELECT * FROM opportunities WHERE opportunity_id = ?", (opportunity_id,)))

    def get_opportunity_snapshot(self, opportunity_id: str) -> dict[str, Any] | None:
        opportunity = self.get_opportunity(opportunity_id)
        if opportunity is None:
            return None
        observation = self._row(
            self._fetchone(
                "SELECT * FROM defi_market_observations WHERE market_observation_id = ?",
                (opportunity["market_observation_id"],),
            )
        )
        if observation is None:
            return opportunity
        result = dict(opportunity)
        result["risk_dimensions"] = json.loads(result["risk_dimensions"])
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
        return [self.get_opportunity_snapshot(row["opportunity_id"]) for row in self._fetchall("SELECT opportunity_id FROM opportunities ORDER BY created_at, opportunity_id")]

    def save_simulation(self, simulation: Mapping[str, Any], scenarios: Iterable[Mapping[str, Any]] | None = None) -> dict[str, Any]:
        input_data = self._mapping(simulation.get("input", {}))
        scenario_values = list(scenarios if scenarios is not None else simulation.get("scenarios", ()))
        horizons = input_data.get("horizons_days", simulation.get("horizons_days"))
        if not horizons or len(horizons) not in range(1, 4) or len(set(horizons)) != len(horizons) or not set(horizons).issubset({30, 180, 365}):
            raise ValueError("horizons_days deve conter 1 a 3 valores unicos entre 30, 180 e 365")
        if bool(simulation.get("execution_supported", False)):
            raise ValueError("simulacao local nunca suporta execucao")
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO simulations
                (simulation_id, account_id, opportunity_id, input_amount, input_asset, horizons_days,
                 compare_idle_stablecoin, assumptions, data_source_observation_id, generated_at,
                 execution_supported, disclaimer)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                (
                    simulation.get("simulation_id"),
                    simulation.get("account_id"),
                    simulation.get("opportunity_id"),
                    input_data.get("amount", input_data.get("input_amount", simulation.get("amount", simulation.get("input_amount")))),
                    input_data.get("asset", input_data.get("input_asset", simulation.get("asset", simulation.get("input_asset")))),
                    self._json(list(horizons)),
                    int(input_data.get("compare_idle_stablecoin", simulation.get("compare_idle_stablecoin", True))),
                    self._json(simulation.get("assumptions", [])),
                    simulation.get("data_source_observation_id"),
                    self._timestamp(simulation.get("generated_at")),
                    self._text(simulation.get("disclaimer"), "disclaimer"),
                ),
            )
            for scenario in scenario_values:
                scenario_map = self._mapping(scenario)
                connection.execute(
                    """INSERT INTO simulation_scenarios
                    (simulation_id, horizon_days, projected_value, projected_yield, idle_stablecoin_value, currency)
                    VALUES (?, ?, ?, ?, ?, ?)""",
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
        result = self._row(self._fetchone("SELECT * FROM simulations WHERE simulation_id = ?", (simulation_id,)))
        if result is None:
            return None
        result["horizons_days"] = json.loads(result["horizons_days"])
        result["assumptions"] = json.loads(result["assumptions"])
        result["execution_supported"] = bool(result["execution_supported"])
        result["compare_idle_stablecoin"] = bool(result["compare_idle_stablecoin"])
        result["scenarios"] = [
            self._row(row)
            for row in self._fetchall(
                "SELECT * FROM simulation_scenarios WHERE simulation_id = ? ORDER BY horizon_days",
                (simulation_id,),
            )
        ]
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
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO conversations
                (conversation_id, account_id, session_id, consent_id, correlation_id, channel_name,
                 adapter, simulated, status, last_activity_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    values.get("conversation_id"), values.get("account_id"), values.get("session_id"),
                    values.get("consent_id"), self._text(values.get("correlation_id"), "correlation_id"),
                    values.get("channel_name"), values.get("adapter"), int(bool(values.get("simulated", False))),
                    values.get("status", "active"), self._timestamp(values.get("last_activity_at")),
                ),
            )
        return self.get_conversation(values["conversation_id"])  # type: ignore[return-value]

    create_conversation = save_conversation

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        result = self._row(self._fetchone("SELECT * FROM conversations WHERE conversation_id = ?", (conversation_id,)))
        if result:
            result["simulated"] = bool(result["simulated"])
            result["channel"] = {"name": result["channel_name"], "adapter": result["adapter"], "simulated": result["simulated"]}
        return result

    def update_conversation(self, conversation: Mapping[str, Any]) -> dict[str, Any]:
        channel = self._mapping(conversation.get("channel", {}))
        values = {
            **conversation,
            "channel_name": conversation.get("channel_name", channel.get("name")),
            "adapter": conversation.get("adapter", channel.get("adapter")),
            "simulated": conversation.get(
                "simulated", channel.get("simulated", False)
            ),
        }
        with self._transaction() as connection:
            cursor = connection.execute(
                """UPDATE conversations
                SET channel_name = ?, adapter = ?, simulated = ?, status = ?,
                    last_activity_at = ?
                WHERE conversation_id = ? AND account_id = ?""",
                (
                    values.get("channel_name"),
                    values.get("adapter"),
                    int(bool(values.get("simulated", False))),
                    values.get("status", "active"),
                    self._timestamp(values.get("last_activity_at")),
                    values.get("conversation_id"),
                    values.get("account_id"),
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(values.get("conversation_id"))
        return self.get_conversation(values["conversation_id"])  # type: ignore[return-value]

    def save_message(self, message: Mapping[str, Any]) -> dict[str, Any]:
        conversation = self.get_conversation(message.get("conversation_id"))
        if conversation is None:
            raise ValueError("conversation_id desconhecido")
        account = self.get_account(conversation["account_id"])
        payload = message.get("payload", {})
        self._reject_secrets(payload)
        audit = self._mapping(message.get("audit", {}))
        channel = self._mapping(message.get("channel", {}))
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO messages
                (message_id, conversation_id, account_id, session_id, envelope_version, message_type,
                 occurred_at, request_id, correlation_id, subject_type, email_verified, channel_name,
                 channel_adapter, channel_simulated, consent_id, payload, disclaimer, audit_source,
                 audit_schema_version, trace_id, audit_actor, audit_redaction, audit_llm, audit_data_sources)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'account', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    message.get("message_id"), message["conversation_id"], conversation["account_id"],
                    conversation["session_id"], message.get("envelope_version", "1.0"), message.get("message_type"),
                    self._timestamp(message.get("occurred_at")), message.get("request_id"),
                    message.get("correlation_id", conversation["correlation_id"]), int(bool(account and account["email_verified"])),
                    channel.get("name", conversation["channel_name"]), channel.get("adapter", conversation["adapter"]),
                    int(bool(channel.get("simulated", conversation["simulated"]))), conversation["consent_id"], self._json(payload),
                    self._text(message.get("disclaimer"), "disclaimer"), audit.get("source", "local.repository"),
                    audit.get("schema_version", "1.0"), audit.get("trace_id"),
                    audit.get("actor", "user" if message.get("message_type") == "user_message" else "hub"),
                    audit.get("redaction", "not_required"), self._json(audit.get("llm", {})), self._json(audit.get("data_sources", [])),
                ),
            )
        return self.get_message(message["message_id"])  # type: ignore[return-value]

    create_message = save_message

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        result = self._row(self._fetchone("SELECT * FROM messages WHERE message_id = ?", (message_id,)))
        return self._decode_message(result)

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        return [self._decode_message(self._row(row)) for row in self._fetchall("SELECT * FROM messages WHERE conversation_id = ? ORDER BY occurred_at, message_id", (conversation_id,))]

    def save_conversation_runtime_state(
        self,
        conversation_id: str,
        account_id: str,
        state: Mapping[str, Any],
    ) -> None:
        self._reject_secrets(state)
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO conversation_runtime_state
                (conversation_id, account_id, state_json, updated_at)
                VALUES (?, ?, ?, ?)""",
                (
                    self._text(conversation_id, "conversation_id"),
                    self._text(account_id, "account_id"),
                    self._json(state),
                    self._timestamp(self._now()),
                ),
            )

    def get_conversation_runtime_state(self, conversation_id: str) -> dict[str, Any] | None:
        row = self._row(
            self._fetchone(
                "SELECT state_json FROM conversation_runtime_state WHERE conversation_id = ?",
                (conversation_id,),
            )
        )
        return json.loads(row["state_json"]) if row is not None else None

    def latest_conversation_runtime_state(
        self, account_id: str
    ) -> dict[str, Any] | None:
        row = self._row(
            self._fetchone(
                """SELECT state_json FROM conversation_runtime_state
                WHERE account_id = ? ORDER BY updated_at DESC, conversation_id DESC
                LIMIT 1""",
                (account_id,),
            )
        )
        return json.loads(row["state_json"]) if row is not None else None

    def update_conversation_runtime_state(
        self,
        conversation_id: str,
        account_id: str,
        state: Mapping[str, Any],
    ) -> None:
        self._reject_secrets(state)
        with self._transaction() as connection:
            cursor = connection.execute(
                """UPDATE conversation_runtime_state
                SET account_id = ?, state_json = ?, updated_at = ?
                WHERE conversation_id = ?""",
                (
                    self._text(account_id, "account_id"),
                    self._json(state),
                    self._timestamp(self._now()),
                    self._text(conversation_id, "conversation_id"),
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(conversation_id)

    def save_alert(self, alert: Mapping[str, Any]) -> dict[str, Any]:
        source = self._mapping(alert.get("data_source", {}))
        observation_id = alert.get("data_source_observation_id") or source.get("observation_id")
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO alerts
                (alert_id, account_id, opportunity_id, data_source_observation_id, type, title, message,
                 status, created_at, observed_at, suggested_action, disclaimer)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    alert.get("alert_id"), alert.get("account_id"), alert.get("opportunity_id"), observation_id,
                    alert.get("type"), alert.get("title"), alert.get("message"), alert.get("status", "unread"),
                    self._timestamp(alert.get("created_at")), self._optional_timestamp(alert.get("observed_at", source.get("observed_at"))),
                    alert.get("suggested_action", "none"), self._text(alert.get("disclaimer"), "disclaimer"),
                ),
            )
        return self.get_alert(alert["alert_id"])  # type: ignore[return-value]

    create_alert = save_alert

    def get_alert(self, alert_id: str) -> dict[str, Any] | None:
        return self._row(self._fetchone("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)))

    def list_alerts(self, account_id: str, *, status: str | None = None) -> list[dict[str, Any]]:
        if status is None:
            rows = self._fetchall("SELECT * FROM alerts WHERE account_id = ? ORDER BY created_at, alert_id", (account_id,))
        else:
            rows = self._fetchall("SELECT * FROM alerts WHERE account_id = ? AND status = ? ORDER BY created_at, alert_id", (account_id, status))
        return [self._row(row) for row in rows]

    def mark_alert_read(self, alert_id: str) -> dict[str, Any] | None:
        with self._transaction() as connection:
            connection.execute("UPDATE alerts SET status = 'read' WHERE alert_id = ?", (alert_id,))
        return self.get_alert(alert_id)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = self._require_connection()
            connection.execute("BEGIN")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _fetchone(self, query: str, parameters: tuple[Any, ...]) -> sqlite3.Row | None:
        with self._lock:
            return self._require_connection().execute(query, parameters).fetchone()

    def _fetchall(self, query: str, parameters: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._require_connection().execute(query, parameters).fetchall()

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("SQLiteRepository ja foi fechado")
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

    def _timestamp(self, value: Any) -> str:
        if value is None:
            value = self._now()
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif isinstance(value, datetime):
            parsed = value
        else:
            raise TypeError("timestamp deve ser datetime ou ISO-8601")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime(_TIMESTAMP_FORMAT)

    def _optional_timestamp(self, value: Any) -> str | None:
        return None if value is None else self._timestamp(value)

    @staticmethod
    def _normalize_email(email: Any) -> str:
        if email is None or not str(email).strip():
            raise ValueError("email e obrigatorio")
        return str(email).strip().lower()

    @staticmethod
    def _bool_or_none(value: Any) -> int | None:
        return None if value is None else int(bool(value))

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _digest_secret(value: Any) -> str:
        return hashlib.sha256(str(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _row(row: sqlite3.Row | Mapping[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for key in ("email_verified", "read_only", "is_stale", "execution_supported", "compare_idle_stablecoin", "simulated", "channel_simulated"):
            if key in result and result[key] is not None:
                result[key] = bool(result[key])
        return result

    def _decode_message(self, result: dict[str, Any] | None) -> dict[str, Any] | None:
        if result is None:
            return None
        for key in ("payload", "audit_llm", "audit_data_sources"):
            result[key] = json.loads(result[key])
        result["email_verified"] = bool(result["email_verified"])
        result["channel_simulated"] = bool(result["channel_simulated"])
        return result

    @staticmethod
    def _decode_channel_identity(
        result: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if result is None:
            return None
        result["simulated"] = bool(result["simulated"])
        result["channel"] = {
            "name": result["channel_name"],
            "adapter": result["adapter"],
            "simulated": result["simulated"],
        }
        return result

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


Repository = SQLiteRepository


def create_repository(database_path: str | Path | None) -> SQLiteRepository | None:
    """Cria e inicializa o adapter SQLite quando um caminho foi configurado.

    Sem caminho, retorna ``None`` para que o chamador preserve seu modo em
    memória explicitamente. Erros de abertura ou inicialização são propagados;
    não há fallback silencioso para outro armazenamento.
    """

    if database_path is None or not str(database_path).strip():
        return None
    repository = SQLiteRepository(str(database_path).strip())
    repository.initialize()
    return repository


__all__ = ["Repository", "SQLiteRepository", "create_repository"]
