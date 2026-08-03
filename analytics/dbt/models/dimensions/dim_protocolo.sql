with protocols as (
    select distinct protocol_name
    from {{ ref('stg_test_events') }}
    where protocol_name is not null
)

select
    md5(protocol_name) as protocol_key,
    protocol_name,
    'defillama' as source_system,
    'synthetic_fixture' as record_origin
from protocols

