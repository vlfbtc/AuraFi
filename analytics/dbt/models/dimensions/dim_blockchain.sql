select
    md5(blockchain_name) as blockchain_key,
    blockchain_name,
    blockchain_type,
    consensus,
    native_token,
    cast(average_gas_fee_usd as numeric(8, 4)) as average_gas_fee_usd,
    cast(average_tps as integer) as average_tps,
    cast(finality_seconds as integer) as finality_seconds,
    cast(mainnet_date as date) as mainnet_date,
    cast(official_bridge as {{ dbt.type_boolean() }}) as official_bridge,
    cast(is_test_data as {{ dbt.type_boolean() }}) as is_test_data,
    'synthetic_fixture' as record_origin
from {{ ref('mvp_blockchains') }}
where is_test_data = true
