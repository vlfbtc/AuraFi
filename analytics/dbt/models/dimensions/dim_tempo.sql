{{ config(materialized='table') }}

/* PostgreSQL MVP date spine: one row per UTC hour from 2020 through 2040. */
with hours as (
    select generate_series(
        timestamp '2020-01-01 00:00:00',
        timestamp '2040-12-31 23:00:00',
        interval '1 hour'
    ) as hour_at
),
calendar as (
    select
        hour_at,
        cast(hour_at as date) as calendar_date,
        extract(isodow from hour_at) as iso_day_of_week,
        extract(month from hour_at) as month_number,
        extract(hour from hour_at) as hour_of_day
    from hours
)

select
    cast(to_char(hour_at, 'YYYYMMDDHH24') as bigint) as time_key,
    hour_at,
    calendar_date,
    cast(hour_of_day as smallint) as hour_of_day,
    case
        when hour_of_day < 6 then 'madrugada'
        when hour_of_day < 12 then 'manha'
        when hour_of_day < 18 then 'tarde'
        else 'noite'
    end as day_period,
    case iso_day_of_week
        when 1 then 'segunda'
        when 2 then 'terca'
        when 3 then 'quarta'
        when 4 then 'quinta'
        when 5 then 'sexta'
        when 6 then 'sabado'
        else 'domingo'
    end as weekday_name,
    case when iso_day_of_week between 1 and 5 then true else false end as is_weekday,
    case
        when iso_day_of_week between 1 and 5
         and to_char(calendar_date, 'MM-DD') not in (
            '01-01', '04-21', '05-01', '09-07', '10-12',
            '11-02', '11-15', '11-20', '12-25'
         ) then true else false
    end as is_business_day,
    case
        when to_char(calendar_date, 'MM-DD') in (
            '01-01', '04-21', '05-01', '09-07', '10-12',
            '11-02', '11-15', '11-20', '12-25'
        ) then true else false
    end as is_fixed_national_holiday,
    cast(month_number as smallint) as calendar_month,
    case month_number
        when 1 then 'janeiro' when 2 then 'fevereiro' when 3 then 'marco'
        when 4 then 'abril' when 5 then 'maio' when 6 then 'junho'
        when 7 then 'julho' when 8 then 'agosto' when 9 then 'setembro'
        when 10 then 'outubro' when 11 then 'novembro' else 'dezembro'
    end as month_name,
    cast(extract(quarter from hour_at) as smallint) as calendar_quarter,
    case when month_number <= 6 then 1 else 2 end as calendar_semester,
    cast(extract(year from hour_at) as smallint) as calendar_year,
    to_char(hour_at, 'YYYY-MM') as year_month,
    'UTC' as timezone
from calendar
