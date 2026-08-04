{{ config(materialized='view') }}

with sessions as (
    select
        f.*,
        t.calendar_date,
        c.channel_name
    from {{ ref('fato_interacao_conversacional') }} f
    join {{ ref('dim_tempo') }} t on t.time_key = f.time_key
    join {{ ref('dim_canal') }} c on c.channel_key = f.channel_key
    where f.is_test_data = true
),
linked as (
    select
        current_session.calendar_date,
        previous_session.channel_key as previous_channel_key,
        previous_session.channel_name as previous_channel_name,
        current_session.channel_key,
        current_session.channel_name,
        current_session.continuity_flag,
        current_session.resumption_time_seconds,
        current_session.context_loss_events
    from sessions current_session
    join sessions previous_session
        on previous_session.session_id = current_session.previous_session_id
        and previous_session.user_key = current_session.user_key
    where previous_session.channel_key <> current_session.channel_key
)

select
    calendar_date,
    previous_channel_key,
    previous_channel_name,
    channel_key,
    channel_name,
    count(*) as cross_channel_handoff_count,
    sum(case when continuity_flag = true then 1 else 0 end) as successful_resumption_count,
    cast(sum(case when continuity_flag = true then 1 else 0 end) as numeric(18, 8))
        / nullif(cast(count(*) as numeric(18, 8)), 0) as cross_channel_handoff_rate,
    avg(resumption_time_seconds) as average_session_resumption_seconds,
    sum(coalesce(context_loss_events, 0)) as context_loss_events,
    cast(sum(case when coalesce(context_loss_events, 0) > 0 then 1 else 0 end) as numeric(18, 8))
        / nullif(cast(count(*) as numeric(18, 8)), 0) as context_loss_handoff_rate,
    true as is_test_data
from linked
group by
    calendar_date,
    previous_channel_key,
    previous_channel_name,
    channel_key,
    channel_name
