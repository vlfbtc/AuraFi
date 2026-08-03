{{ config(materialized='view') }}

/*
  MVP metrics for the synthetic DW fixture.

  The model deliberately keeps each fact at its native grain before
  aggregating. No fact-to-fact join is used except the explicit
  previous_session_id link needed to prove cross-channel continuity.

  Output grain:
    one row per metric_name, calendar_date and applicable breakdown
    (channel/profile, channel pair, source/mode, or fixture day).
*/
with recommendation_base as (
    select
        f.recommendation_key,
        f.time_key,
        t.calendar_date,
        f.user_key,
        f.risk_profile_key,
        p.declared_profile,
        f.channel_key,
        c.channel_name,
        f.decision_accepted,
        f.confidence_score,
        f.decision_time_seconds,
        f.llm_cost_usd,
        f.is_test_data
    from {{ ref('fato_recomendacao') }} f
    join {{ ref('dim_tempo') }} t on t.time_key = f.time_key
    join {{ ref('dim_usuario') }} u on u.user_key = f.user_key
    join {{ ref('dim_perfil_risco') }} p on p.risk_profile_key = f.risk_profile_key
    join {{ ref('dim_protocolo') }} pr on pr.protocol_key = f.protocol_key
    join {{ ref('dim_ativo') }} a on a.asset_key = f.asset_key
    join {{ ref('dim_blockchain') }} b on b.blockchain_key = f.blockchain_key
    join {{ ref('dim_canal') }} c on c.channel_key = f.channel_key
    where f.is_test_data = true
),
conversation_base as (
    select
        f.conversation_key,
        f.session_id,
        f.previous_session_id,
        f.time_key,
        t.calendar_date,
        f.user_key,
        f.risk_profile_key,
        p.declared_profile,
        f.channel_key,
        c.channel_name,
        f.continuity_flag,
        f.fallback_used,
        f.is_test_data
    from {{ ref('fato_interacao_conversacional') }} f
    join {{ ref('dim_tempo') }} t on t.time_key = f.time_key
    join {{ ref('dim_usuario') }} u on u.user_key = f.user_key
    join {{ ref('dim_perfil_risco') }} p on p.risk_profile_key = f.risk_profile_key
    join {{ ref('dim_canal') }} c on c.channel_key = f.channel_key
    where f.is_test_data = true
),
yield_base as (
    select
        f.yield_observation_key,
        f.time_key,
        t.calendar_date,
        f.protocol_key,
        pr.protocol_name,
        f.asset_key,
        a.asset_symbol,
        f.blockchain_key,
        b.blockchain_name,
        f.source,
        f.mode,
        f.is_stale,
        f.is_test_data
    from {{ ref('fato_yield_observacao') }} f
    join {{ ref('dim_tempo') }} t on t.time_key = f.time_key
    join {{ ref('dim_protocolo') }} pr on pr.protocol_key = f.protocol_key
    join {{ ref('dim_ativo') }} a on a.asset_key = f.asset_key
    join {{ ref('dim_blockchain') }} b on b.blockchain_key = f.blockchain_key
    where f.is_test_data = true
),
cross_channel_pairs as (
    select
        current_session.calendar_date,
        current_session.user_key,
        current_session.channel_key,
        current_session.channel_name,
        previous_session.channel_key as previous_channel_key,
        previous_session.channel_name as previous_channel_name,
        current_session.continuity_flag,
        current_session.is_test_data
    from conversation_base current_session
    join conversation_base previous_session
        on previous_session.session_id = current_session.previous_session_id
        and previous_session.user_key = current_session.user_key
    where current_session.channel_key <> previous_session.channel_key
),
journey_users as (
    select distinct
        calendar_date,
        user_key
    from recommendation_base
),
covered_journey_users as (
    select distinct
        calendar_date,
        user_key
    from cross_channel_pairs
    where continuity_flag = true
),
metric_rows as (
    select
        'acceptance_rate' as metric_name,
        'acceptance' as metric_group,
        'one recommendation per calendar day, channel and declared profile' as metric_grain,
        'ratio' as metric_unit,
        cast(sum(case when decision_accepted = true then 1 else 0 end) as numeric(18, 8))
            / nullif(cast(count(*) as numeric(18, 8)), 0) as metric_value,
        cast(sum(case when decision_accepted = true then 1 else 0 end) as numeric(18, 8)) as numerator,
        cast(count(*) as numeric(18, 8)) as denominator,
        calendar_date,
        channel_key,
        channel_name,
        cast(null as {{ dbt.type_string() }}) as previous_channel_key,
        cast(null as {{ dbt.type_string() }}) as previous_channel_name,
        risk_profile_key,
        declared_profile,
        cast(null as {{ dbt.type_string() }}) as source,
        cast(null as {{ dbt.type_string() }}) as mode,
        'fato_recomendacao' as source_fact,
        is_test_data
    from recommendation_base
    group by calendar_date, channel_key, channel_name, risk_profile_key, declared_profile, is_test_data

    union all

    select
        'llm_cost_per_recommendation' as metric_name,
        'cost' as metric_group,
        'one recommendation per calendar day, channel and declared profile' as metric_grain,
        'usd_per_recommendation' as metric_unit,
        sum(llm_cost_usd) / nullif(cast(count(llm_cost_usd) as numeric(18, 8)), 0) as metric_value,
        sum(llm_cost_usd) as numerator,
        cast(count(llm_cost_usd) as numeric(18, 8)) as denominator,
        calendar_date,
        channel_key,
        channel_name,
        cast(null as {{ dbt.type_string() }}) as previous_channel_key,
        cast(null as {{ dbt.type_string() }}) as previous_channel_name,
        risk_profile_key,
        declared_profile,
        cast(null as {{ dbt.type_string() }}) as source,
        cast(null as {{ dbt.type_string() }}) as mode,
        'fato_recomendacao' as source_fact,
        is_test_data
    from recommendation_base
    where llm_cost_usd is not null
    group by calendar_date, channel_key, channel_name, risk_profile_key, declared_profile, is_test_data

    union all

    select
        'average_confidence' as metric_name,
        'trust' as metric_group,
        'one recommendation per calendar day, channel and declared profile' as metric_grain,
        'confidence_score' as metric_unit,
        avg(confidence_score) as metric_value,
        sum(confidence_score) as numerator,
        cast(count(confidence_score) as numeric(18, 8)) as denominator,
        calendar_date,
        channel_key,
        channel_name,
        cast(null as {{ dbt.type_string() }}) as previous_channel_key,
        cast(null as {{ dbt.type_string() }}) as previous_channel_name,
        risk_profile_key,
        declared_profile,
        cast(null as {{ dbt.type_string() }}) as source,
        cast(null as {{ dbt.type_string() }}) as mode,
        'fato_recomendacao' as source_fact,
        is_test_data
    from recommendation_base
    where confidence_score is not null
    group by calendar_date, channel_key, channel_name, risk_profile_key, declared_profile, is_test_data

    union all

    select
        'average_time_to_decision' as metric_name,
        'decision' as metric_group,
        'one recommendation per calendar day, channel and declared profile' as metric_grain,
        'seconds' as metric_unit,
        avg(decision_time_seconds) as metric_value,
        sum(decision_time_seconds) as numerator,
        cast(count(decision_time_seconds) as numeric(18, 8)) as denominator,
        calendar_date,
        channel_key,
        channel_name,
        cast(null as {{ dbt.type_string() }}) as previous_channel_key,
        cast(null as {{ dbt.type_string() }}) as previous_channel_name,
        risk_profile_key,
        declared_profile,
        cast(null as {{ dbt.type_string() }}) as source,
        cast(null as {{ dbt.type_string() }}) as mode,
        'fato_recomendacao' as source_fact,
        is_test_data
    from recommendation_base
    where decision_time_seconds is not null
    group by calendar_date, channel_key, channel_name, risk_profile_key, declared_profile, is_test_data

    union all

    select
        'cross_channel_continuity_rate' as metric_name,
        'continuity' as metric_group,
        'one linked cross-channel session pair per calendar day and channel direction' as metric_grain,
        'ratio' as metric_unit,
        cast(sum(case when continuity_flag = true then 1 else 0 end) as numeric(18, 8))
            / nullif(cast(count(*) as numeric(18, 8)), 0) as metric_value,
        cast(sum(case when continuity_flag = true then 1 else 0 end) as numeric(18, 8)) as numerator,
        cast(count(*) as numeric(18, 8)) as denominator,
        calendar_date,
        channel_key,
        channel_name,
        previous_channel_key,
        previous_channel_name,
        cast(null as {{ dbt.type_string() }}) as risk_profile_key,
        cast(null as {{ dbt.type_string() }}) as declared_profile,
        cast(null as {{ dbt.type_string() }}) as source,
        cast(null as {{ dbt.type_string() }}) as mode,
        'fato_interacao_conversacional' as source_fact,
        is_test_data
    from cross_channel_pairs
    group by
        calendar_date,
        channel_key,
        channel_name,
        previous_channel_key,
        previous_channel_name,
        is_test_data

    union all

    select
        'conversation_fallback_rate' as metric_name,
        'resilience' as metric_group,
        'one conversation session per calendar day, channel and declared profile' as metric_grain,
        'ratio' as metric_unit,
        cast(sum(case when fallback_used = true then 1 else 0 end) as numeric(18, 8))
            / nullif(cast(count(*) as numeric(18, 8)), 0) as metric_value,
        cast(sum(case when fallback_used = true then 1 else 0 end) as numeric(18, 8)) as numerator,
        cast(count(*) as numeric(18, 8)) as denominator,
        calendar_date,
        channel_key,
        channel_name,
        cast(null as {{ dbt.type_string() }}) as previous_channel_key,
        cast(null as {{ dbt.type_string() }}) as previous_channel_name,
        risk_profile_key,
        declared_profile,
        cast(null as {{ dbt.type_string() }}) as source,
        cast(null as {{ dbt.type_string() }}) as mode,
        'fato_interacao_conversacional' as source_fact,
        is_test_data
    from conversation_base
    group by calendar_date, channel_key, channel_name, risk_profile_key, declared_profile, is_test_data

    union all

    select
        'stale_yield_observation_rate' as metric_name,
        'data_freshness' as metric_group,
        'one yield snapshot per calendar day, source and mode' as metric_grain,
        'ratio' as metric_unit,
        cast(sum(case when is_stale = true then 1 else 0 end) as numeric(18, 8))
            / nullif(cast(count(*) as numeric(18, 8)), 0) as metric_value,
        cast(sum(case when is_stale = true then 1 else 0 end) as numeric(18, 8)) as numerator,
        cast(count(*) as numeric(18, 8)) as denominator,
        calendar_date,
        cast(null as {{ dbt.type_string() }}) as channel_key,
        cast(null as {{ dbt.type_string() }}) as channel_name,
        cast(null as {{ dbt.type_string() }}) as previous_channel_key,
        cast(null as {{ dbt.type_string() }}) as previous_channel_name,
        cast(null as {{ dbt.type_string() }}) as risk_profile_key,
        cast(null as {{ dbt.type_string() }}) as declared_profile,
        source,
        mode,
        'fato_yield_observacao' as source_fact,
        is_test_data
    from yield_base
    group by calendar_date, source, mode, is_test_data

    union all

    select
        'journey_coverage_rate' as metric_name,
        'journey' as metric_group,
        'one recommendation user cohort per calendar day' as metric_grain,
        'ratio' as metric_unit,
        cast(count(distinct covered.user_key) as numeric(18, 8))
            / nullif(cast(count(distinct journey.user_key) as numeric(18, 8)), 0) as metric_value,
        cast(count(distinct covered.user_key) as numeric(18, 8)) as numerator,
        cast(count(distinct journey.user_key) as numeric(18, 8)) as denominator,
        journey.calendar_date,
        cast(null as {{ dbt.type_string() }}) as channel_key,
        cast(null as {{ dbt.type_string() }}) as channel_name,
        cast(null as {{ dbt.type_string() }}) as previous_channel_key,
        cast(null as {{ dbt.type_string() }}) as previous_channel_name,
        cast(null as {{ dbt.type_string() }}) as risk_profile_key,
        cast(null as {{ dbt.type_string() }}) as declared_profile,
        cast(null as {{ dbt.type_string() }}) as source,
        cast(null as {{ dbt.type_string() }}) as mode,
        'fato_recomendacao + fato_interacao_conversacional' as source_fact,
        true as is_test_data
    from journey_users journey
    left join covered_journey_users covered
        on covered.calendar_date = journey.calendar_date
        and covered.user_key = journey.user_key
    group by journey.calendar_date
),
keyed_metrics as (
    select
        md5(
            metric_name || ':' ||
            cast(calendar_date as {{ dbt.type_string() }}) || ':' ||
            coalesce(channel_key, '') || ':' ||
            coalesce(previous_channel_key, '') || ':' ||
            coalesce(risk_profile_key, '') || ':' ||
            coalesce(source, '') || ':' ||
            coalesce(mode, '')
        ) as metric_key,
        metric_name,
        metric_group,
        metric_grain,
        metric_value,
        metric_unit,
        numerator,
        denominator,
        calendar_date,
        channel_key,
        channel_name,
        previous_channel_key,
        previous_channel_name,
        risk_profile_key,
        declared_profile,
        source,
        mode,
        source_fact,
        is_test_data
    from metric_rows
)

select *
from keyed_metrics
