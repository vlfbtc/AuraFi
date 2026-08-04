with sessions as (
    select f.*, c.channel_name
    from {{ ref('fato_interacao_conversacional') }} f
    join {{ ref('dim_canal') }} c on c.channel_key = f.channel_key
),
violations as (
    select current_session.conversation_key
    from sessions current_session
    left join sessions previous_session
      on previous_session.session_id = current_session.previous_session_id
     and previous_session.user_key = current_session.user_key
    where
        (current_session.previous_session_id is not null and previous_session.session_id is null)
        or (current_session.continuity_flag = true and current_session.previous_session_id is null)
        or (
            current_session.previous_session_id is not null
            and current_session.resumption_time_seconds
                <> extract(epoch from current_session.session_started_at - previous_session.session_ended_at)
        )
)

select * from violations
