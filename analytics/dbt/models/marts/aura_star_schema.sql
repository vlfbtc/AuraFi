{{ config(materialized='view') }}

/*
  Consumo unificado do star schema. Cada ramo mantém o grão da tabela fato
  original; as chaves dimensionais continuam disponíveis para joins e testes.
*/
with recommendation_rows as (
    select
        f.recommendation_key as mart_row_key,
        'recommendation' as record_type,
        'one recommendation per user, channel and moment' as grain,
        f.time_key,
        f.user_key,
        u.user_pseudo_id,
        f.risk_profile_key,
        p.declared_profile,
        f.protocol_key,
        pr.protocol_name,
        f.asset_key,
        a.asset_symbol,
        f.blockchain_key,
        b.blockchain_name,
        f.channel_key,
        c.channel_name,
        f.recommendation_id as record_id,
        cast(null as {{ dbt.type_string() }}) as pool_name,
        f.recommended_at as event_at,
        f.recommended_apy_percent,
        f.simulated_value,
        f.confidence_score,
        f.decision_accepted,
        cast(null as numeric(12, 4)) as yield_apy_percent,
        cast(null as numeric(18, 2)) as tvl_usd,
        cast(null as {{ dbt.type_string() }}) as liquidity_level,
        cast(null as integer) as message_count,
        cast(null as integer) as session_duration_seconds,
        cast(null as {{ dbt.type_boolean() }}) as continuity_flag,
        f.input_tokens,
        f.output_tokens,
        f.llm_cost_usd,
        cast(null as integer) as user_message_count,
        cast(null as integer) as aura_message_count,
        cast(null as smallint) as csat_score,
        cast(null as {{ dbt.type_boolean() }}) as escalation_flag,
        cast(null as {{ dbt.type_boolean() }}) as generated_recommendation,
        cast(null as integer) as resumption_time_seconds,
        cast(null as integer) as context_loss_events,
        cast(null as {{ dbt.type_boolean() }}) as premium_conversion_flag,
        cast(null as numeric(7, 4)) as base_apr_percent,
        cast(null as numeric(7, 4)) as incentive_apy_percent,
        cast(null as numeric(4, 2)) as liquidity_score,
        cast(null as {{ dbt.type_boolean() }}) as recommendable_flag,
        f.is_test_data
    from {{ ref('fato_recomendacao') }} f
    join {{ ref('dim_usuario') }} u on u.user_key = f.user_key
    join {{ ref('dim_perfil_risco') }} p on p.risk_profile_key = f.risk_profile_key
    join {{ ref('dim_protocolo') }} pr on pr.protocol_key = f.protocol_key
    join {{ ref('dim_ativo') }} a on a.asset_key = f.asset_key
    join {{ ref('dim_blockchain') }} b on b.blockchain_key = f.blockchain_key
    join {{ ref('dim_canal') }} c on c.channel_key = f.channel_key
),
yield_rows as (
    select
        f.yield_observation_key as mart_row_key,
        'yield_observation' as record_type,
        'one snapshot per pool, protocol, asset and blockchain' as grain,
        f.time_key,
        cast(null as {{ dbt.type_string() }}) as user_key,
        cast(null as {{ dbt.type_string() }}) as user_pseudo_id,
        f.risk_profile_key,
        rp.declared_profile,
        f.protocol_key,
        pr.protocol_name,
        f.asset_key,
        a.asset_symbol,
        f.blockchain_key,
        b.blockchain_name,
        cast(null as {{ dbt.type_string() }}) as channel_key,
        cast(null as {{ dbt.type_string() }}) as channel_name,
        f.pool_name as record_id,
        f.pool_name,
        f.observed_at as event_at,
        cast(null as numeric(12, 4)) as recommended_apy_percent,
        cast(null as numeric(18, 2)) as simulated_value,
        cast(null as numeric(8, 4)) as confidence_score,
        cast(null as {{ dbt.type_boolean() }}) as decision_accepted,
        f.yield_apy_percent,
        f.tvl_usd,
        f.liquidity_level,
        cast(null as integer) as message_count,
        cast(null as integer) as session_duration_seconds,
        cast(null as {{ dbt.type_boolean() }}) as continuity_flag,
        cast(null as integer) as input_tokens,
        cast(null as integer) as output_tokens,
        cast(null as numeric(12, 6)) as llm_cost_usd,
        cast(null as integer) as user_message_count,
        cast(null as integer) as aura_message_count,
        cast(null as smallint) as csat_score,
        cast(null as {{ dbt.type_boolean() }}) as escalation_flag,
        cast(null as {{ dbt.type_boolean() }}) as generated_recommendation,
        cast(null as integer) as resumption_time_seconds,
        cast(null as integer) as context_loss_events,
        cast(null as {{ dbt.type_boolean() }}) as premium_conversion_flag,
        f.base_apr_percent,
        f.incentive_apy_percent,
        f.liquidity_score,
        f.recommendable_flag,
        f.is_test_data
    from {{ ref('fato_yield_observacao') }} f
    join {{ ref('dim_protocolo') }} pr on pr.protocol_key = f.protocol_key
    join {{ ref('dim_perfil_risco') }} rp on rp.risk_profile_key = f.risk_profile_key
    join {{ ref('dim_ativo') }} a on a.asset_key = f.asset_key
    join {{ ref('dim_blockchain') }} b on b.blockchain_key = f.blockchain_key
),
conversation_rows as (
    select
        f.conversation_key as mart_row_key,
        'conversation_session' as record_type,
        'one session with message gaps under 30 minutes' as grain,
        f.time_key,
        f.user_key,
        u.user_pseudo_id,
        f.risk_profile_key,
        p.declared_profile,
        cast(null as {{ dbt.type_string() }}) as protocol_key,
        cast(null as {{ dbt.type_string() }}) as protocol_name,
        cast(null as {{ dbt.type_string() }}) as asset_key,
        cast(null as {{ dbt.type_string() }}) as asset_symbol,
        cast(null as {{ dbt.type_string() }}) as blockchain_key,
        cast(null as {{ dbt.type_string() }}) as blockchain_name,
        f.channel_key,
        c.channel_name,
        f.session_id as record_id,
        cast(null as {{ dbt.type_string() }}) as pool_name,
        f.session_started_at as event_at,
        cast(null as numeric(12, 4)) as recommended_apy_percent,
        cast(null as numeric(18, 2)) as simulated_value,
        cast(null as numeric(8, 4)) as confidence_score,
        cast(null as {{ dbt.type_boolean() }}) as decision_accepted,
        cast(null as numeric(12, 4)) as yield_apy_percent,
        cast(null as numeric(18, 2)) as tvl_usd,
        cast(null as {{ dbt.type_string() }}) as liquidity_level,
        f.message_count,
        f.session_duration_seconds,
        f.continuity_flag,
        f.input_tokens,
        f.output_tokens,
        f.llm_cost_usd,
        f.user_message_count,
        f.aura_message_count,
        f.csat_score,
        f.escalation_flag,
        f.generated_recommendation,
        f.resumption_time_seconds,
        f.context_loss_events,
        f.premium_conversion_flag,
        cast(null as numeric(7, 4)) as base_apr_percent,
        cast(null as numeric(7, 4)) as incentive_apy_percent,
        cast(null as numeric(4, 2)) as liquidity_score,
        cast(null as {{ dbt.type_boolean() }}) as recommendable_flag,
        f.is_test_data
    from {{ ref('fato_interacao_conversacional') }} f
    join {{ ref('dim_usuario') }} u on u.user_key = f.user_key
    join {{ ref('dim_perfil_risco') }} p on p.risk_profile_key = f.risk_profile_key
    join {{ ref('dim_canal') }} c on c.channel_key = f.channel_key
)

select * from recommendation_rows
union all
select * from yield_rows
union all
select * from conversation_rows
