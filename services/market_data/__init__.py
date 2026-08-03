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
    "NormalizedOpportunity",
    "SyntheticFallback",
    "SystemClock",
    "UrllibHttpClient",
]
