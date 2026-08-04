with time_coverage as (
    select 'dim_tempo' as dimension_name
    from {{ ref('dim_tempo') }}
    having count(*) <> 184104
       or min(hour_at) <> timestamp '2020-01-01 00:00:00'
       or max(hour_at) <> timestamp '2040-12-31 23:00:00'
),
risk_coverage as (
    select 'dim_perfil_risco' as dimension_name
    from {{ ref('dim_perfil_risco') }}
    having count(*) <> 3
),
channel_coverage as (
    select 'dim_canal' as dimension_name
    from {{ ref('dim_canal') }}
    having count(*) < 4
       or sum(case when channel_name = 'web_widget' then 1 else 0 end) <> 1
       or sum(case when channel_name = 'ios_app' then 1 else 0 end) <> 1
       or sum(case when channel_name = 'whatsapp_business' then 1 else 0 end) <> 1
       or sum(case when channel_name = 'telegram' then 1 else 0 end) <> 1
)

select * from time_coverage
union all
select * from risk_coverage
union all
select * from channel_coverage
