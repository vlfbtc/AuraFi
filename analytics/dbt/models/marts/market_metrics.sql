{{ config(materialized='view') }}

/* One row per UTC day and complete market dimensional slice. */
select
    t.calendar_date,
    f.risk_profile_key,
    rp.declared_profile,
    f.protocol_key,
    p.protocol_name,
    f.asset_key,
    a.asset_symbol,
    f.blockchain_key,
    b.blockchain_name,
    f.source,
    f.mode,
    count(*) as observation_count,
    avg(f.yield_apy_percent) as average_observed_apy_percent,
    avg(f.base_apr_percent) as average_base_apr_percent,
    avg(f.incentive_apy_percent) as average_incentive_apy_percent,
    avg(f.tvl_usd) as average_pool_tvl_usd,
    avg(f.protocol_tvl_snapshot_usd) as average_protocol_tvl_usd,
    avg(f.apy_volatility_30d) as average_apy_volatility_30d,
    avg(f.impermanent_loss_30d_percent) as average_impermanent_loss_30d_percent,
    avg(f.liquidity_score) as average_liquidity_score,
    cast(sum(case when f.recommendable_flag = true then 1 else 0 end) as numeric(18, 8))
        / nullif(cast(count(*) as numeric(18, 8)), 0) as recommendable_pool_rate,
    cast(sum(case when f.is_stale = true then 1 else 0 end) as numeric(18, 8))
        / nullif(cast(count(*) as numeric(18, 8)), 0) as stale_observation_rate,
    true as is_test_data
from {{ ref('fato_yield_observacao') }} f
join {{ ref('dim_tempo') }} t on t.time_key = f.time_key
join {{ ref('dim_perfil_risco') }} rp on rp.risk_profile_key = f.risk_profile_key
join {{ ref('dim_protocolo') }} p on p.protocol_key = f.protocol_key
join {{ ref('dim_ativo') }} a on a.asset_key = f.asset_key
join {{ ref('dim_blockchain') }} b on b.blockchain_key = f.blockchain_key
where f.is_test_data = true
group by
    t.calendar_date,
    f.risk_profile_key,
    rp.declared_profile,
    f.protocol_key,
    p.protocol_name,
    f.asset_key,
    a.asset_symbol,
    f.blockchain_key,
    b.blockchain_name,
    f.source,
    f.mode
