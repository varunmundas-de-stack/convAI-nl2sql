"""
Cube Query Builder - Pure Intent → Cube Query JSON translator.

This module converts a validated Intent object into a Cube Query JSON object.
It is a PURE FUNCTION with NO side effects.

DESIGN PRINCIPLES:
- Input is a validated Intent (not raw dict, not LLM output)
- Output is Cube Query JSON only (measures, dimensions, filters, timeDimensions, order, limit)
- Mapping is mechanical, not inferential (direct field translations)
- Translation is allowed, inference is not
- Missing fields are handled deterministically (omit or apply hard-coded default)
- No branching on business semantics
- No catalog access (catalog is not read here)
- No I/O, no network, no side effects
- Fully unit-testable (Intent A → exact Cube query JSON B)

This file does NOT:
- Call Cube
- Log
- Read environment variables
- Mutate state
- Inspect Cube schema
- Apply business rules
"""

from typing import Any

from backend.app.models.intent import Intent, IntentType


# =============================================================================
# HARD-CODED DEFAULTS (Explicit, documented, global)
# =============================================================================

DEFAULT_LIMIT = 1000
DEFAULT_TIMEZONE = "Asia/Kolkata"


# =============================================================================
# MAPPING TABLES (Canonical name → Cube member ID)
# =============================================================================

# Metric name → Cube measure ID
METRIC_TO_CUBE_MEASURE: dict[str, str] = {
    "transaction_count": "sales_fact.count",
    "total_quantity": "sales_fact.quantity",
    "distributor_count": "distributors.count",
    "outlet_count": "outlets.count",
    "sku_count": "skus.count",
    "territory_count": "territories.count",
}

# Dimension name → Cube dimension ID
DIMENSION_TO_CUBE_DIMENSION: dict[str, str] = {
    # Sales Fact dimensions
    "sales_type": "sales_fact.sales_type",
    "is_credit_sale": "sales_fact.is_credit",
    "sales_rep": "sales_fact.sales_rep_code",
    "invoice_number": "sales_fact.invoice_number",
    # SKU dimensions
    "brand": "skus.brand",
    "product_category": "skus.category",
    "product_sub_category": "skus.sub_category",
    "product_name": "skus.sku_name",
    "pack_size": "skus.pack_size",
    # Territory dimensions
    "region": "territories.region",
    "state": "territories.state",
    "zone": "territories.zone",
    "territory_name": "territories.territory_name",
    # Outlet dimensions
    "outlet_type": "outlets.outlet_type",
    "outlet_name": "outlets.outlet_name",
    "beat_code": "outlets.beat_code",
    # Distributor dimensions
    "distributor_name": "distributors.distributor_name",
    "distributor_type": "distributors.distributor_type",
}

# Time dimension name → Cube time dimension ID
TIME_DIMENSION_TO_CUBE: dict[str, str] = {
    "invoice_date": "sales_fact.invoice_date",
    "calendar_date": "date_dim.full_date",
}

# Intent filter operator → Cube filter operator
OPERATOR_TO_CUBE_OPERATOR: dict[str, str] = {
    "equals": "equals",
    "not_equals": "notEquals",
    "in": "equals",  # Cube uses 'equals' with array of values for 'in'
    "not_in": "notEquals",  # Cube uses 'notEquals' with array of values for 'not_in'
    "contains": "contains",
}

# Time window name → Cube relative date range string
TIME_WINDOW_TO_DATE_RANGE: dict[str, str] = {
    "today": "today",
    "yesterday": "yesterday",
    "last_7_days": "last 7 days",
    "last_30_days": "last 30 days",
    "last_90_days": "last 90 days",
    "month_to_date": "this month",
    "quarter_to_date": "this quarter",
    "year_to_date": "this year",
    "last_month": "last month",
    "last_quarter": "last quarter",
    "last_year": "last year",
}


# =============================================================================
# INTERNAL TRANSLATION FUNCTIONS (Pure, no side effects)
# =============================================================================

def _build_measures(intent: Intent) -> list[str]:
    """
    Translate intent.metric → Cube measures array.
    
    Always returns a single-element list (one metric per query).
    """
    cube_measure = METRIC_TO_CUBE_MEASURE.get(intent.metric)
    if cube_measure is None:
        # This should never happen if validation is correct upstream
        raise ValueError(f"Unknown metric: {intent.metric}")
    return [cube_measure]


def _build_dimensions(intent: Intent) -> list[str] | None:
    """
    Translate intent.group_by → Cube dimensions array.
    
    Returns None if no dimensions (omit from query).
    """
    if not intent.group_by:
        return None
    
    cube_dimensions = []
    for dim in intent.group_by:
        cube_dim = DIMENSION_TO_CUBE_DIMENSION.get(dim)
        if cube_dim is None:
            raise ValueError(f"Unknown dimension: {dim}")
        cube_dimensions.append(cube_dim)
    
    return cube_dimensions


def _build_filters(intent: Intent) -> list[dict[str, Any]] | None:
    """
    Translate intent.filters → Cube filters array.
    
    Cube filter format:
    {
        "member": "cube.dimension",
        "operator": "equals",
        "values": ["value1", "value2"]
    }
    
    Returns None if no filters (omit from query).
    """
    if not intent.filters:
        return None
    
    cube_filters = []
    for flt in intent.filters:
        cube_dim = DIMENSION_TO_CUBE_DIMENSION.get(flt.dimension)
        if cube_dim is None:
            raise ValueError(f"Unknown filter dimension: {flt.dimension}")
        
        cube_operator = OPERATOR_TO_CUBE_OPERATOR.get(flt.operator, "equals")
        
        # Cube always expects values as an array of strings
        if isinstance(flt.value, list):
            values = [str(v) for v in flt.value]
        else:
            values = [str(flt.value)]
        
        cube_filters.append({
            "member": cube_dim,
            "operator": cube_operator,
            "values": values,
        })
    
    return cube_filters


def _build_time_dimensions(intent: Intent) -> list[dict[str, Any]] | None:
    """
    Translate intent.time_dimension + time_range → Cube timeDimensions array.
    
    Cube timeDimension format:
    {
        "dimension": "cube.time_field",
        "dateRange": "last 30 days" OR ["2024-01-01", "2024-01-31"],
        "granularity": "month"  # Optional, omit for snapshot
    }
    
    Rules:
    - TREND intent: Always include granularity
    - SNAPSHOT intent: Omit granularity (filtering only)
    - If no time_dimension and no time_range: Return None (omit from query)
    """
    # If no time info at all, omit from query
    if intent.time_dimension is None and intent.time_range is None:
        return None
    
    # Build the timeDimension object
    time_dim_obj: dict[str, Any] = {}
    
    # Dimension (required if we have time_dimension)
    if intent.time_dimension:
        cube_time_dim = TIME_DIMENSION_TO_CUBE.get(intent.time_dimension.dimension)
        if cube_time_dim is None:
            raise ValueError(f"Unknown time dimension: {intent.time_dimension.dimension}")
        time_dim_obj["dimension"] = cube_time_dim
        
        # Granularity: only for TREND intent
        if intent.intent_type == IntentType.TREND:
            time_dim_obj["granularity"] = intent.time_dimension.granularity
    else:
        # If we have time_range but no time_dimension, use default time dimension
        # This happens for snapshot queries with time filters
        time_dim_obj["dimension"] = TIME_DIMENSION_TO_CUBE["invoice_date"]
    
    # Date range (if time_range is specified)
    if intent.time_range:
        if intent.time_range.window:
            # Named time window → Cube relative date range
            date_range = TIME_WINDOW_TO_DATE_RANGE.get(intent.time_range.window)
            if date_range is None:
                raise ValueError(f"Unknown time window: {intent.time_range.window}")
            time_dim_obj["dateRange"] = date_range
        elif intent.time_range.start_date and intent.time_range.end_date:
            # Explicit date range → Cube array format
            time_dim_obj["dateRange"] = [
                intent.time_range.start_date,
                intent.time_range.end_date,
            ]
    
    return [time_dim_obj]


def _build_order(intent: Intent) -> dict[str, str] | None:
    """
    Build Cube order object.
    
    Default behavior (if no order specified):
    - Order by the metric descending
    
    Returns None to use Cube's default ordering.
    """
    # Currently Intent doesn't have an order field
    # Apply default: order by metric desc
    cube_measure = METRIC_TO_CUBE_MEASURE.get(intent.metric)
    if cube_measure:
        return {cube_measure: "desc"}
    return None


def _build_limit(intent: Intent) -> int:
    """
    Build Cube limit.
    
    Default: DEFAULT_LIMIT (1000)
    """
    # Currently Intent doesn't have a limit field
    # Apply default
    return DEFAULT_LIMIT


# =============================================================================
# PUBLIC INTERFACE
# =============================================================================

def build_cube_query(intent: Intent) -> dict[str, Any]:
    """
    Build a Cube Query JSON from a validated Intent.
    
    This is the ONLY public function in this module.
    It is a PURE FUNCTION: same input always produces same output.
    
    Args:
        intent: A validated Intent object (NOT a raw dict)
        
    Returns:
        Cube Query JSON object ready for the Cube REST API
        
    Raises:
        ValueError: If intent contains unmappable values
                   (this should never happen if validation is correct)
    
    Example:
        >>> from backend.app.models.intent import Intent, IntentType
        >>> intent = Intent(
        ...     intent_type=IntentType.SNAPSHOT,
        ...     metric="total_quantity",
        ...     group_by=["region"],
        ...     time_range=TimeRange(window="last_30_days")
        ... )
        >>> query = build_cube_query(intent)
        >>> print(query)
        {
            "measures": ["sales_fact.quantity"],
            "dimensions": ["territories.region"],
            "timeDimensions": [{"dimension": "sales_fact.invoice_date", "dateRange": "last 30 days"}],
            "order": {"sales_fact.quantity": "desc"},
            "limit": 1000,
            "timezone": "Asia/Kolkata"
        }
    """
    query: dict[str, Any] = {}
    
    # measures (required)
    query["measures"] = _build_measures(intent)
    
    # dimensions (optional)
    dimensions = _build_dimensions(intent)
    if dimensions:
        query["dimensions"] = dimensions
    
    # filters (optional)
    filters = _build_filters(intent)
    if filters:
        query["filters"] = filters
    
    # timeDimensions (optional)
    time_dimensions = _build_time_dimensions(intent)
    if time_dimensions:
        query["timeDimensions"] = time_dimensions
    
    # order (optional, but we apply default)
    order = _build_order(intent)
    if order:
        query["order"] = order
    
    # limit (always included with default)
    query["limit"] = _build_limit(intent)
    
    # timezone (fixed system timezone)
    query["timezone"] = DEFAULT_TIMEZONE
    
    return query
