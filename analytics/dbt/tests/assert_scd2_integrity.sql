with overlapping as (
    select a.user_key
    from {{ ref('dim_usuario') }} a
    join {{ ref('dim_usuario') }} b
      on a.user_pseudo_id = b.user_pseudo_id
     and a.user_key <> b.user_key
     and a.valid_from < coalesce(b.valid_to, timestamp '9999-12-31 00:00:00')
     and b.valid_from < coalesce(a.valid_to, timestamp '9999-12-31 00:00:00')
),
invalid_current as (
    select min(user_key) as user_key
    from {{ ref('dim_usuario') }}
    group by user_pseudo_id
    having sum(case when is_current = true then 1 else 0 end) <> 1
),
invalid_boundaries as (
    select user_key
    from {{ ref('dim_usuario') }}
    where valid_to is not null and valid_to <= valid_from
)

select user_key, 'overlap' as violation from overlapping
union all
select user_key, 'current_count' from invalid_current
union all
select user_key, 'invalid_boundary' from invalid_boundaries
