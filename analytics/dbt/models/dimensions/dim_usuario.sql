with users as (
    select distinct
        user_pseudo_id,
        user_version,
        user_valid_from,
        user_valid_to
    from {{ ref('stg_test_events') }}
)

select
    md5(user_pseudo_id || ':' || cast(user_version as {{ dbt.type_string() }})) as user_key,
    user_pseudo_id,
    user_version,
    user_valid_from as valid_from,
    user_valid_to as valid_to,
    case when user_valid_to is null then true else false end as is_current,
    'synthetic_fixture' as record_origin
from users

