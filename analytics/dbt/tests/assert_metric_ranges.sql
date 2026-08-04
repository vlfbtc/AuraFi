with violations as (
    select cast(channel_key as {{ dbt.type_string() }}) as metric_key, 'recommendation_metrics' as model_name
    from {{ ref('recommendation_metrics') }}
    where acceptance_rate < 0 or acceptance_rate > 1
       or average_simulated_ticket_usd < 0
       or average_ai_confidence < 0 or average_ai_confidence > 1
       or average_decision_time_seconds < 0
       or total_llm_cost_usd < 0

    union all

    select cast(channel_key as {{ dbt.type_string() }}), 'hub_metrics'
    from {{ ref('hub_metrics') }}
    where channel_engagement_share < 0 or channel_engagement_share > 1
       or human_escalation_rate < 0 or human_escalation_rate > 1
       or recommendation_generation_rate < 0 or recommendation_generation_rate > 1
       or fallback_rate < 0 or fallback_rate > 1
       or premium_conversion_rate < 0 or premium_conversion_rate > 1
       or context_loss_session_rate < 0 or context_loss_session_rate > 1
       or (average_csat is not null and (average_csat < 1 or average_csat > 5))

    union all

    select cast(channel_key as {{ dbt.type_string() }}), 'cross_channel_metrics'
    from {{ ref('cross_channel_metrics') }}
    where cross_channel_handoff_rate < 0 or cross_channel_handoff_rate > 1
       or context_loss_handoff_rate < 0 or context_loss_handoff_rate > 1
       or average_session_resumption_seconds < 0

    union all

    select cast(protocol_key as {{ dbt.type_string() }}), 'market_metrics'
    from {{ ref('market_metrics') }}
    where recommendable_pool_rate < 0 or recommendable_pool_rate > 1
       or stale_observation_rate < 0 or stale_observation_rate > 1
       or average_observed_apy_percent < 0
       or average_pool_tvl_usd < 0
)

select * from violations
