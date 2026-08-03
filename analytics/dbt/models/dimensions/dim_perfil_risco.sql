with profiles as (
    select distinct
        risk_profile,
        risk_status,
        risk_version,
        risk_source,
        risk_declared_at
    from {{ ref('stg_test_events') }}
)

select
    md5(risk_profile || ':' || cast(risk_version as {{ dbt.type_string() }})) as risk_profile_key,
    risk_profile as declared_profile,
    risk_status as status,
    risk_version as version,
    risk_source as source,
    risk_declared_at as declared_at,
    'synthetic_fixture' as record_origin
from profiles

