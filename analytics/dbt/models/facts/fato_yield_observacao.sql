with observations as (
    select *
    from {{ ref('stg_test_events') }}
    where event_type = 'yield_observation'
),
joined as (
    select
        o.*,
        t.time_key,
        rp.risk_profile_key,
        p.protocol_key,
        a.asset_key,
        b.blockchain_key,
        e.base_apr_percent,
        e.incentive_apy_percent,
        e.protocol_tvl_snapshot_usd,
        e.apy_volatility_30d,
        e.impermanent_loss_30d_percent,
        e.liquidity_score,
        e.recommendable_flag
    from observations o
    join {{ ref('dim_tempo') }} t on t.hour_at = date_trunc('hour', o.occurred_at)
    join {{ ref('dim_perfil_risco') }} rp on rp.declared_profile = o.risk_profile
    join {{ ref('dim_protocolo') }} p on p.protocol_name = o.protocol_name
    join {{ ref('dim_ativo') }} a on a.asset_symbol = o.asset_symbol
    join {{ ref('dim_blockchain') }} b on b.blockchain_name = o.blockchain_name
    left join {{ ref('stg_fact_enrichment') }} e on e.event_id = o.event_id
)

select
    md5(pool_name || ':' || protocol_name || ':' || asset_symbol || ':' || blockchain_name || ':' || cast(observed_at as {{ dbt.type_string() }})) as yield_observation_key,
    pool_name,
    time_key,
    risk_profile_key,
    protocol_key,
    asset_key,
    blockchain_key,
    yield_apy_percent,
    base_apr_percent,
    incentive_apy_percent,
    tvl_usd,
    protocol_tvl_snapshot_usd,
    apy_volatility_30d,
    impermanent_loss_30d_percent,
    liquidity_level,
    liquidity_score,
    recommendable_flag,
    observed_at,
    retrieved_at,
    market_source as source,
    market_mode as mode,
    read_only,
    is_stale,
    is_test_data,
    source_system
from joined
