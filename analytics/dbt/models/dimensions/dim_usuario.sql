with users as (
    select *
    from {{ ref('mvp_users') }}
    where is_test_data = true
)

select
    md5(user_pseudo_id || ':' || cast(user_version as {{ dbt.type_string() }})) as user_key,
    user_pseudo_id,
    cast(user_version as integer) as user_version,
    age_band,
    gender,
    state_code,
    city_size,
    plan,
    cast(registered_on as date) as registered_on,
    acquisition_channel,
    cast(wallet_connected as {{ dbt.type_boolean() }}) as wallet_connected,
    crypto_experience,
    cast(valid_from as {{ dbt.type_timestamp() }}) as valid_from,
    cast(valid_to as {{ dbt.type_timestamp() }}) as valid_to,
    cast(is_current as {{ dbt.type_boolean() }}) as is_current,
    cast(is_test_data as {{ dbt.type_boolean() }}) as is_test_data,
    'synthetic_fixture' as record_origin
from users
