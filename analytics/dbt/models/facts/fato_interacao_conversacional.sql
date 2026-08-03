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
        c.channel_key
    from sessions s
    join {{ ref('dim_tempo') }} t on t.hour_at = date_trunc('hour', s.occurred_at)
    join {{ ref('dim_usuario') }} u on u.user_pseudo_id = s.user_pseudo_id and u.user_version = s.user_version
    join {{ ref('dim_perfil_risco') }} p on p.declared_profile = s.risk_profile and p.version = s.risk_version
    join {{ ref('dim_canal') }} c on c.channel_name = s.channel_name and c.adapter = s.channel_adapter
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
    session_duration_seconds,
    input_tokens,
    output_tokens,
    llm_cost_usd,
    fallback_used,
    escalation_flag,
    is_test_data,
    source_system
from joined

