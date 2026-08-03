with blockchains as (
    select distinct blockchain_name
    from {{ ref('stg_test_events') }}
    where blockchain_name is not null
)

select
    md5(blockchain_name) as blockchain_key,
    blockchain_name,
    'synthetic_fixture' as record_origin
from blockchains

