with channels as (
    select distinct channel_name, channel_adapter, channel_simulated
    from {{ ref('stg_test_events') }}
)

select
    md5(channel_name || ':' || channel_adapter) as channel_key,
    channel_name,
    channel_adapter as adapter,
    channel_simulated as simulated,
    'synthetic_fixture' as record_origin
from channels

