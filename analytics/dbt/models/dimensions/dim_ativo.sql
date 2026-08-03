with assets as (
    select distinct asset_symbol, asset_type
    from {{ ref('stg_test_events') }}
    where asset_symbol is not null
)

select
    md5(asset_symbol) as asset_key,
    asset_symbol,
    asset_type,
    'synthetic_fixture' as record_origin
from assets

