"""
Pydantic schemas for DSPy pipeline intermediate results and catalog constants.

Following RULE P1: One Pydantic model per agent output
Following RULE P4: Catalog constants in schemas.py, import everywhere
"""
from __future__ import annotations
from typing import List, Optional, Dict, Any, Literal, Union
from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator

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
COMMON_DIMENSIONS = frozenset({
    "city", "state", "zone",
    "distributor_code", "distributor_name",
    "brand", "category", "sub_category", "pack_size", "sku_code"
})

# Dimensions only available in SECONDARY scope
SECONDARY_ONLY_DIMENSIONS = frozenset({
    "retailer_code", "retailer_name", "retailer_type",
    "route_code", "route_name"
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
# QUERY DECOMPOSITION — Before Agent Pipeline
# =============================================================================

class SubQueryItem(BaseModel):
    """Represents a decomposed sub-query."""
    index: int = Field(description="Position in original compound query")
    text: str = Field(description="Isolated sub-query text")
    intent_hint: Optional[str] = Field(default=None, description="Suggested intent type")
    dependencies: List[int] = Field(default_factory=list, description="Indices of sub-queries this depends on")

    model_config = ConfigDict(extra="forbid")


class DecomposedQuery(BaseModel):
    """Output of QueryDecomposerModule."""
    original_query: str
    sub_queries: List[SubQueryItem]
    is_compound: bool = Field(description="True if query was split, False if single query")

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# AGENT 1 OUTPUT — ClassifiedQuery
# =============================================================================
 
# Closed role taxonomy. Every term gets exactly one role.
TermRole = Literal[
    "METRIC",           # net_value, billed_qty, count, gross_value, tax_value
    "DIMENSION",        # zone, brand, category, state, distributor_name...
    "TIME_RANGE",       # last month, last 30 days, Q1 2024, this quarter
    "TIME_GRANULARITY", # daily, weekly, monthly, quarterly, yearly
    "FILTER_VALUE",     # Gold Flake, North-1, Kirana, 5 kg, Oil
    "RANKING",          # top 5, bottom 3, highest, lowest, best, worst
    "SCOPE",            # Primary, Secondary
    "COMPARISON",       # vs, compared to, versus, growth, change
    "TREND",            # trend, trending, over time, trajectory
]
 
QueryIntent = Literal[
    "SNAPSHOT",        # single aggregated value, no dimension breakdown (was KPI)
    "DISTRIBUTION",    # breakdown by one or more dimensions
    "RANKING",         # top/bottom N with a grouping dimension
    "TREND",           # metric over time requiring granularity
    "COMPARISON",      # current period vs another period or dimension
    "DRILL_DOWN",      # navigating deeper into a hierarchy from previous context
    "MINIMAL_MESSAGE", # bare dimension or metric name only — context-dependent
    "STRUCTURAL",      # asking what entities exist, not how they performed
]
 
 
class ClassifiedTerm(BaseModel):
    
    term: str = Field(
        description="Exact word or phrase as it appears in the query."
    )
    role: TermRole = Field(
        description="Semantic role this term plays in the query."
    )
    catalog_match: Optional[str] = Field(
    default=None,
    description=(
        "The resolved canonical column name from the data catalog. "
        "Apply known aliases and synonyms to map user-facing terms to their "
        "standardized catalog equivalents. Null if the term has no direct "
        "catalog entry (e.g. analytical intents like ranking, trends, or comparisons)."
        )
    )
    scope: Optional[Literal["PRIMARY", "SECONDARY"]] = Field(
        default=None,
        description="The scope implied by this term (e.g., 'secondary sales' implies SECONDARY). Null if not applicable."
    )
 
    model_config = ConfigDict(extra="forbid")
 
 
class FilterHint(BaseModel):
    """
    A specific filter value paired with the dimension it qualifies.
    """
    dimension: str = Field(
        description=(
            "Catalog dimension this value qualifies. "
            "Examples: brand→'Gold Flake', zone→'North-1', "
            "category→'Oil', pack_size→'5 kg', retailer_type→'Kirana'."
        )
    )
    value: str = Field(
        description="Exact filter value as mentioned in the query."
    )
 
    model_config = ConfigDict(extra="forbid")
 
 
class ClassifiedQuery(BaseModel):
    """
    Output of ClassifierAgent. Passed to all 5 downstream agents.

    """
 
    original_query: str = Field(
        description="Original raw query, stored for downstream reference and logging."
    )
 
    classified_terms: list[ClassifiedTerm] = Field(
        description=(
            "Every meaningful term labelled with its role and catalog match. "
            "Include all terms that carry intent. Skip stop words and filler."
        )
    )
 
    query_intent: QueryIntent = Field(
        description=(
            "Single dominant intent. Resolution priority (highest first): "
            "MINIMAL_MESSAGE if query is only a bare dimension or metric name. "
            "STRUCTURAL if asking what entities exist (which brands, what zones). "
            "TREND if any TREND-role term is present. "
            "COMPARISON if any COMPARISON-role term is present. "
            "RANKING if RANKING signal present with a grouping dimension. "
            "DRILL_DOWN if navigating deeper into a previous result. "
            "DISTRIBUTION if grouping by dimension, no ranking or trend. "
            "KPI if measuring a value with no grouping dimension."
        )
    )
 
    filter_hints: list[FilterHint] = Field(
        default_factory=list,
        description=(
            "Each specific filter value paired with its dimension. "
            "Empty list if no filter values are present in the query."
        )
    )
 
    explicit_scope: Optional[Literal["PRIMARY", "SECONDARY"]] = Field(
        default=None,
        description=(
            "Null if scope not stated — ScopeAgent will inherit from context. "
            "Set only when query literally contains 'Primary' or 'Secondary'."
        )
    )
 
    model_config = ConfigDict(extra="forbid")
 
 
# =============================================================================
# AGENT 2 OUTPUT — ScopeResult
# =============================================================================
 
class ScopeResult(BaseModel):
    """Output of ScopeAgent."""
 
    sales_scope: Literal["PRIMARY", "SECONDARY"] = Field(
        description="Resolved sales scope. SECONDARY is the default."
    )
 
    model_config = ConfigDict(extra="forbid")
 
 
# =============================================================================
# AGENT 3 OUTPUT — TimeResult
# =============================================================================
 
class TimeResult(BaseModel):
    """
    Output of TimeAgent.
    """
 
    time_window: Optional[Literal[
        "today", "yesterday",
        "last_7_days", "last_30_days", "last_90_days",
        "month_to_date", "quarter_to_date", "year_to_date",
        "last_month", "last_quarter", "last_year",
        "all_time",
    ]] = Field(
        default=None,
        description="Named time window — use only if phrase matches catalog exactly."
    )
 
    start_date: Optional[str] = Field(
        default=None,
        description="Explicit start date YYYY-MM-DD. Set when no catalog window matches."
    )
 
    end_date: Optional[str] = Field(
        default=None,
        description="Explicit end date YYYY-MM-DD. Set when no catalog window matches."
    )
 
    granularity: Optional[Literal["day", "week", "month", "quarter", "year"]] = Field(
        default=None,
        description=(
            "Time grouping frequency. Set ONLY for TREND or COMPARISON intents. "
            "Null for KPI, DISTRIBUTION, RANKING. "
            "Default to 'week' when intent is TREND but no granularity is stated."
        )
    )
 
    @model_validator(mode="after")
    def window_xor_dates(self) -> "TimeResult":
        """Window and explicit dates must never both be set. Explicit dates take priority."""
        
        # If both start & end dates exist → remove time_window
        if self.start_date and self.end_date and self.time_window:
            self.time_window = None

        return self
 
    @property
    def has_time_constraint(self) -> bool:
        """Derived — True if any time constraint is present."""
        return any([self.time_window, self.start_date, self.end_date])
 
    model_config = ConfigDict(extra="forbid")
 
 
# =============================================================================
# AGENT 4 OUTPUT — MetricsResult
# =============================================================================
 
class MetricsResult(BaseModel):
    """
    Output of MetricsAgent.

    """
 
    metrics: List[MetricSpec] = Field(
        min_length=1,
        description=(
            "Canonical metric names from CATALOG_METRICS. "
            "Must contain at least one. Default to ['net_value'] if ambiguous."
        )
    )
 
    aggregations: List[Literal["sum", "count", "avg"]] = Field(
        description=(
            "Aggregation per metric, parallel to metrics list. "
            "count→'count', all others→'sum'."
        )
    )
 
    model_config = ConfigDict(extra="forbid")
 
 
# =============================================================================
# AGENT 5 OUTPUT — DimensionsResult
# =============================================================================
 
class FilterCondition(BaseModel):
    """
    A single filter condition on a dimension.
    """
 
    dimension: str = Field(
        description="Canonical catalog dimension name to filter on."
    )
    operator: Literal["equals", "not_equals", "in", "not_in", "contains"] = Field(
        description=(
            "Filter operator. Single value → 'equals'. "
            "Multiple values → 'in'. Exclusion → 'not_equals'/'not_in'."
        )
    )
    value: Union[str, List[str]] = Field(
        description="Filter value(s). Use List[str] only with 'in'/'not_in' operators."
    )
 
    model_config = ConfigDict(extra="forbid")
 
 
class DimensionsResult(BaseModel):
    """
    Output of DimensionsAgent.
    """
 
    group_by: Optional[List[str]] = Field(
        default=None,
        description=(
            "Canonical dimension names for grouping. Null if no grouping. "
            "Max 2 dimensions. Never include 'invoice_date'. "
            "Max 1 dimension per hierarchy axis (geo: zone/state/city, "
            "product: category/sub_category/brand/sku_code)."
        )
    )
    
    @field_validator("group_by", mode="before")
    @classmethod
    def ensure_group_by_is_list(cls, v):
        if isinstance(v, str):
            return [v]
        return v
 
    filters: Optional[List[FilterCondition]] = Field(
        default=None,
        description="Filter conditions to apply. Null if no filters."
    )
 
    model_config = ConfigDict(extra="forbid")
 
 
# =============================================================================
# ASSEMBLER OUTPUT — Final Intent
# =============================================================================
 
class RankingConfig(BaseModel):
    """Ranking specification within post-processing."""
    enabled: bool
    order: Literal["asc", "desc"]
    limit: Optional[int] = Field(
        default=None,
        description="Number of results. Default to 10 if not specified."
    )
 
    model_config = ConfigDict(extra="forbid")
 
 
class ComparisonConfig(BaseModel):
    """Comparison specification within post-processing."""
    type: Literal["period", "dimension"]
    comparison_window: Optional[str] = Field(
    default=None,
    description="Relative time window for comparison. Null if comparing explicit date ranges. Must be a valid TIME_WINDOWS value if set.",
    )

    @field_validator("comparison_window")
    @classmethod
    def validate_window(cls, v):
        if v is not None and v not in TIME_WINDOWS:
            return None  # coerce invalid values to null instead of crashing
        return v
 
    model_config = ConfigDict(extra="forbid")
 
 
class PostProcessingResult(BaseModel):
    """
    Post-processing specification.
    """
 
    ranking: Optional[RankingConfig] = Field(
        default=None,
        description="Null if no ranking requested, or if group_by is null."
    )
 
    comparison: Optional[ComparisonConfig] = Field(
        default=None,
        description="Null if no comparison requested or no window provided."
    )
 
    derived_metric: Literal[
        "none",
        "wow_growth", "mom_growth", "yoy_growth",
        "period_change", "contribution_percent", "avg_price",
    ] = Field(
        default="none",
        description=(
            "Derived metric to calculate. 'none' if not applicable. "
            "mom_growth/yoy_growth require a comparison_window — use 'none' if absent."
        )
    )
 
    model_config = ConfigDict(extra="forbid")
 
 
class TimeSpec(BaseModel):
    """Time block in the final Intent. Always uses 'invoice_date'."""
 
    dimension: Literal["invoice_date"] = Field(default="invoice_date")
    window: Optional[str] = Field(alias="time_window")
    start_date: Optional[str] = Field(default=None)
    end_date: Optional[str] = Field(default=None)
    granularity: Optional[Literal["day", "week", "month", "quarter", "year"]] = Field(default=None)
 
    model_config = ConfigDict(extra="forbid")
 
 
class MetricSpec(BaseModel):
    """A single metric with its aggregation in the final Intent."""
    name: str
    aggregation: Literal["sum", "count", "avg"]
 
    model_config = ConfigDict(extra="forbid")
 
 
class Intent(BaseModel):
    """
    Final output of the pipeline. Schema matches the original monolithic
    prompt's output exactly — the internal agent structure is invisible
    to downstream consumers.
    """
 
    sales_scope: Literal["PRIMARY", "SECONDARY"]
    metrics: List[MetricSpec] = Field(min_length=1)
    group_by: Optional[List[str]] = Field(default=None)
    
    @field_validator("group_by", mode="before")
    @classmethod
    def ensure_group_by_is_list(cls, v):
        if isinstance(v, str):
            return [v]
        return v
        
    filters: Optional[List[FilterCondition]] = Field(default=None)
    time: Optional[TimeSpec] = Field(default=None)
    post_processing: Optional[PostProcessingResult] = Field(default=None)
 
    model_config = ConfigDict(extra="forbid")
 
 
# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================
 
def get_valid_dimensions_for_scope(scope: str) -> frozenset[str]:
    """Returns the set of valid dimensions for a given sales scope."""
    return COMMON_DIMENSIONS if scope == "PRIMARY" else ALL_DIMENSIONS
  
def is_valid_time_window(window: str) -> bool:
    return window in TIME_WINDOWS