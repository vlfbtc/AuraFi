with hours as (
    select distinct date_trunc('hour', occurred_at) as hour_at
    from {{ ref('stg_test_events') }}
)

select
    md5(cast(hour_at as {{ dbt.type_string() }})) as time_key,
    hour_at,
    cast(hour_at as date) as calendar_date,
    extract(year from hour_at) as calendar_year,
    extract(month from hour_at) as calendar_month,
    extract(day from hour_at) as calendar_day,
    extract(hour from hour_at) as hour_of_day,
    'UTC' as timezone
from hours

