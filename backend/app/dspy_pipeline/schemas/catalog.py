# =============================================================================
# CATALOG CONSTANTS (RULE P4)
# Single source of truth for all catalog validation
# =============================================================================

# Metrics available in the catalog
METRICS_CATALOG = [
    {
        "name": "count",
        "description": "Number of sales transactions",
        "aggregation": "count",
    },
    {
        "name": "net_value",
        "description": "Total net sales value after discounts",
        "aggregation": "sum",
    },
    {
        "name": "gross_value",
        "description": "Total gross sales value before discounts",
        "aggregation": "sum",
    },
    {
        "name": "tax_value",
        "description": "Total tax amount",
        "aggregation": "sum",
    },
    {
        "name": "billed_qty",
        "description": "Total sales quantity (units/volume sold)",
        "aggregation": "sum",
    },
]

CATALOG_METRICS = frozenset(m["name"] for m in METRICS_CATALOG)

# Dimensions available in both PRIMARY and SECONDARY
'''
COMMON_DIMENSIONS = frozenset({
    "city", "state", "zone",
    "distributor_code", "distributor_name",
    "brand", "category", "sub_category", "pack_size", "sku_code",
    # Star schema hierarchy dimensions
    "geo_zone", "geo_state", "geo_city", "geo_territory", "geo_level",
    "prod_category", "prod_sub_category", "prod_brand", "prod_sku_code",
    "org_zsm", "org_asm", "org_so",
    "period_year", "period_quarter", "period_month", "period_week",
})
'''
##newly added 
COMMON_DIMENSIONS = frozenset({
    "city", "state", "zone",
    "distributor_code", "distributor_name",
    "brand", "category", "sub_category", "pack_size", "sku_code",
    # Star schema semantic aliases
    "geo_zone", "geo_state", "geo_city", "geo_territory", "geo_level",
    "prod_category", "prod_sub_category", "prod_brand", "prod_sku_code",
    "org_zsm", "org_asm", "org_so",
    "period_year", "period_quarter", "period_month", "period_week",
    # Fully-qualified cube paths (post-normalization)
    "dim_geography.zone", "dim_geography.state", "dim_geography.city",
    "dim_geography.territory", "dim_geography.geo_level",
    "dim_product.category", "dim_product.sub_category", "dim_product.brand",
    "dim_product.sku_code", "dim_product.pack_size", "dim_product.product_desc",
    "dim_period.fiscal_year", "dim_period.fiscal_quarter",
    "dim_period.fiscal_month", "dim_period.fiscal_week",
    "dim_salesorg.zsm_name", "dim_salesorg.asm_name", "dim_salesorg.so_code",
    "dim_customer.channel_type", "dim_salesorg.so_code",
})

# Dimensions only available in SECONDARY scope
SECONDARY_ONLY_DIMENSIONS = frozenset({
    "retailer_code", "retailer_name", "retailer_type",
    "route_code", "route_name",
    "dim_channel_type",
})

# All valid dimensions
ALL_DIMENSIONS = COMMON_DIMENSIONS | SECONDARY_ONLY_DIMENSIONS

# Time windows from catalog
TIME_WINDOWS = frozenset({
    "today", "yesterday",
    "last_7_days", "last_30_days", "last_90_days",
    "month_to_date", "quarter_to_date", "year_to_date",
    "last_month", "last_quarter", "last_year",
    "all_time",
})

# Time granularities
TIME_GRANULARITIES = frozenset({
    "day", "week", "month", "quarter", "year"
})

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================
 
def get_valid_dimensions_for_scope(scope: str) -> frozenset[str]:
    """Returns the set of valid dimensions for a given sales scope."""
    return COMMON_DIMENSIONS if scope == "PRIMARY" else ALL_DIMENSIONS
  
def is_valid_time_window(window: str) -> bool:
    return window in TIME_WINDOWS