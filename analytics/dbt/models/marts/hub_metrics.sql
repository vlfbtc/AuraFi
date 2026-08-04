{{ config(materialized='view') }}

with grouped as (
    select
        t.calendar_date,
        f.channel_key,
        c.channel_name,
        f.risk_profile_key,
        rp.declared_profile,
        u.plan,
        count(*) as session_count,
        sum(coalesce(f.user_message_count, 0)) as user_message_count,
        sum(coalesce(f.aura_message_count, 0)) as aura_message_count,
        avg(f.session_duration_seconds) as average_session_duration_seconds,
        avg(f.total_llm_tokens) as average_llm_tokens_per_session,
        sum(coalesce(f.total_llm_tokens, 0)) as total_llm_tokens,
        sum(coalesce(f.llm_cost_usd, 0)) as total_llm_cost_usd,
        sum(coalesce(f.llm_cost_usd, 0))
            / nullif(cast(count(*) as numeric(18, 8)), 0) as llm_cost_per_session_usd,
        avg(f.csat_score) as average_csat,
        cast(count(f.csat_score) as numeric(18, 8))
            / nullif(cast(count(*) as numeric(18, 8)), 0) as csat_response_rate,
        cast(sum(case when f.escalation_flag = true then 1 else 0 end) as numeric(18, 8))
            / nullif(cast(count(*) as numeric(18, 8)), 0) as human_escalation_rate,
        cast(sum(case when f.generated_recommendation = true then 1 else 0 end) as numeric(18, 8))
            / nullif(cast(count(*) as numeric(18, 8)), 0) as recommendation_generation_rate,
        cast(sum(case when f.fallback_used = true then 1 else 0 end) as numeric(18, 8))
            / nullif(cast(count(*) as numeric(18, 8)), 0) as fallback_rate,
        cast(sum(case when f.premium_conversion_flag = true then 1 else 0 end) as numeric(18, 8))
            / nullif(cast(count(*) as numeric(18, 8)), 0) as premium_conversion_rate,
        sum(coalesce(f.context_loss_events, 0)) as context_loss_events,
        cast(sum(case when coalesce(f.context_loss_events, 0) > 0 then 1 else 0 end) as numeric(18, 8))
            / nullif(cast(count(*) as numeric(18, 8)), 0) as context_loss_session_rate,
        true as is_test_data
    from {{ ref('fato_interacao_conversacional') }} f
    join {{ ref('dim_tempo') }} t on t.time_key = f.time_key
    join {{ ref('dim_usuario') }} u on u.user_key = f.user_key
    join {{ ref('dim_canal') }} c on c.channel_key = f.channel_key
    join {{ ref('dim_perfil_risco') }} rp on rp.risk_profile_key = f.risk_profile_key
    where f.is_test_data = true
    group by
        t.calendar_date,
        f.channel_key,
        c.channel_name,
        f.risk_profile_key,
        rp.declared_profile,
        u.plan
)

select
    *,
    cast(session_count as numeric(18, 8))
        / nullif(cast(sum(session_count) over (partition by calendar_date) as numeric(18, 8)), 0)
        as channel_engagement_share
from grouped
