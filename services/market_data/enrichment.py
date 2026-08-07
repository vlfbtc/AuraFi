"""Enriquecimento read-only de detalhes de mercado com fontes primárias.

A série histórica vem do chart por pool da DeFiLlama. A conversão USD/BRL
usa a PTAX publicada pelo Banco Central do Brasil. Falhas nunca geram números
sintéticos: o chamador recebe estado ``unavailable`` ou cache identificado.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from numbers import Real
from threading import RLock
from typing import Any, Literal, Mapping, Sequence
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from .defillama import ClockPort, HttpGetPort, JsonPayload, MarketDataError, SystemClock


EnrichmentMode = Literal["auto", "live", "cache", "test", "fallback"]


@dataclass(frozen=True)
class _CachedPayload:
    value: Mapping[str, Any]
    expires_at: datetime


class MarketDetailEnricher:
    """Busca histórico e câmbio somente para uma oportunidade selecionada."""

    def __init__(
        self,
        *,
        defillama_base_url: str | None,
        fx_base_url: str | None,
        http_client: HttpGetPort,
        clock: ClockPort | None = None,
        history_ttl_seconds: float = 300.0,
        fx_ttl_seconds: float = 21_600.0,
        timeout_seconds: float = 5.0,
    ) -> None:
        if history_ttl_seconds <= 0 or fx_ttl_seconds <= 0 or timeout_seconds <= 0:
            raise ValueError("TTLs e timeout do enriquecimento devem ser positivos")
        self.defillama_base_url = defillama_base_url
        self.fx_base_url = fx_base_url
        self.http_client = http_client
        self.clock = clock or SystemClock()
        self.history_ttl_seconds = history_ttl_seconds
        self.fx_ttl_seconds = fx_ttl_seconds
        self.timeout_seconds = timeout_seconds
        self._history_cache: dict[str, _CachedPayload] = {}
        self._fx_cache: _CachedPayload | None = None
        self._lock = RLock()

    def enrich(
        self,
        *,
        opportunity_id: str,
        tvl_usd: float,
        mode: EnrichmentMode,
    ) -> dict[str, Any]:
        now = _utc(self.clock.now())
        history = self._history(opportunity_id, mode=mode, now=now)
        currency_display = self._currency_display(tvl_usd, mode=mode, now=now)
        return {"history": history, "currency_display": currency_display}

    def currency_displays(
        self, tvl_values_usd: Sequence[float], *, mode: EnrichmentMode
    ) -> tuple[Mapping[str, Any], ...]:
        """Converte vários TVLs com uma única leitura PTAX compartilhada."""
        now = _utc(self.clock.now())
        quote_data = self._fx_quote(mode=mode, now=now)
        return tuple(
            self._currency_display_from_quote(value, quote_data=quote_data, now=now)
            for value in tvl_values_usd
        )

    def _history(
        self, opportunity_id: str, *, mode: EnrichmentMode, now: datetime
    ) -> Mapping[str, Any]:
        cached = self._get_history_cache(opportunity_id)
        if mode == "cache":
            return self._cached_history(cached, now) if cached else _history_unavailable(now)
        if mode in {"test", "fallback"} or not self.defillama_base_url:
            return _history_unavailable(now)
        if cached is not None and now < cached.expires_at:
            return self._cached_history(cached, now)

        url = (
            self.defillama_base_url.rstrip("/")
            + "/chart/"
            + quote(opportunity_id, safe="")
        )
        try:
            payload = self.http_client.get(url, timeout_seconds=self.timeout_seconds)
            result = _normalize_history(payload, retrieved_at=now)
            entry = _CachedPayload(
                result, now + timedelta(seconds=self.history_ttl_seconds)
            )
            with self._lock:
                self._history_cache[opportunity_id] = entry
            return result
        except Exception:
            if cached is not None:
                return self._cached_history(cached, now, upstream_failed=True)
            return _history_unavailable(now)

    def _get_history_cache(self, opportunity_id: str) -> _CachedPayload | None:
        with self._lock:
            return self._history_cache.get(opportunity_id)

    @staticmethod
    def _cached_history(
        entry: _CachedPayload, now: datetime, *, upstream_failed: bool = False
    ) -> Mapping[str, Any]:
        stale = now >= entry.expires_at
        source = dict(entry.value["data_source"])
        source.update(
            {
                "mode": "cache",
                "is_stale": stale,
                "cache_expires_at": _iso(entry.expires_at),
            }
        )
        if upstream_failed:
            source["freshness_note"] = "DeFiLlama indisponível; cache preservado."
        return {**entry.value, "data_source": source}

    def _currency_display(
        self, tvl_usd: float, *, mode: EnrichmentMode, now: datetime
    ) -> Mapping[str, Any]:
        quote_data = self._fx_quote(mode=mode, now=now)
        return self._currency_display_from_quote(
            tvl_usd, quote_data=quote_data, now=now
        )

    @staticmethod
    def _currency_display_from_quote(
        tvl_usd: float,
        *,
        quote_data: Mapping[str, Any] | None,
        now: datetime,
    ) -> Mapping[str, Any]:
        if quote_data is None:
            return {
                "primary": {"value": tvl_usd, "currency": "USD"},
                "secondary": None,
                "fx": {
                    "status": "unavailable",
                    "source": "bcb_ptax",
                    "retrieved_at": _iso(now),
                    "is_stale": False,
                },
            }

        rate = float(quote_data["rate"])
        return {
            "primary": {"value": round(tvl_usd * rate, 2), "currency": "BRL"},
            "secondary": {"value": tvl_usd, "currency": "USD"},
            "fx": quote_data,
        }

    def _fx_quote(
        self, *, mode: EnrichmentMode, now: datetime
    ) -> Mapping[str, Any] | None:
        with self._lock:
            cached = self._fx_cache
        if mode == "cache":
            return self._cached_fx(cached, now) if cached else None
        if mode in {"test", "fallback"} or not self.fx_base_url:
            return None
        if cached is not None and now < cached.expires_at:
            return self._cached_fx(cached, now)

        start = (now - timedelta(days=10)).strftime("%m-%d-%Y")
        end = now.strftime("%m-%d-%Y")
        query = urlencode(
            {
                "@dataInicial": f"'{start}'",
                "@dataFinalCotacao": f"'{end}'",
                "$top": "100",
                "$orderby": "dataHoraCotacao desc",
                "$format": "json",
                "$select": (
                    "cotacaoCompra,cotacaoVenda,dataHoraCotacao,tipoBoletim"
                ),
            }
        )
        url = (
            self.fx_base_url.rstrip("/")
            + "/CotacaoDolarPeriodo(dataInicial=@dataInicial,"
            "dataFinalCotacao=@dataFinalCotacao)?"
            + query
        )
        try:
            payload = self.http_client.get(url, timeout_seconds=self.timeout_seconds)
            quote_data = _normalize_ptax(payload, retrieved_at=now)
            entry = _CachedPayload(
                quote_data, now + timedelta(seconds=self.fx_ttl_seconds)
            )
            with self._lock:
                self._fx_cache = entry
            return quote_data
        except Exception:
            return self._cached_fx(cached, now, upstream_failed=True) if cached else None

    @staticmethod
    def _cached_fx(
        entry: _CachedPayload, now: datetime, *, upstream_failed: bool = False
    ) -> Mapping[str, Any]:
        stale = now >= entry.expires_at
        result = {
            **entry.value,
            "mode": "cache",
            "is_stale": stale,
            "cache_expires_at": _iso(entry.expires_at),
        }
        if upstream_failed:
            result["freshness_note"] = "PTAX indisponível; cache preservado."
        return result


def _history_unavailable(now: datetime) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "points": [],
        "windows": {},
        "data_source": {
            "source": "defillama",
            "dataset": "pool_chart",
            "mode": "unavailable",
            "retrieved_at": _iso(now),
            "is_stale": False,
        },
    }


def _normalize_history(
    payload: JsonPayload, *, retrieved_at: datetime
) -> dict[str, Any]:
    raw: Any = payload.get("data") if isinstance(payload, Mapping) else payload
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise MarketDataError("Série histórica DeFiLlama inválida")

    by_timestamp: dict[datetime, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        try:
            observed_at = _parse_datetime(item.get("timestamp"))
        except MarketDataError:
            continue
        apy = _optional_number(item.get("apy"), non_negative=False)
        tvl = _optional_number(item.get("tvlUsd"), non_negative=True)
        if apy is None and tvl is None:
            continue
        point: dict[str, Any] = {"observed_at": _iso(observed_at)}
        if apy is not None:
            point["apy_percent"] = apy
        if tvl is not None:
            point["tvl_usd"] = tvl
        by_timestamp[observed_at] = point
    if not by_timestamp:
        raise MarketDataError("Série histórica DeFiLlama sem pontos utilizáveis")

    ordered = sorted(by_timestamp.items())
    latest_at = ordered[-1][0]
    display_cutoff = latest_at - timedelta(days=30)
    display_points = [point for timestamp, point in ordered if timestamp >= display_cutoff]
    windows = {
        "7d": _window_metrics(ordered, latest_at=latest_at, days=7),
        "30d": _window_metrics(ordered, latest_at=latest_at, days=30),
    }
    return {
        "status": "available",
        "points": display_points,
        "windows": windows,
        "data_source": {
            "source": "defillama",
            "dataset": "pool_chart",
            "mode": "live",
            "observed_at": _iso(latest_at),
            "retrieved_at": _iso(retrieved_at),
            "is_stale": False,
        },
    }


def _window_metrics(
    ordered: Sequence[tuple[datetime, Mapping[str, Any]]],
    *,
    latest_at: datetime,
    days: int,
) -> dict[str, Any]:
    cutoff = latest_at - timedelta(days=days)
    points = [(timestamp, point) for timestamp, point in ordered if timestamp >= cutoff]
    apys = [float(point["apy_percent"]) for _, point in points if "apy_percent" in point]
    tvls = [float(point["tvl_usd"]) for _, point in points if "tvl_usd" in point]
    result: dict[str, Any] = {
        "window_days": days,
        "point_count": len(points),
        "observed_from": _iso(points[0][0]),
        "observed_to": _iso(points[-1][0]),
        "apy": None,
        "tvl_usd": None,
    }
    if apys:
        change = apys[-1] - apys[0]
        result["apy"] = {
            "average": _rounded(sum(apys) / len(apys)),
            "minimum": _rounded(min(apys)),
            "maximum": _rounded(max(apys)),
            "first": _rounded(apys[0]),
            "latest": _rounded(apys[-1]),
            "change_percentage_points": _rounded(change),
            "trend": "up" if change > 0 else "down" if change < 0 else "flat",
        }
    if tvls:
        change = tvls[-1] - tvls[0]
        percent = (change / tvls[0] * 100) if tvls[0] > 0 else None
        result["tvl_usd"] = {
            "first": _rounded(tvls[0], digits=2),
            "latest": _rounded(tvls[-1], digits=2),
            "change": _rounded(change, digits=2),
            "change_percent": _rounded(percent) if percent is not None else None,
        }
    return result


def _normalize_ptax(payload: JsonPayload, *, retrieved_at: datetime) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise MarketDataError("Resposta PTAX inválida")
    raw = payload.get("value")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise MarketDataError("Resposta PTAX sem cotações")
    candidates: list[tuple[datetime, float, float, str | None]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        try:
            observed_at = _parse_ptax_datetime(item.get("dataHoraCotacao"))
        except MarketDataError:
            continue
        buy = _optional_number(item.get("cotacaoCompra"), non_negative=True)
        sell = _optional_number(item.get("cotacaoVenda"), non_negative=True)
        if buy is None or sell is None or buy <= 0 or sell <= 0:
            continue
        bulletin = item.get("tipoBoletim")
        candidates.append(
            (observed_at, buy, sell, bulletin if isinstance(bulletin, str) else None)
        )
    if not candidates:
        raise MarketDataError("Resposta PTAX sem cotação USD/BRL utilizável")
    closing = [
        item
        for item in candidates
        if item[3] is not None and "fechamento" in item[3].casefold()
    ]
    selected = closing or candidates
    observed_at, buy, sell, bulletin = max(selected, key=lambda item: item[0])
    result: dict[str, Any] = {
        "status": "available",
        "base_currency": "USD",
        "quote_currency": "BRL",
        "rate": _rounded((buy + sell) / 2, digits=6),
        "rate_method": "midpoint_buy_sell",
        "quote_selection": (
            "latest_closing_bulletin" if closing else "latest_available_bulletin"
        ),
        "buy_rate": _rounded(buy, digits=6),
        "sell_rate": _rounded(sell, digits=6),
        "source": "bcb_ptax",
        "mode": "live",
        "observed_at": _iso(observed_at),
        "retrieved_at": _iso(retrieved_at),
        "is_stale": False,
    }
    if bulletin:
        result["bulletin_type"] = bulletin
    return result


def _optional_number(value: Any, *, non_negative: bool) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, Real):
        return None
    result = float(value)
    if not isfinite(result) or (non_negative and result < 0):
        return None
    return result


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _utc(value)
    if isinstance(value, Real) and not isinstance(value, bool):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as error:
            raise MarketDataError("Timestamp externo inválido") from error
    if isinstance(value, str):
        normalized = value.strip().replace("Z", "+00:00")
        try:
            return _utc(datetime.fromisoformat(normalized))
        except ValueError as error:
            raise MarketDataError("Timestamp externo inválido") from error
    raise MarketDataError("Timestamp externo inválido")


def _parse_ptax_datetime(value: Any) -> datetime:
    """Interpreta o horário sem offset da PTAX no fuso oficial de Brasília."""
    if not isinstance(value, str):
        raise MarketDataError("Timestamp PTAX inválido")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise MarketDataError("Timestamp PTAX inválido") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("America/Sao_Paulo"))
    return parsed.astimezone(timezone.utc)


def _rounded(value: float, *, digits: int = 6) -> float:
    return round(value, digits)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")
