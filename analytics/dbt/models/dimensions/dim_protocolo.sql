select
    md5(protocol_name) as protocol_key,
    protocol_name,
    category,
    primary_blockchain,
    cast(current_tvl_usd as numeric(18, 2)) as current_tvl_usd,
    cast(security_score as numeric(4, 2)) as security_score,
    audit_status,
    primary_auditor,
    cast(launch_year as integer) as launch_year,
    governance_token,
    cast(insurance_available as {{ dbt.type_boolean() }}) as insurance_available,
    cast(is_test_data as {{ dbt.type_boolean() }}) as is_test_data,
    'defillama' as source_system,
    'synthetic_fixture' as record_origin
from {{ ref('mvp_protocols') }}
where is_test_data = true
