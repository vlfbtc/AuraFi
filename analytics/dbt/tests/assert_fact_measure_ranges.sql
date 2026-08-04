with violations as (
    select 'fato_recomendacao' as model_name, recommendation_key as row_key, 'measure_range' as violation
    from {{ ref('fato_recomendacao') }}
    where recommended_apy_percent < 0
       or simulated_value < 0
       or confidence_score < 0 or confidence_score > 1
       or decision_time_seconds < 0
       or input_tokens < 0 or output_tokens < 0 or llm_cost_usd < 0

    union all

    select 'fato_yield_observacao', yield_observation_key, 'measure_range'
    from {{ ref('fato_yield_observacao') }}
    where yield_apy_percent < 0
       or base_apr_percent < 0
       or incentive_apy_percent < 0
       or abs(yield_apy_percent - base_apr_percent - incentive_apy_percent) > 0.0001
       or tvl_usd < 0 or protocol_tvl_snapshot_usd < 0
       or apy_volatility_30d < 0 or impermanent_loss_30d_percent < 0
       or liquidity_score < 0 or liquidity_score > 10
       or retrieved_at < observed_at

    union all

    select 'fato_interacao_conversacional', conversation_key, 'measure_range'
    from {{ ref('fato_interacao_conversacional') }}
    where user_message_count < 0 or aura_message_count < 0
       or message_count <> user_message_count + aura_message_count
       or session_duration_seconds < 0
       or session_ended_at < session_started_at
       or total_llm_tokens < 0 or llm_cost_usd < 0
       or (csat_score is not null and (csat_score < 1 or csat_score > 5))
       or context_loss_events < 0
       or (previous_session_id is not null and resumption_time_seconds < 0)
)

select * from violations
