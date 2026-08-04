{{ config(materialized='view') }}

select
    cast(event_id as {{ dbt.type_string() }}) as event_id,
    cast(prompt_version as {{ dbt.type_string() }}) as prompt_version,
    cast(base_apr_percent as numeric(7, 4)) as base_apr_percent,
    cast(incentive_apy_percent as numeric(7, 4)) as incentive_apy_percent,
    cast(protocol_tvl_snapshot_usd as numeric(18, 2)) as protocol_tvl_snapshot_usd,
    cast(apy_volatility_30d as numeric(7, 4)) as apy_volatility_30d,
    cast(impermanent_loss_30d_percent as numeric(7, 4)) as impermanent_loss_30d_percent,
    cast(liquidity_score as numeric(4, 2)) as liquidity_score,
    cast(recommendable_flag as {{ dbt.type_boolean() }}) as recommendable_flag,
    cast(user_message_count as integer) as user_message_count,
    cast(aura_message_count as integer) as aura_message_count,
    cast(main_topic as {{ dbt.type_string() }}) as main_topic,
    cast(csat_score as smallint) as csat_score,
    cast(generated_recommendation as {{ dbt.type_boolean() }}) as generated_recommendation,
    cast(resumption_time_seconds as integer) as resumption_time_seconds,
    cast(context_loss_events as integer) as context_loss_events,
    cast(premium_conversion_flag as {{ dbt.type_boolean() }}) as premium_conversion_flag,
    cast(session_input_tokens as integer) as session_input_tokens,
    cast(session_output_tokens as integer) as session_output_tokens,
    cast(session_llm_cost_usd as numeric(12, 6)) as session_llm_cost_usd,
    cast(is_test_data as {{ dbt.type_boolean() }}) as is_test_data
from {{ ref('mvp_fact_enrichment') }}
where is_test_data = true
