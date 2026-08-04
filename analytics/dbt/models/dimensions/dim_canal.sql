select
    md5(channel_name || ':' || adapter) as channel_key,
    channel_name,
    channel_type,
    adapter,
    adapter_version,
    cast(launch_date as date) as launch_date,
    cast(push_supported as {{ dbt.type_boolean() }}) as push_supported,
    cast(attachment_supported as {{ dbt.type_boolean() }}) as attachment_supported,
    cast(estimated_message_cost_usd as numeric(8, 5)) as estimated_message_cost_usd,
    cast(simulated as {{ dbt.type_boolean() }}) as simulated,
    cast(is_test_data as {{ dbt.type_boolean() }}) as is_test_data,
    'synthetic_fixture' as record_origin
from {{ ref('mvp_channels') }}
where is_test_data = true
