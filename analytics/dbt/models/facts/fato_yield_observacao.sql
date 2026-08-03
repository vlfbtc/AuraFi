with observations as (
    select *
    from {{ ref('stg_test_events') }}
    where event_type = 'yield_observation'
),
joined as (
    select
        o.*,
        t.time_key,
        p.protocol_key,
        a.asset_key,
        b.blockchain_key
    from observations o
    join {{ ref('dim_tempo') }} t on t.hour_at = date_trunc('hour', o.occurred_at)
    join {{ ref('dim_protocolo') }} p on p.protocol_name = o.protocol_name
    join {{ ref('dim_ativo') }} a on a.asset_symbol = o.asset_symbol
    join {{ ref('dim_blockchain') }} b on b.blockchain_name = o.blockchain_name
)

select
    md5(pool_name || ':' || protocol_name || ':' || asset_symbol || ':' || blockchain_name || ':' || cast(observed_at as {{ dbt.type_string() }})) as yield_observation_key,
    pool_name,
    time_key,
    protocol_key,
    asset_key,
    blockchain_key,
    yield_apy_percent,
    tvl_usd,
    liquidity_level,
    observed_at,
    retrieved_at,
    market_source as source,
    market_mode as mode,
    read_only,
    is_stale,
    is_test_data,
    source_system
from joined

