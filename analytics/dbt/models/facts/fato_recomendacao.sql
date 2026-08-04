with recommendations as (
    select *
    from {{ ref('stg_test_events') }}
    where event_type = 'recommendation'
),
joined as (
    select
        r.*,
        t.time_key,
        u.user_key,
        p.risk_profile_key,
        pr.protocol_key,
        a.asset_key,
        b.blockchain_key,
        c.channel_key,
        e.prompt_version
    from recommendations r
    join {{ ref('dim_tempo') }} t on t.hour_at = date_trunc('hour', r.occurred_at)
    join {{ ref('dim_usuario') }} u on u.user_pseudo_id = r.user_pseudo_id and u.user_version = r.user_version
    join {{ ref('dim_perfil_risco') }} p on p.declared_profile = r.risk_profile
    join {{ ref('dim_protocolo') }} pr on pr.protocol_name = r.protocol_name
    join {{ ref('dim_ativo') }} a on a.asset_symbol = r.asset_symbol
    join {{ ref('dim_blockchain') }} b on b.blockchain_name = r.blockchain_name
    join {{ ref('dim_canal') }} c on c.channel_name = r.channel_name and c.adapter = r.channel_adapter
    left join {{ ref('stg_fact_enrichment') }} e on e.event_id = r.event_id
)

select
    md5(recommendation_id) as recommendation_key,
    recommendation_id,
    opportunity_id,
    time_key,
    user_key,
    risk_profile_key,
    protocol_key,
    asset_key,
    blockchain_key,
    channel_key,
    occurred_at as recommended_at,
    recommendation_status as status,
    profile_used,
    recommended_apy_percent,
    simulated_value,
    confidence_score,
    decision_accepted,
    decision_time_seconds,
    input_tokens,
    output_tokens,
    llm_cost_usd,
    prompt_version,
    is_test_data,
    source_system
from joined
