select
    md5(asset_symbol) as asset_key,
    asset_symbol,
    full_name,
    asset_type,
    issuer,
    backing_type,
    peg_target,
    regulation,
    cast(market_cap_usd as numeric(18, 2)) as market_cap_usd,
    cast(launch_date as date) as launch_date,
    cast(is_test_data as {{ dbt.type_boolean() }}) as is_test_data,
    'synthetic_fixture' as record_origin
from {{ ref('mvp_assets') }}
where is_test_data = true
