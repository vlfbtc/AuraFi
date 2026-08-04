{{ config(materialized='view') }}

/* One row per UTC day, channel, declared profile and protocol. */
select
    t.calendar_date,
    f.channel_key,
    c.channel_name,
    f.risk_profile_key,
    rp.declared_profile,
    f.protocol_key,
    p.protocol_name,
    count(*) as recommendation_count,
    sum(case when f.decision_accepted = true then 1 else 0 end) as accepted_count,
    cast(sum(case when f.decision_accepted = true then 1 else 0 end) as numeric(18, 8))
        / nullif(cast(count(*) as numeric(18, 8)), 0) as acceptance_rate,
    avg(f.simulated_value) as average_simulated_ticket_usd,
    avg(f.confidence_score) as average_ai_confidence,
    avg(f.decision_time_seconds) as average_decision_time_seconds,
    sum(coalesce(f.input_tokens, 0)) as input_tokens,
    sum(coalesce(f.output_tokens, 0)) as output_tokens,
    sum(coalesce(f.llm_cost_usd, 0)) as total_llm_cost_usd,
    sum(coalesce(f.llm_cost_usd, 0))
        / nullif(cast(count(*) as numeric(18, 8)), 0) as llm_cost_per_recommendation_usd,
    true as is_test_data
from {{ ref('fato_recomendacao') }} f
join {{ ref('dim_tempo') }} t on t.time_key = f.time_key
join {{ ref('dim_canal') }} c on c.channel_key = f.channel_key
join {{ ref('dim_perfil_risco') }} rp on rp.risk_profile_key = f.risk_profile_key
join {{ ref('dim_protocolo') }} p on p.protocol_key = f.protocol_key
where f.is_test_data = true
group by
    t.calendar_date,
    f.channel_key,
    c.channel_name,
    f.risk_profile_key,
    rp.declared_profile,
    f.protocol_key,
    p.protocol_name
