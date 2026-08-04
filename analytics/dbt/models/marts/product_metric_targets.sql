{{ config(materialized='view') }}

select
    cast(target_year as integer) as target_year,
    metric_name,
    target_operator,
    cast(target_value as numeric(18, 4)) as target_value,
    target_unit,
    cast(is_test_data as {{ dbt.type_boolean() }}) as is_test_data
from {{ ref('mvp_product_targets') }}
where is_test_data = true
