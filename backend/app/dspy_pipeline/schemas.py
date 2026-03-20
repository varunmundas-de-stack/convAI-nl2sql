"""
Pydantic schemas for DSPy pipeline intermediate results and catalog constants.

Following RULE P1: One Pydantic model per agent output
Following RULE P4: Catalog constants in schemas.py, import everywhere
"""

from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, ConfigDict

# =============================================================================
# CATALOG CONSTANTS (RULE P4)
# Single source of truth for all catalog validation
# =============================================================================

# Metrics available in the catalog
CATALOG_METRICS = frozenset([
    "count", "net_value", "gross_value", "tax_value", "billed_qty"
])

# Metric aliases for user-friendly terms
METRIC_ALIASES = {
    "volume_qty": "billed_qty",
    "quantity": "billed_qty",
    "transactions": "count",
    "sales": "net_value",
    "revenue": "net_value",
    "turnover": "net_value"
}

# Dimensions available in both PRIMARY and SECONDARY
COMMON_DIMENSIONS = frozenset([
    "city", "state", "zone", "distributor_code", "distributor_name",
    "brand", "category", "sub_category", "pack_size", "sku_code", "product_desc"
])

# Dimensions only available in SECONDARY scope
SECONDARY_ONLY_DIMENSIONS = frozenset([
    "retailer_code", "retailer_name", "retailer_type", "route_code", "route_name"
])

# All valid dimensions
ALL_DIMENSIONS = COMMON_DIMENSIONS | SECONDARY_ONLY_DIMENSIONS

# Dimension aliases
DIMENSION_ALIASES = {
    "territory": "zone",
    "region": "zone",
    "distributor": "distributor_name",
    "retailer": "retailer_name",
    "product": "product_desc"
}

# Time windows from catalog
TIME_WINDOWS = frozenset([
    "today", "yesterday", "last_7_days", "last_30_days", "last_90_days",
    "month_to_date", "quarter_to_date", "year_to_date",
    "last_month", "last_quarter", "last_year", "all_time"
])

# Time granularities
TIME_GRANULARITIES = frozenset([
    "day", "week", "month", "quarter", "year"
])

# Geographic hierarchy (shallow → deep)
GEO_HIERARCHY = ["zone", "state", "city"]

# Product hierarchy (shallow → deep)
PRODUCT_HIERARCHY = ["category", "sub_category", "brand", "sku_code"]

# =============================================================================
# INTERMEDIATE SCHEMAS (RULE P1)
# One Pydantic model per agent output
# =============================================================================

class ClassifiedQuery(BaseModel):
    """
    Output of ClassifierAgent - terms labeled with semantic roles.

    Maps tokens/phrases to their semantic categories for downstream agents.
    """
    query_text: str = Field(..., description="Original query text")

    # Semantic labels for key terms
    metric_terms: List[str] = Field(
        default_factory=list,
        description="Terms identified as metrics (sales, quantity, revenue, etc.)"
    )

    dimension_terms: List[str] = Field(
        default_factory=list,
        description="Terms identified as dimensions (zone, brand, category, etc.)"
    )

    filter_terms: List[str] = Field(
        default_factory=list,
        description="Terms that indicate filter conditions (in, equals, contains)"
    )

    time_expressions: List[str] = Field(
        default_factory=list,
        description="Time-related expressions (last month, daily, trend)"
    )

    ranking_indicators: List[str] = Field(
        default_factory=list,
        description="Ranking/ordering terms (top, bottom, highest, lowest)"
    )

    scope_indicators: List[str] = Field(
        default_factory=list,
        description="Sales scope indicators (primary, secondary)"
    )

    comparison_indicators: List[str] = Field(
        default_factory=list,
        description="Comparison terms (vs, compared to, growth)"
    )

    model_config = ConfigDict(extra="forbid")


class ScopeTimeResult(BaseModel):
    """
    Output of ScopeTimeAgent - resolved sales scope and time specification.
    """
    sales_scope: Literal["PRIMARY", "SECONDARY"] = Field(
        ...,
        description="Resolved sales scope based on query context"
    )

    time_window: Optional[str] = Field(
        None,
        description="Named time window if matches catalog exactly"
    )

    start_date: Optional[str] = Field(
        None,
        description="Explicit start date in YYYY-MM-DD format"
    )

    end_date: Optional[str] = Field(
        None,
        description="Explicit end date in YYYY-MM-DD format"
    )

    granularity: Optional[Literal["day", "week", "month", "quarter", "year"]] = Field(
        None,
        description="Time grouping granularity for trend queries"
    )

    has_time_constraint: bool = Field(
        ...,
        description="Whether any time constraint was specified"
    )

    model_config = ConfigDict(extra="forbid")


class MetricsResult(BaseModel):
    """
    Output of MetricsAgent - validated metrics list.
    """
    metrics: List[str] = Field(
        ...,
        min_length=1,
        description="Catalog-validated metric names"
    )

    aggregations: List[Literal["sum", "count", "avg"]] = Field(
        ...,
        description="Aggregation function for each metric (parallel to metrics)"
    )

    metric_confidence: Dict[str, float] = Field(
        default_factory=dict,
        description="Confidence score for each metric identification (0.0-1.0)"
    )

    model_config = ConfigDict(extra="forbid")


class FilterCondition(BaseModel):
    """Individual filter condition."""
    dimension: str = Field(..., description="Dimension to filter on")
    operator: Literal["equals", "not_equals", "in", "not_in", "contains"] = Field(
        default="equals", description="Filter operator"
    )
    value: str | List[str] = Field(..., description="Filter value(s)")

    model_config = ConfigDict(extra="forbid")


class DimensionsResult(BaseModel):
    """
    Output of DimensionsAgent - dimensions, filters, and context operations.
    """
    group_by: Optional[List[str]] = Field(
        None,
        description="Dimensions for grouping results"
    )

    filters: Optional[List[FilterCondition]] = Field(
        None,
        description="Filter conditions to apply"
    )

    context_operation: Optional[Literal["MINIMAL_MESSAGE", "DRILL_DOWN", "ALSO_BY", "REPLACE_BY"]] = Field(
        None,
        description="Type of context operation applied"
    )

    hierarchy_level: Optional[str] = Field(
        None,
        description="Current hierarchy level (for drill operations)"
    )

    model_config = ConfigDict(extra="forbid")


class PostProcessingSpec(BaseModel):
    """Post-processing operations specification."""
    ranking_enabled: bool = Field(default=False, description="Whether ranking is requested")
    ranking_order: Optional[Literal["asc", "desc"]] = Field(None, description="Ranking order")
    ranking_limit: Optional[int] = Field(None, description="Number of results to return")

    comparison_type: Optional[Literal["period", "dimension"]] = Field(
        None, description="Type of comparison requested"
    )
    comparison_window: Optional[str] = Field(None, description="Comparison time window")

    derived_metric: Optional[str] = Field(None, description="Derived metric to calculate")

    model_config = ConfigDict(extra="forbid")

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_valid_metrics_for_scope(scope: str) -> frozenset[str]:
    """Get valid metrics for a given sales scope."""
    # All metrics are available for both scopes in this catalog
    return CATALOG_METRICS


def get_valid_dimensions_for_scope(scope: str) -> frozenset[str]:
    """Get valid dimensions for a given sales scope."""
    if scope == "PRIMARY":
        return COMMON_DIMENSIONS
    else:  # SECONDARY
        return ALL_DIMENSIONS


def resolve_metric_alias(term: str) -> str:
    """Resolve metric alias to canonical name."""
    return METRIC_ALIASES.get(term.lower(), term)


def resolve_dimension_alias(term: str) -> str:
    """Resolve dimension alias to canonical name."""
    return DIMENSION_ALIASES.get(term.lower(), term)


def is_valid_time_window(window: str) -> bool:
    """Check if a time window is valid."""
    return window in TIME_WINDOWS


def get_hierarchy_next_level(current_dim: str) -> Optional[str]:
    """Get the next level in hierarchy for drill-down operations."""
    if current_dim in GEO_HIERARCHY:
        idx = GEO_HIERARCHY.index(current_dim)
        return GEO_HIERARCHY[idx + 1] if idx < len(GEO_HIERARCHY) - 1 else None
    elif current_dim in PRODUCT_HIERARCHY:
        idx = PRODUCT_HIERARCHY.index(current_dim)
        return PRODUCT_HIERARCHY[idx + 1] if idx < len(PRODUCT_HIERARCHY) - 1 else None
    return None