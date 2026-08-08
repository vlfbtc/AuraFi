"""Adapter somente leitura para dados de mercado da DeFiLlama.

O módulo deliberadamente depende de portas pequenas para HTTP, cache, relógio
e fallback. Assim, o caminho padrão de testes não precisa de rede, Redis ou
qualquer outro serviço externo.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import json
from numbers import Real
from typing import Any, Callable, Literal, Mapping, Protocol, Sequence
from urllib.parse import urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID


ReadMode = Literal["auto", "live", "cache", "test", "fallback"]
JsonPayload = Mapping[str, Any] | Sequence[Mapping[str, Any]]


class MarketDataError(RuntimeError):
    """Erro controlado de configuração, leitura ou normalização."""


class HttpGetPort(Protocol):
    """Porta mínima usada pelo adapter; somente GET é exposto."""

    def get(self, url: str, *, timeout_seconds: float) -> JsonPayload:
        ...


class ClockPort(Protocol):
    def now(self) -> datetime:
        ...


@dataclass(frozen=True)
class DataSourceMetadata:
    source: Literal["defillama"]
    mode: Literal["live", "cache", "test", "fallback"]
    observed_at: datetime
    retrieved_at: datetime
    read_only: Literal[True] = True
    is_stale: bool = False
    cache_expires_at: datetime | None = None
    freshness_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "source": self.source,
            "mode": self.mode,
            "observed_at": _isoformat(self.observed_at),
            "retrieved_at": _isoformat(self.retrieved_at),
            "read_only": self.read_only,
            "is_stale": self.is_stale,
        }
        if self.cache_expires_at is not None:
            result["cache_expires_at"] = _isoformat(self.cache_expires_at)
        if self.freshness_note:
            result["freshness_note"] = self.freshness_note
        return result


@dataclass(frozen=True)
class NormalizedOpportunity:
    """Modelo de mercado canônico, limitado aos campos do contrato público."""

    opportunity_id: str
    protocol: str
    pool: str
    asset: str
    blockchain: str
    apy_value: float
    apy_observed_at: datetime
    tvl_value: float
    tvl_currency: str
    tvl_observed_at: datetime
    liquidity_level: Literal["low", "medium", "high", "unknown"]
    liquidity_observed_at: datetime
    data_source: DataSourceMetadata
    risk_score: float | None = None
    risk_level: Literal["low", "medium", "high", "unknown"] = "unknown"
    risk_dimensions: tuple[str, ...] = ()
    liquidity_value: float | None = None
    liquidity_currency: str | None = None
    audit_status: Literal[
        "audited", "partially_audited", "not_verified", "unknown"
    ] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serializa somente nomes e valores previstos em ``Opportunity``."""
        liquidity: dict[str, Any] = {
            "level": self.liquidity_level,
            "observed_at": _isoformat(self.liquidity_observed_at),
        }
        if self.liquidity_value is not None:
            liquidity["value"] = self.liquidity_value
        if self.liquidity_currency is not None:
            liquidity["currency"] = self.liquidity_currency

        risk: dict[str, Any] = {
            "score": self.risk_score,
            "level": self.risk_level,
            "dimensions": list(self.risk_dimensions),
        }
        result: dict[str, Any] = {
            "opportunity_id": self.opportunity_id,
            "protocol": self.protocol,
            "pool": self.pool,
            "asset": self.asset,
            "blockchain": self.blockchain,
            "apy": {
                "value": self.apy_value,
                "unit": "percent_annualized",
                "observed_at": _isoformat(self.apy_observed_at),
            },
            "tvl": {
                "value": self.tvl_value,
                "currency": self.tvl_currency,
                "observed_at": _isoformat(self.tvl_observed_at),
            },
            "liquidity": liquidity,
            "risk": risk,
            "data_source": self.data_source.to_dict(),
            "disclaimer": (
                "Dados informativos de mercado; não constituem recomendação "
                "personalizada nem execução de transação."
            ),
        }
        if self.audit_status is not None:
            result["audit_status"] = self.audit_status
        return result


@dataclass(frozen=True)
class MarketDataSnapshot:
    """Resposta normalizada do adapter para consumo por outros serviços."""

    items: tuple[NormalizedOpportunity, ...]
    data_source: DataSourceMetadata

    def to_dict(self) -> dict[str, Any]:
        return {"items": [item.to_dict() for item in self.items]}


@dataclass(frozen=True)
class CacheEntry:
    """Valor de cache com validade explícita para permitir servir stale."""

    value: MarketDataSnapshot
    expires_at: datetime


class CachePort(Protocol):
    def get(self, key: str) -> CacheEntry | None:
        ...

    def set(self, key: str, value: CacheEntry) -> None:
        ...


class FallbackPort(Protocol):
    def get(self) -> JsonPayload:
        ...


@dataclass(frozen=True)
class DeFiLlamaSchema:
    """Mapeamento externo configurável; a versão real do schema é [LACUNA]."""

    items_keys: tuple[str, ...] = ("data",)
    fields: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: {
            "opportunity_id": ("pool", "id"),
            "protocol": ("project", "protocol"),
            "pool": ("poolMeta", "pool_name", "name", "pool"),
            "asset": ("symbol", "asset"),
            "blockchain": ("chain", "blockchain"),
            "apy": ("apy", "apy.value"),
            "tvl": ("tvlUsd", "tvl", "tvl.value"),
            "tvl_currency": ("tvl_currency", "tvl.currency"),
            "liquidity_level": ("liquidity_level", "liquidity.level"),
            "liquidity_value": ("liquidity_value", "liquidityUsd", "liquidity.value"),
            "liquidity_currency": ("liquidity_currency", "liquidity.currency"),
            "risk_score": ("risk_score", "riskScore", "risk.score"),
            "risk_level": ("risk_level", "riskLevel", "risk.level"),
            "risk_dimensions": ("risk_dimensions", "riskDimensions", "risk.dimensions"),
            "audit_status": ("audit_status", "auditStatus"),
            "observed_at": (
                "observed_at",
                "timestamp",
                "lastUpdated",
                "updatedAt",
                "data_source.observed_at",
            ),
        }
    )


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise MarketDataError("Redirecionamentos da DeFiLlama não são permitidos")


class UrllibHttpClient:
    """Implementação padrão da porta HTTP, restrita a requisições GET."""

    def __init__(self, *, max_response_bytes: int = 16_777_216) -> None:
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes deve ser maior que zero")
        self.max_response_bytes = max_response_bytes
        self._open = build_opener(_RejectRedirects()).open

    def get(self, url: str, *, timeout_seconds: float) -> JsonPayload:
        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "AuraFi/1.0"},
            method="GET",
        )
        with self._open(request, timeout=timeout_seconds) as response:  # noqa: S310
            content_type = response.headers.get_content_type()
            if content_type != "application/json":
                raise MarketDataError("A fonte externa retornou um tipo de conteúdo inválido")
            raw = response.read(self.max_response_bytes + 1)
            if len(raw) > self.max_response_bytes:
                raise MarketDataError("A resposta externa excedeu o limite permitido")
            payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, (Mapping, list, tuple)):
            raise MarketDataError("A resposta externa não é um objeto/lista JSON")
        return payload


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class InMemoryCache:
    """Cache determinístico para desenvolvimento e testes unitários."""

    def __init__(self) -> None:
        self._values: dict[str, CacheEntry] = {}

    def get(self, key: str) -> CacheEntry | None:
        return self._values.get(key)

    def set(self, key: str, value: CacheEntry) -> None:
        self._values[key] = value


class SyntheticFallback:
    """Fixture sintética, sem representar protocolo ou usuário real."""

    def get(self) -> JsonPayload:
        return {
            "data": [
                {
                    "pool": "fixture-pool-a",
                    "project": "TestLend",
                    "poolMeta": "Stable Pool A",
                    "symbol": "USDC",
                    "chain": "Ethereum",
                    "apy": 5.2,
                    "tvlUsd": 1_250_000,
                    "liquidity_level": "high",
                    "risk_level": "unknown",
                    "risk_dimensions": ["data_quality"],
                    "observed_at": "2026-08-02T10:00:00+00:00",
                }
            ]
        }


class DeFiLlamaAdapter:
    """Leitor de oportunidades DeFiLlama com cache e degradação controlada.

    ``base_url`` e ``endpoint`` são obrigatórios para o modo live e ficam
    deliberadamente sem valor padrão: a decisão de endpoint externo permanece
    [LACUNA] configurável. A classe não possui operações de mutação externa.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        endpoint: str | None = None,
        http_client: HttpGetPort | None = None,
        cache: CachePort | None = None,
        fallback: FallbackPort | Callable[[], JsonPayload] | None = None,
        clock: ClockPort | None = None,
        schema: DeFiLlamaSchema | None = None,
        ttl_seconds: float = 300.0,
        timeout_seconds: float = 5.0,
        cache_key: str = "defillama:market-data",
        fx_base_url: str | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds deve ser maior que zero")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds deve ser maior que zero")
        self.base_url = base_url
        self.endpoint = endpoint
        self.http_client = http_client or UrllibHttpClient()
        self.cache = cache or InMemoryCache()
        self.fallback = fallback or SyntheticFallback()
        self.clock = clock or SystemClock()
        self.schema = schema or DeFiLlamaSchema()
        self.ttl_seconds = ttl_seconds
        self.timeout_seconds = timeout_seconds
        self.cache_key = cache_key
        from .enrichment import MarketDetailEnricher

        self.detail_enricher = MarketDetailEnricher(
            defillama_base_url=base_url,
            fx_base_url=fx_base_url,
            http_client=self.http_client,
            clock=self.clock,
            timeout_seconds=timeout_seconds,
        )

    def enrich_opportunity(
        self, opportunity: NormalizedOpportunity, *, mode: ReadMode = "auto"
    ) -> dict[str, Any]:
        """Adiciona histórico e apresentação monetária ao detalhe, fail-soft."""
        self.detail_enricher.http_client = self.http_client
        self.detail_enricher.defillama_base_url = self.base_url
        return self.detail_enricher.enrich(
            opportunity_id=opportunity.opportunity_id,
            tvl_usd=opportunity.tvl_value,
            mode=mode,
        )

    def currency_displays(
        self,
        opportunities: Sequence[NormalizedOpportunity],
        *,
        mode: ReadMode = "auto",
    ) -> tuple[Mapping[str, Any], ...]:
        """Converte a listagem com uma única leitura/cache PTAX compartilhada."""
        self.detail_enricher.http_client = self.http_client
        return self.detail_enricher.currency_displays(
            [item.tvl_value for item in opportunities], mode=mode
        )

    def read(self, *, mode: ReadMode = "auto") -> MarketDataSnapshot:
        """Lê dados sem mutar a fonte; ``mode`` facilita testes determinísticos."""
        if mode not in {"auto", "live", "cache", "test", "fallback"}:
            raise ValueError(f"Modo de leitura inválido: {mode}")
        if mode in {"test", "fallback"}:
            return self._read_fallback(mode)

        live_error: Exception | None = None
        if mode in {"auto", "live"} and self._request_url() is not None:
            try:
                return self._read_live()
            except Exception as error:
                live_error = error

        cached = self._read_cache()
        if cached is not None:
            if live_error is None:
                return cached
            note = (
                "Fonte DeFiLlama indisponível; servindo cache "
                + ("stale." if cached.data_source.is_stale else "válido.")
            )
            return self._with_metadata(
                cached,
                replace(cached.data_source, freshness_note=note),
            )

        reason = "Fonte DeFiLlama não configurada ou indisponível"
        if live_error is not None:
            reason += f": {type(live_error).__name__}"
        return self._read_fallback("fallback", reason)

    def read_opportunities(self, *, mode: ReadMode = "auto") -> MarketDataSnapshot:
        """Alias semântico para consumidores que trabalham com oportunidades."""
        return self.read(mode=mode)

    def get_opportunities(self, *, mode: ReadMode = "auto") -> MarketDataSnapshot:
        return self.read(mode=mode)

    def read_for_detail(self, *, mode: ReadMode = "auto") -> MarketDataSnapshot:
        """Reutiliza snapshot live válido antes de reler a coleção completa.

        Somente entradas gravadas por ``_read_live`` chegam ao cache. Fixtures
        ``test``/``fallback`` nunca são persistidas e, portanto, nunca são
        promovidas por este atalho.
        """
        if mode in {"auto", "live"}:
            cached = self._read_cache()
            if cached is not None and not cached.data_source.is_stale:
                return cached
        return self.read(mode=mode)

    def _read_live(self) -> MarketDataSnapshot:
        url = self._request_url()
        if url is None:
            raise MarketDataError("base_url e endpoint são necessários para live")
        retrieved_at = _ensure_utc(self.clock.now())
        payload = self.http_client.get(url, timeout_seconds=self.timeout_seconds)
        snapshot = self._normalize(payload, mode="live", retrieved_at=retrieved_at)
        expires_at = retrieved_at + timedelta(seconds=self.ttl_seconds)
        live_source = replace(snapshot.data_source, cache_expires_at=expires_at)
        snapshot = self._with_metadata(snapshot, live_source)
        try:
            self.cache.set(self.cache_key, CacheEntry(snapshot, expires_at))
        except Exception:
            pass
        return snapshot

    def _read_cache(self) -> MarketDataSnapshot | None:
        try:
            entry = self.cache.get(self.cache_key)
        except Exception:
            return None
        if entry is None or not isinstance(entry.value, MarketDataSnapshot):
            return None
        now = _ensure_utc(self.clock.now())
        stale = now >= _ensure_utc(entry.expires_at)
        note = "Cache válido dentro do TTL de 300 segundos."
        if stale:
            note = "Cache stale servido após indisponibilidade da fonte."
        metadata = replace(
            entry.value.data_source,
            mode="cache",
            cache_expires_at=_ensure_utc(entry.expires_at),
            is_stale=stale,
            freshness_note=note,
        )
        return self._with_metadata(entry.value, metadata)

    def _read_fallback(self, mode: Literal["test", "fallback"], reason: str = "") -> MarketDataSnapshot:
        retrieved_at = _ensure_utc(self.clock.now())
        try:
            payload = self.fallback.get() if hasattr(self.fallback, "get") else self.fallback()
            note = "Fixture sintética de teste; não representa dados frescos."
            if mode == "fallback":
                note = "Fallback sintético de desenvolvimento/teste; não representa dados frescos."
            if reason:
                note += f" Motivo: {reason}."
            return self._normalize(
                payload,
                mode=mode,
                retrieved_at=retrieved_at,
                forced_stale=True,
                freshness_note=note,
            )
        except Exception as error:
            raise MarketDataError("Fallback sintético indisponível") from error

    def _normalize(
        self,
        payload: JsonPayload,
        *,
        mode: Literal["live", "test", "fallback"],
        retrieved_at: datetime,
        forced_stale: bool = False,
        freshness_note: str | None = None,
    ) -> MarketDataSnapshot:
        items = _items_from_payload(payload, self.schema)
        if not items:
            raise MarketDataError("A resposta da DeFiLlama não contém oportunidades")
        observed_at = _observed_at_from_payload(payload, items, self.schema, retrieved_at)
        if observed_at == retrieved_at and not freshness_note:
            freshness_note = (
                "A fonte não informou o momento da observação; "
                "o momento de recuperação foi usado como referência."
            )
        metadata = DataSourceMetadata(
            source="defillama",
            mode=mode,
            observed_at=observed_at,
            retrieved_at=retrieved_at,
            is_stale=forced_stale,
            freshness_note=freshness_note,
        )
        normalized = tuple(
            _normalize_item(item, metadata, self.schema) for item in items
        )
        return MarketDataSnapshot(normalized, metadata)

    def _request_url(self) -> str | None:
        if not self.endpoint:
            return None
        if self.endpoint.startswith(("http://", "https://")):
            return self.endpoint
        if not self.base_url:
            return None
        return urljoin(self.base_url.rstrip("/") + "/", self.endpoint.lstrip("/"))

    @staticmethod
    def _with_metadata(
        snapshot: MarketDataSnapshot, metadata: DataSourceMetadata
    ) -> MarketDataSnapshot:
        items = tuple(replace(item, data_source=metadata) for item in snapshot.items)
        return MarketDataSnapshot(items, metadata)


def _items_from_payload(payload: JsonPayload, schema: DeFiLlamaSchema) -> list[Mapping[str, Any]]:
    if isinstance(payload, (list, tuple)):
        value: Any = payload
    elif isinstance(payload, Mapping):
        value = None
        for key in schema.items_keys:
            if key in payload:
                value = payload[key]
                break
        if value is None:
            value = [payload]
    else:
        raise MarketDataError("Payload externo inválido")
    if not isinstance(value, (list, tuple)):
        raise MarketDataError("A coleção de oportunidades do payload é inválida")
    if not all(isinstance(item, Mapping) for item in value):
        raise MarketDataError("Cada oportunidade externa deve ser um objeto")
    return list(value)


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except (ValueError, AttributeError):
        return False
    return True


def _normalize_item(
    item: Mapping[str, Any], metadata: DataSourceMetadata, schema: DeFiLlamaSchema
) -> NormalizedOpportunity:
    opportunity_id = _required_text(_find(item, schema, "opportunity_id"), "opportunity_id")
    protocol = _required_text(_find(item, schema, "protocol"), "protocol")
    pool_value = _find(item, schema, "pool")
    if isinstance(pool_value, Mapping):
        pool_value = pool_value.get("name") or pool_value.get("pool")
    asset = _required_text(_find(item, schema, "asset"), "asset")
    blockchain = _required_text(_find(item, schema, "blockchain"), "blockchain")
    pool = _required_text(pool_value or f"{asset} pool", "pool")
    if pool == opportunity_id or _is_uuid(pool):
        pool = f"{asset} pool"
    apy_value = _non_negative(_find(item, schema, "apy"), "apy")
    tvl_value = _non_negative(_find(item, schema, "tvl"), "tvl")

    liquidity_level = _enum_or_unknown(
        _find(item, schema, "liquidity_level"), {"low", "medium", "high", "unknown"}
    )
    risk_level = _enum_or_unknown(
        _find(item, schema, "risk_level"), {"low", "medium", "high", "unknown"}
    )
    risk_score = _optional_non_negative(_find(item, schema, "risk_score"), "risk_score")
    if risk_score is not None and risk_score > 100:
        raise MarketDataError("risk_score deve estar entre 0 e 100")
    dimensions = _dimensions(_find(item, schema, "risk_dimensions"))
    audit_status = _optional_enum(
        _find(item, schema, "audit_status"),
        {"audited", "partially_audited", "not_verified", "unknown"},
    )
    liquidity_value = _optional_non_negative(
        _find(item, schema, "liquidity_value"), "liquidity_value"
    )
    liquidity_currency = _optional_text(_find(item, schema, "liquidity_currency"))
    tvl_currency = _optional_text(_find(item, schema, "tvl_currency"))
    if tvl_currency is None and "tvlUsd" in schema.fields.get("tvl", ()):
        tvl_currency = "USD"
    if tvl_currency is None:
        raise MarketDataError("Campo obrigatório ausente ou inválido: tvl_currency")
    return NormalizedOpportunity(
        opportunity_id=opportunity_id,
        protocol=protocol,
        pool=pool,
        asset=asset,
        blockchain=blockchain,
        apy_value=apy_value,
        apy_observed_at=metadata.observed_at,
        tvl_value=tvl_value,
        tvl_currency=tvl_currency,
        tvl_observed_at=metadata.observed_at,
        liquidity_level=liquidity_level,  # type: ignore[arg-type]
        liquidity_observed_at=metadata.observed_at,
        data_source=metadata,
        risk_score=risk_score,
        risk_level=risk_level,  # type: ignore[arg-type]
        risk_dimensions=dimensions,
        liquidity_value=liquidity_value,
        liquidity_currency=liquidity_currency,
        audit_status=audit_status,  # type: ignore[arg-type]
    )


def _find(item: Mapping[str, Any], schema: DeFiLlamaSchema, name: str) -> Any:
    for alias in schema.fields.get(name, ()):
        current: Any = item
        for part in alias.split("."):
            if not isinstance(current, Mapping) or part not in current:
                current = None
                break
            current = current[part]
        if current is not None:
            return current
    return None


def _observed_at_from_payload(
    payload: JsonPayload,
    items: Sequence[Mapping[str, Any]],
    schema: DeFiLlamaSchema,
    fallback: datetime,
) -> datetime:
    if isinstance(payload, Mapping):
        value = _find(payload, schema, "observed_at")
        if value is not None:
            return _parse_datetime(value)
    for item in items:
        value = _find(item, schema, "observed_at")
        if value is not None:
            return _parse_datetime(value)
    return fallback


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarketDataError(f"Campo obrigatório ausente ou inválido: {name}")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _non_negative(value: Any, name: str) -> float:
    result = _optional_non_negative(value, name)
    if result is None:
        raise MarketDataError(f"Campo obrigatório ausente ou inválido: {name}")
    return result


def _optional_non_negative(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise MarketDataError(f"Campo numérico inválido: {name}")
    result = float(value)
    if result < 0:
        raise MarketDataError(f"Campo não pode ser negativo: {name}")
    return result


def _enum_or_unknown(value: Any, allowed: set[str]) -> str:
    return value if isinstance(value, str) and value in allowed else "unknown"


def _optional_enum(value: Any, allowed: set[str]) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) and value in allowed else "unknown"


def _dimensions(value: Any) -> tuple[str, ...]:
    allowed = {
        "smart_contract",
        "liquidity",
        "volatility",
        "underlying_asset",
        "counterparty",
        "data_quality",
    }
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    if not isinstance(value, (list, tuple, set)):
        return ()
    return tuple(part for part in value if isinstance(part, str) and part in allowed)


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if isinstance(value, Real) and not isinstance(value, bool):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    if isinstance(value, str):
        normalized = value.strip().replace("Z", "+00:00")
        try:
            return _ensure_utc(datetime.fromisoformat(normalized))
        except ValueError as error:
            raise MarketDataError("Timestamp externo inválido") from error
    raise MarketDataError("Timestamp externo inválido")


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _isoformat(value: datetime) -> str:
    return _ensure_utc(value).isoformat().replace("+00:00", "Z")
