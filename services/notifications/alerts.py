"""Pure alert domain for AuraFi (BE-008).

This module deliberately stops at a domain result.  It does not call a channel,
persist data, read market data, or execute a wallet operation.  Consumers inject
the policy, observation/event data, clock, identifier generator and
deduplication port.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4


DEFAULT_DISCLAIMER = (
    "Este alerta é apenas apoio à decisão. APY e risco são dados observados e "
    "variáveis, não constituem garantia de retorno. O AuraFi não executa "
    "transações, não custodia ativos e não indica que exista saldo ou alocação."
)


class _StrEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class AlertType(_StrEnum):
    APY_CHANGE = "apy_change"
    RISK_CHANGE = "risk_change"
    NEW_OPPORTUNITY = "new_opportunity"
    DATA_STALE = "data_stale"


class SuggestedAction(_StrEnum):
    VIEW_OPPORTUNITY = "view_opportunity"
    SIMULATE = "simulate"
    ASK_HUB = "ask_hub"
    NONE = "none"


class AlertStatus(_StrEnum):
    UNREAD = "unread"
    READ = "read"


class AlertResultStatus(_StrEnum):
    GENERATED = "generated"
    PENDING = "pending"
    NOT_ELIGIBLE = "not_eligible"
    DISABLED = "disabled"
    DEDUPLICATED = "deduplicated"
    DRY_RUN = "dry_run"


def _enum(value: Any, enum_type: type[_StrEnum], field_name: str) -> _StrEnum:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        allowed = ", ".join(item.value for item in enum_type)
        raise ValueError(f"{field_name} invalido; aceitos: {allowed}") from error


def _utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} deve ser datetime")
    if value.tzinfo is None:
        raise ValueError(f"{field_name} deve incluir timezone")
    return value.astimezone(timezone.utc)


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} nao pode ser vazio")
    return value.strip()


def _optional_float(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} deve ser numerico")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{field_name} deve ser finito")
    return result


@dataclass(frozen=True, slots=True)
class AlertDataSource:
    """Metadata needed to explain a market-backed alert."""

    source: str
    mode: str
    observed_at: datetime
    retrieved_at: datetime
    is_stale: bool
    read_only: bool = True
    freshness_note: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _text(self.source, "source"))
        object.__setattr__(self, "mode", _text(self.mode, "mode"))
        object.__setattr__(self, "observed_at", _utc(self.observed_at, "observed_at"))
        object.__setattr__(self, "retrieved_at", _utc(self.retrieved_at, "retrieved_at"))
        if not isinstance(self.is_stale, bool):
            raise TypeError("is_stale deve ser bool")
        if not isinstance(self.read_only, bool):
            raise TypeError("read_only deve ser bool")
        if not self.read_only:
            raise ValueError("AlertDataSource aceita somente fonte de leitura")
        if self.freshness_note is not None:
            object.__setattr__(self, "freshness_note", _text(self.freshness_note, "freshness_note"))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "source": self.source,
            "mode": self.mode,
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "retrieved_at": self.retrieved_at.isoformat().replace("+00:00", "Z"),
            "read_only": self.read_only,
            "is_stale": self.is_stale,
        }
        if self.freshness_note:
            result["freshness_note"] = self.freshness_note
        return result


DataSourceMetadata = AlertDataSource
DataSource = AlertDataSource


@dataclass(frozen=True, slots=True)
class AlertObservation:
    """A comparable market observation supplied by the caller."""

    opportunity_id: str
    data_source: AlertDataSource
    apy: float | None = None
    risk_level: str | None = None
    observation_id: str | None = None
    apy_value: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "opportunity_id", _text(self.opportunity_id, "opportunity_id"))
        object.__setattr__(self, "data_source", _coerce_data_source(self.data_source))
        apy = _optional_float(self.apy, "apy")
        apy_value = _optional_float(self.apy_value, "apy_value")
        if apy is not None and apy_value is not None and apy != apy_value:
            raise ValueError("apy e apy_value nao podem divergir")
        apy = apy if apy is not None else apy_value
        object.__setattr__(self, "apy", apy)
        object.__setattr__(self, "apy_value", apy)
        if self.risk_level is not None:
            object.__setattr__(self, "risk_level", _text(self.risk_level, "risk_level"))
        if self.observation_id is not None:
            object.__setattr__(self, "observation_id", _text(self.observation_id, "observation_id"))

    @classmethod
    def from_market(cls, opportunity: Any) -> "AlertObservation":
        """Adapt a market-data object without importing the market service."""

        metadata = getattr(opportunity, "data_source", None)
        if metadata is None and isinstance(opportunity, Mapping):
            metadata = opportunity.get("data_source")
        data_source = _coerce_data_source(metadata)
        values = opportunity
        apy_value = _value(values, "apy", "apy_value")
        if isinstance(apy_value, Mapping):
            apy_value = _value(apy_value, "value", "apy")
        risk_value = _value(values, "risk_level")
        if isinstance(risk_value, Mapping):
            risk_value = _value(risk_value, "level", "risk_level")
        return cls(
            opportunity_id=_value(values, "opportunity_id"),
            data_source=data_source,
            apy=apy_value,
            risk_level=risk_value,
            observation_id=_value(values, "observation_id", "market_observation_id"),
        )


@dataclass(frozen=True, slots=True)
class AlertEvent:
    """Event candidate evaluated by :class:`AlertService`."""

    type: AlertType
    current: AlertObservation
    previous: AlertObservation | None = None
    is_new: bool | None = None
    is_monitored: bool | None = None
    event_id: str | None = None
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "type", _enum(self.type, AlertType, "type"))
        if not isinstance(self.current, AlertObservation):
            raise TypeError("current deve ser AlertObservation")
        if self.previous is not None and not isinstance(self.previous, AlertObservation):
            raise TypeError("previous deve ser AlertObservation")
        for name in ("event_id", "correlation_id"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _text(value, name))
        for name in ("is_new", "is_monitored"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, bool):
                raise TypeError(f"{name} deve ser bool quando informado")

    @property
    def opportunity_id(self) -> str:
        return self.current.opportunity_id


@dataclass(frozen=True, slots=True)
class ApyChangeRule:
    """Explicit APY threshold; no threshold is ever supplied by this module."""

    threshold: float | None = None
    threshold_kind: str | None = None
    direction: str | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        threshold = _optional_float(self.threshold, "threshold")
        if threshold is not None and threshold < 0:
            raise ValueError("threshold nao pode ser negativo")
        object.__setattr__(self, "threshold", threshold)
        if self.threshold_kind is not None and self.threshold_kind not in {"absolute", "relative"}:
            raise ValueError("threshold_kind deve ser absolute ou relative")
        if self.direction is not None and self.direction not in {"increase", "decrease", "any"}:
            raise ValueError("direction deve ser increase, decrease ou any")
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled deve ser bool")

    @property
    def configured(self) -> bool:
        return self.enabled and self.threshold is not None and self.threshold_kind is not None and self.direction is not None


@dataclass(frozen=True, slots=True)
class ExplicitEventRule:
    """Rule for events whose condition is supplied as explicit event data."""

    enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled deve ser bool")


RiskChangeRule = ExplicitEventRule
NewOpportunityRule = ExplicitEventRule
DataStaleRule = ExplicitEventRule


@dataclass(frozen=True, slots=True)
class AlertPreferences:
    """Account-facing choices. ``None`` means not configured, not enabled."""

    enabled_types: frozenset[AlertType] | None = None
    suggested_actions: Mapping[AlertType, SuggestedAction] | None = None

    def __post_init__(self) -> None:
        if self.enabled_types is not None:
            normalized = frozenset(_enum(item, AlertType, "enabled_types") for item in self.enabled_types)
            object.__setattr__(self, "enabled_types", normalized)
        if self.suggested_actions is not None:
            normalized_actions = {
                _enum(key, AlertType, "suggested_actions"): _enum(value, SuggestedAction, "suggested_action")
                for key, value in self.suggested_actions.items()
            }
            object.__setattr__(self, "suggested_actions", normalized_actions)

    def decide(self, alert_type: AlertType) -> tuple[bool, SuggestedAction | None, str | None]:
        if self.enabled_types is None:
            return False, None, "PREFERENCES_NOT_CONFIGURED"
        if alert_type not in self.enabled_types:
            return False, None, "PREFERENCE_DISABLED"
        action = SuggestedAction.NONE
        if self.suggested_actions is not None and alert_type in self.suggested_actions:
            action = self.suggested_actions[alert_type]
        return True, action, None


@dataclass(frozen=True, slots=True)
class AlertPolicy:
    """Versioned, fail-closed policy for alert generation."""

    version: str
    preferences: AlertPreferences | None = None
    apy_change: ApyChangeRule | None = None
    risk_change: RiskChangeRule | None = None
    new_opportunity: NewOpportunityRule | None = None
    data_stale: DataStaleRule | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _text(self.version, "version"))
        for name in ("apy_change", "risk_change", "new_opportunity", "data_stale"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, (ApyChangeRule, ExplicitEventRule)):
                raise TypeError(f"{name} possui tipo de regra invalido")

    def rule_for(self, alert_type: AlertType) -> ApyChangeRule | ExplicitEventRule | None:
        return {
            AlertType.APY_CHANGE: self.apy_change,
            AlertType.RISK_CHANGE: self.risk_change,
            AlertType.NEW_OPPORTUNITY: self.new_opportunity,
            AlertType.DATA_STALE: self.data_stale,
        }[alert_type]


@dataclass(frozen=True, slots=True)
class Alert:
    """Domain alert. It is not a delivery command."""

    alert_id: str
    type: AlertType
    opportunity_id: str
    title: str
    message: str
    status: AlertStatus
    created_at: datetime
    observed_at: datetime
    data_source: AlertDataSource
    suggested_action: SuggestedAction
    disclaimer: str
    correlation_id: str
    policy_version: str
    deduplication_key: str
    dry_run: bool = False

    def __post_init__(self) -> None:
        for name in ("alert_id", "opportunity_id", "title", "message", "disclaimer", "correlation_id", "policy_version", "deduplication_key"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "type", _enum(self.type, AlertType, "type"))
        object.__setattr__(self, "status", _enum(self.status, AlertStatus, "status"))
        object.__setattr__(self, "suggested_action", _enum(self.suggested_action, SuggestedAction, "suggested_action"))
        object.__setattr__(self, "created_at", _utc(self.created_at, "created_at"))
        object.__setattr__(self, "observed_at", _utc(self.observed_at, "observed_at"))
        if not self.disclaimer.strip():
            raise ValueError("disclaimer nao pode ser vazio")
        if not self.dry_run and "retorno" not in self.disclaimer.lower():
            raise ValueError("disclaimer deve mencionar retorno")

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "type": self.type.value,
            "opportunity_id": self.opportunity_id,
            "title": self.title,
            "message": self.message,
            "status": self.status.value,
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "data_source": self.data_source.to_dict(),
            "suggested_action": self.suggested_action.value,
            "disclaimer": self.disclaimer,
            "correlation_id": self.correlation_id,
            "policy_version": self.policy_version,
            "deduplication_key": self.deduplication_key,
            "dry_run": self.dry_run,
        }

    def mark_read(self) -> "Alert":
        """Return a read copy; persistence and authorization remain external."""

        return replace(self, status=AlertStatus.READ)


@dataclass(frozen=True, slots=True)
class AlertResult:
    status: AlertResultStatus
    correlation_id: str
    reason_code: str | None = None
    reason: str | None = None
    alert: Alert | None = None
    deduplication_key: str | None = None
    policy_version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _enum(self.status, AlertResultStatus, "status"))
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, "correlation_id"))
        if self.reason_code is None and self.status is not AlertResultStatus.GENERATED and self.status is not AlertResultStatus.DRY_RUN:
            raise ValueError("resultado nao gerado exige reason_code")

    @property
    def generated(self) -> bool:
        return self.alert is not None and self.status in {AlertResultStatus.GENERATED, AlertResultStatus.DRY_RUN}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "correlation_id": self.correlation_id,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "alert": self.alert.to_dict() if self.alert else None,
            "deduplication_key": self.deduplication_key,
            "policy_version": self.policy_version,
        }


class DeduplicationPort(Protocol):
    def claim(self, key: str) -> bool:
        """Atomically claim a key; return False when already claimed."""


class ClockPort(Protocol):
    def now(self) -> datetime:
        ...


class InMemoryDeduplicationStore:
    """Small deterministic store for tests and a process-local adapter."""

    def __init__(self) -> None:
        self._keys: set[str] = set()

    def claim(self, key: str) -> bool:
        if key in self._keys:
            return False
        self._keys.add(key)
        return True

    def __contains__(self, key: str) -> bool:
        return key in self._keys


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class AlertService:
    """Evaluate alert candidates and return domain events only."""

    def __init__(
        self,
        *,
        disclaimer: str = DEFAULT_DISCLAIMER,
        deduplication: DeduplicationPort | None = None,
        clock: ClockPort | Callable[[], datetime] | None = None,
        id_generator: Callable[[], str] | None = None,
    ) -> None:
        if not disclaimer.strip() or "retorno" not in disclaimer.lower():
            raise ValueError("disclaimer deve ser nao vazio e mencionar retorno")
        self._disclaimer = disclaimer
        self._deduplication = deduplication or InMemoryDeduplicationStore()
        self._clock = clock or SystemClock()
        self._id_generator = id_generator or (lambda: str(uuid4()))

    def evaluate(
        self,
        account_id: str,
        event: AlertEvent,
        policy: AlertPolicy | None,
        *,
        dry_run: bool = False,
        now: datetime | None = None,
    ) -> AlertResult:
        account_id = _text(account_id, "account_id")
        correlation_id = event.correlation_id or self._new_id()
        if policy is None:
            return self._result(AlertResultStatus.PENDING, correlation_id, "POLICY_REQUIRED", "Uma AlertPolicy versionada e necessaria.")

        rule = policy.rule_for(event.type)
        if rule is None:
            return self._result(AlertResultStatus.PENDING, correlation_id, "RULE_NOT_CONFIGURED", f"A regra de {event.type.value} nao foi configurada.", policy)
        if not rule.enabled:
            return self._result(AlertResultStatus.DISABLED, correlation_id, "RULE_DISABLED", f"A regra de {event.type.value} esta desabilitada.", policy)
        if isinstance(rule, ApyChangeRule) and not rule.configured:
            return self._result(AlertResultStatus.PENDING, correlation_id, "THRESHOLD_NOT_CONFIGURED", "APY change exige threshold, tipo e direcao explicitos.", policy)

        preferences = policy.preferences
        if preferences is None:
            return self._result(AlertResultStatus.PENDING, correlation_id, "PREFERENCES_NOT_CONFIGURED", "Preferencias de alertas nao configuradas.", policy)
        enabled, action, preference_reason = preferences.decide(event.type)
        if not enabled:
            status = AlertResultStatus.PENDING if preference_reason == "PREFERENCES_NOT_CONFIGURED" else AlertResultStatus.DISABLED
            return self._result(status, correlation_id, preference_reason or "PREFERENCES_NOT_CONFIGURED", "Preferencias nao permitem emitir este alerta.", policy)

        eligible, reason_code, reason = self._condition(event, rule)
        if not eligible:
            return self._result(AlertResultStatus.NOT_ELIGIBLE, correlation_id, reason_code, reason, policy)

        key = self._deduplication_key(account_id, event, policy.version)
        if not dry_run and not self._deduplication.claim(key):
            return self._result(AlertResultStatus.DEDUPLICATED, correlation_id, "DUPLICATE_EVENT", "O mesmo evento ja foi considerado para esta conta.", policy, key)

        created_at = _utc(now, "now") if now is not None else _utc(self._clock_now(), "clock.now()")
        alert = self._build_alert(event, policy.version, action or SuggestedAction.NONE, correlation_id, key, created_at, dry_run)
        status = AlertResultStatus.DRY_RUN if dry_run else AlertResultStatus.GENERATED
        return AlertResult(status=status, correlation_id=correlation_id, alert=alert, deduplication_key=key, policy_version=policy.version)

    process = evaluate
    generate = evaluate

    def evaluate_apy_change(self, account_id: str, previous: AlertObservation, current: AlertObservation, policy: AlertPolicy, **kwargs: Any) -> AlertResult:
        return self.evaluate(account_id, AlertEvent(AlertType.APY_CHANGE, current, previous, correlation_id=kwargs.pop("correlation_id", None)), policy, **kwargs)

    def evaluate_risk_change(self, account_id: str, previous: AlertObservation, current: AlertObservation, policy: AlertPolicy, **kwargs: Any) -> AlertResult:
        return self.evaluate(account_id, AlertEvent(AlertType.RISK_CHANGE, current, previous, correlation_id=kwargs.pop("correlation_id", None)), policy, **kwargs)

    def evaluate_new_opportunity(self, account_id: str, current: AlertObservation, policy: AlertPolicy, *, is_monitored: bool | None = None, is_new: bool | None = None, **kwargs: Any) -> AlertResult:
        return self.evaluate(account_id, AlertEvent(AlertType.NEW_OPPORTUNITY, current, is_new=is_new, is_monitored=is_monitored, correlation_id=kwargs.pop("correlation_id", None)), policy, **kwargs)

    def evaluate_data_stale(self, account_id: str, current: AlertObservation, policy: AlertPolicy, **kwargs: Any) -> AlertResult:
        return self.evaluate(account_id, AlertEvent(AlertType.DATA_STALE, current, correlation_id=kwargs.pop("correlation_id", None)), policy, **kwargs)

    def _condition(self, event: AlertEvent, rule: ApyChangeRule | ExplicitEventRule) -> tuple[bool, str, str]:
        current = event.current
        previous = event.previous
        if event.type in {AlertType.APY_CHANGE, AlertType.RISK_CHANGE}:
            if previous is None:
                return False, "PREVIOUS_OBSERVATION_REQUIRED", "A mudanca exige observacao anterior."
            if previous.opportunity_id != current.opportunity_id or previous.data_source.source != current.data_source.source:
                return False, "OBSERVATIONS_NOT_COMPARABLE", "As observacoes devem ser da mesma oportunidade e fonte."

        if event.type is AlertType.APY_CHANGE:
            assert isinstance(rule, ApyChangeRule)
            if current.apy is None or previous is None or previous.apy is None:
                return False, "APY_OBSERVATION_REQUIRED", "As duas observacoes precisam conter APY valido."
            change = current.apy - previous.apy
            magnitude = abs(change) if rule.threshold_kind == "absolute" else abs(change) / abs(previous.apy) if previous.apy != 0 else None
            if magnitude is None:
                return False, "APY_RELATIVE_CHANGE_UNDEFINED", "Nao e possivel calcular mudanca relativa sobre APY zero."
            direction_ok = rule.direction == "any" or (rule.direction == "increase" and change > 0) or (rule.direction == "decrease" and change < 0)
            if not direction_ok or magnitude < rule.threshold:
                return False, "THRESHOLD_NOT_REACHED", "A variacao observada nao atingiu o threshold configurado."
            return True, "APY_CHANGE_DETECTED", "A variacao de APY atingiu o threshold configurado."

        if event.type is AlertType.RISK_CHANGE:
            assert isinstance(rule, ExplicitEventRule)
            if not current.risk_level or not previous or not previous.risk_level or {current.risk_level, previous.risk_level} & {"unknown", ""}:
                return False, "RISK_LEVEL_REQUIRED", "A mudanca de risco exige dois niveis explicitos e conhecidos."
            if current.risk_level == previous.risk_level:
                return False, "RISK_CHANGE_NOT_DETECTED", "O nivel de risco nao mudou."
            return True, "RISK_CHANGE_DETECTED", "Foi detectada transicao explicita de nivel de risco."

        if event.type is AlertType.NEW_OPPORTUNITY:
            if event.is_new is not True or event.is_monitored is not True:
                return False, "NEW_OPPORTUNITY_NOT_CONFIRMED", "Novidade e monitoramento precisam ser informados explicitamente."
            return True, "NEW_OPPORTUNITY_DETECTED", "A oportunidade nova pertence ao conjunto monitorado."

        if current.data_source.is_stale is not True:
            return False, "DATA_NOT_STALE", "A fonte nao marcou o snapshot como stale."
        return True, "DATA_STALE_DETECTED", "A fonte marcou explicitamente o snapshot como stale."

    def _build_alert(self, event: AlertEvent, policy_version: str, action: SuggestedAction, correlation_id: str, key: str, created_at: datetime, dry_run: bool) -> Alert:
        titles = {
            AlertType.APY_CHANGE: "Mudanca de APY observada",
            AlertType.RISK_CHANGE: "Mudanca de risco observada",
            AlertType.NEW_OPPORTUNITY: "Nova oportunidade observada",
            AlertType.DATA_STALE: "Dado de mercado desatualizado",
        }
        messages = {
            AlertType.APY_CHANGE: "O APY observado desta oportunidade mudou. Revise os dados antes de decidir.",
            AlertType.RISK_CHANGE: "O nivel de risco observado desta oportunidade mudou. Revise as dimensoes de risco.",
            AlertType.NEW_OPPORTUNITY: "Uma oportunidade nova apareceu no conjunto monitorado. Avalie as informacoes disponiveis.",
            AlertType.DATA_STALE: "O dado de mercado esta marcado como stale e pode estar desatualizado.",
        }
        return Alert(
            alert_id=self._new_id(),
            type=event.type,
            opportunity_id=event.opportunity_id,
            title=titles[event.type],
            message=f"{messages[event.type]} {self._disclaimer}",
            status=AlertStatus.UNREAD,
            created_at=created_at,
            observed_at=event.current.data_source.observed_at,
            data_source=event.current.data_source,
            suggested_action=action,
            disclaimer=self._disclaimer,
            correlation_id=correlation_id,
            policy_version=policy_version,
            deduplication_key=key,
            dry_run=dry_run,
        )

    def _result(self, status: AlertResultStatus, correlation_id: str, reason_code: str, reason: str, policy: AlertPolicy | None = None, key: str | None = None) -> AlertResult:
        return AlertResult(status=status, correlation_id=correlation_id, reason_code=reason_code, reason=reason, deduplication_key=key, policy_version=policy.version if policy else None)

    def _clock_now(self) -> datetime:
        return self._clock.now() if hasattr(self._clock, "now") else self._clock()  # type: ignore[operator]

    def _new_id(self) -> str:
        return _text(str(self._id_generator()), "generated_id")

    @staticmethod
    def _deduplication_key(account_id: str, event: AlertEvent, policy_version: str) -> str:
        current = event.current
        previous = event.previous
        observations = {
            "event_id": event.event_id,
            "current_id": current.observation_id,
            "current_observed_at": current.data_source.observed_at.isoformat(),
            "current_source": current.data_source.source,
            "current_apy": current.apy,
            "current_risk": current.risk_level,
            "previous_id": previous.observation_id if previous else None,
            "previous_observed_at": previous.data_source.observed_at.isoformat() if previous else None,
            "previous_apy": previous.apy if previous else None,
            "previous_risk": previous.risk_level if previous else None,
            "is_new": event.is_new,
        }
        digest = sha256(json.dumps(observations, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]
        return f"{account_id}:{event.opportunity_id}:{event.type.value}:{policy_version}:{digest}"


def _value(values: Any, *names: str) -> Any:
    for name in names:
        if isinstance(values, Mapping) and name in values:
            return values[name]
        if hasattr(values, name):
            return getattr(values, name)
    return None


def _coerce_data_source(value: Any) -> AlertDataSource:
    if isinstance(value, AlertDataSource):
        return value
    if isinstance(value, Mapping):
        source = value.get("source")
        mode = value.get("mode")
        observed_at = value.get("observed_at")
        retrieved_at = value.get("retrieved_at")
        is_stale = value.get("is_stale")
        return AlertDataSource(source, mode, _parse_datetime(observed_at), _parse_datetime(retrieved_at), is_stale, value.get("read_only", True), value.get("freshness_note"))
    if value is None:
        raise ValueError("data_source e obrigatorio")
    return AlertDataSource(
        source=getattr(value, "source"),
        mode=getattr(value, "mode"),
        observed_at=_parse_datetime(getattr(value, "observed_at")),
        retrieved_at=_parse_datetime(getattr(value, "retrieved_at")),
        is_stale=getattr(value, "is_stale"),
        read_only=getattr(value, "read_only", True),
        freshness_note=getattr(value, "freshness_note", None),
    )


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _utc(value, "timestamp")
    if isinstance(value, str):
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")), "timestamp")
    raise TypeError("timestamp deve ser datetime ou ISO-8601")


__all__ = [
    "DEFAULT_DISCLAIMER",
    "Alert",
    "AlertDataSource",
    "AlertEvent",
    "AlertObservation",
    "AlertPolicy",
    "AlertPreferences",
    "AlertResult",
    "AlertResultStatus",
    "AlertService",
    "AlertStatus",
    "AlertType",
    "ApyChangeRule",
    "ClockPort",
    "DataSourceMetadata",
    "DataSource",
    "DataStaleRule",
    "DeduplicationPort",
    "ExplicitEventRule",
    "InMemoryDeduplicationStore",
    "NewOpportunityRule",
    "RiskChangeRule",
    "SuggestedAction",
    "SystemClock",
]
