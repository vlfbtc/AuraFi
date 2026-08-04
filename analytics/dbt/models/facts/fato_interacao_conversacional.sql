with sessions as (
    select *
    from {{ ref('stg_test_events') }}
    where event_type = 'conversation_session'
),
joined as (
    select
        s.*,
        t.time_key,
        u.user_key,
        p.risk_profile_key,
        c.channel_key,
        e.user_message_count,
        e.aura_message_count,
        e.main_topic,
        e.csat_score,
        e.generated_recommendation,
        e.resumption_time_seconds,
        e.context_loss_events,
        e.premium_conversion_flag,
        e.session_input_tokens,
        e.session_output_tokens,
        e.session_llm_cost_usd
    from sessions s
    join {{ ref('dim_tempo') }} t on t.hour_at = date_trunc('hour', s.occurred_at)
    join {{ ref('dim_usuario') }} u on u.user_pseudo_id = s.user_pseudo_id and u.user_version = s.user_version
    join {{ ref('dim_perfil_risco') }} p on p.declared_profile = s.risk_profile
    join {{ ref('dim_canal') }} c on c.channel_name = s.channel_name and c.adapter = s.channel_adapter
    left join {{ ref('stg_fact_enrichment') }} e on e.event_id = s.event_id
)

select
    md5(session_id) as conversation_key,
    session_id,
    conversation_id,
    previous_session_id,
    time_key,
    user_key,
    risk_profile_key,
    channel_key,
    session_started_at,
    session_ended_at,
    continuity_flag,
    message_count,
    user_message_count,
    aura_message_count,
    session_duration_seconds,
    coalesce(input_tokens, session_input_tokens) as input_tokens,
    coalesce(output_tokens, session_output_tokens) as output_tokens,
    coalesce(input_tokens, session_input_tokens, 0)
        + coalesce(output_tokens, session_output_tokens, 0) as total_llm_tokens,
    coalesce(llm_cost_usd, session_llm_cost_usd) as llm_cost_usd,
    main_topic,
    csat_score,
    fallback_used,
    escalation_flag,
    generated_recommendation,
    resumption_time_seconds,
    context_loss_events,
    premium_conversion_flag,
    is_test_data,
    source_system
from joined
