"""Porta de leitura de dados de mercado do AuraFi."""

from .defillama import (
    CacheEntry,
    CachePort,
    ClockPort,
    DataSourceMetadata,
    DeFiLlamaAdapter,
    DeFiLlamaSchema,
    FallbackPort,
    HttpGetPort,
    InMemoryCache,
    MarketDataError,
    MarketDataSnapshot,
    NormalizedOpportunity,
    SyntheticFallback,
    SystemClock,
    UrllibHttpClient,
)
from .enrichment import MarketDetailEnricher
from .presentation import decorate_opportunity, decorate_simulation, derive_risk_level

__all__ = [
    "CacheEntry",
    "CachePort",
    "ClockPort",
    "DataSourceMetadata",
    "DeFiLlamaAdapter",
    "DeFiLlamaSchema",
    "FallbackPort",
    "HttpGetPort",
    "InMemoryCache",
    "MarketDataError",
    "MarketDataSnapshot",
    "MarketDetailEnricher",
    "NormalizedOpportunity",
    "SyntheticFallback",
    "SystemClock",
    "UrllibHttpClient",
    "decorate_opportunity",
    "decorate_simulation",
    "derive_risk_level",
]
