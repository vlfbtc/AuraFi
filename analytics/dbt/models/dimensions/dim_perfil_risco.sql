select
    md5(profile_code) as risk_profile_key,
    risk_profile as declared_profile,
    profile_code,
    description,
    cast(max_loss_tolerance_percent as numeric(5, 2)) as max_loss_tolerance_percent,
    cast(max_healthy_apy_percent as numeric(5, 2)) as max_healthy_apy_percent,
    cast(minimum_tvl_usd as numeric(18, 2)) as minimum_tvl_usd,
    cast(audit_required as {{ dbt.type_boolean() }}) as audit_required,
    cast(is_test_data as {{ dbt.type_boolean() }}) as is_test_data,
    'synthetic_fixture' as record_origin
from {{ ref('mvp_risk_profiles') }}
where is_test_data = true
