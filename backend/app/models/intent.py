"""
Intent Model - Canonical intent contract for the NL2SQL system.

Responsibilities:
- Define allowed intent types (enum)
- Define intent fields with types and validation
- Provide deterministic intent type derivation
- NO business logic
- NO catalog access
- NO LLM logic
"""

from enum import Enum
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, model_validator, ConfigDict


# =============================================================================
# INTENT TYPE ENUM
# Derived deterministically via derive_intent_type() — NOT set by the LLM.
# =============================================================================

class IntentType(str, Enum):
    """
    Defines the type of analytical query the user wants to perform.

    This is derived deterministically from the structured intent fields,
    NOT extracted by the LLM. The derivation rules are in derive_intent_type().
    """
    SNAPSHOT     = "snapshot"      # Single aggregate, no time grouping
    TREND        = "trend"         # Metric grouped over time (time.granularity set)
    COMPARISON   = "comparison"    # Metric compared across periods or segments
    RANKING      = "ranking"       # Ranked list (post_processing.ranking.enabled = true)
    DISTRIBUTION = "distribution"  # Breakdown by dimension (group_by set, no ranking)
    DRILL_DOWN   = "drill_down"    # Hierarchical exploration


# =============================================================================
# SUB-MODELS
# =============================================================================

class Metric(BaseModel):
    """
    A single metric to compute.

    Example: {"name": "net_value", "aggregation": "sum"}
    """
    name: str = Field(
        ...,
        description="Catalog metric name (e.g. 'net_value', 'billed_qty', 'count')"
    )
    aggregation: Literal["sum", "count", "avg"] = Field(
        default="sum",
        description="Aggregation function to apply"
    )

    model_config = ConfigDict(extra="forbid")


class Filter(BaseModel):
    """
    A filter condition on a dimension.

    Example: {"dimension": "zone", "operator": "equals", "value": "North-1"}

    Value normalization:
    - For 'in'/'not_in': accepts string or list, normalizes to list
    - For 'equals'/'not_equals'/'contains': accepts string or single-item list,
      normalizes to string. Multiple values are upgraded to 'in'.
    """
    dimension: str = Field(
        ...,
        description="The dimension to filter on (e.g. 'zone', 'brand', 'category')"
    )
    operator: Literal["equals", "not_equals", "in", "not_in", "contains"] = Field(
        default="equals",
        description="Comparison operator"
    )
    value: str | List[str] = Field(
        ...,
        description="Value(s) to filter by. Use list for 'in'/'not_in' operators."
    )

    @model_validator(mode='after')
    def normalize_and_validate_value(self) -> 'Filter':
        """Normalize value type based on operator."""
        if self.operator in ("in", "not_in"):
            if isinstance(self.value, str):
                object.__setattr__(self, 'value', [self.value])
        elif self.operator in ("equals", "not_equals", "contains"):
            if isinstance(self.value, list):
                if len(self.value) == 0:
                    raise ValueError(f"Operator '{self.operator}' requires at least one value")
                elif len(self.value) == 1:
                    object.__setattr__(self, 'value', self.value[0])
                else:
                    # Multiple values with equals → upgrade to 'in'
                    object.__setattr__(self, 'operator', 'in')
        return self

    model_config = ConfigDict(extra="forbid")


class TimeSpec(BaseModel):
    """
    Unified time specification combining dimension, range, and granularity.

    Either 'window' OR 'start_date'/'end_date' must be used — never both.
    'granularity' is set for trend queries (grouping by time period).
    'granularity' is null for snapshot/filter-only queries.
    """
    dimension: str = Field(
        default="invoice_date",
        description="The time dimension field. Always 'invoice_date'."
    )
    window: Optional[str] = Field(
        default=None,
        description="Named time window (e.g. 'last_30_days', 'month_to_date')"
    )
    start_date: Optional[str] = Field(
        default=None,
        description="Explicit start date in ISO format (YYYY-MM-DD), inclusive"
    )
    end_date: Optional[str] = Field(
        default=None,
        description="Explicit end date in ISO format (YYYY-MM-DD), inclusive"
    )
    granularity: Optional[Literal["day", "week", "month", "quarter", "year"]] = Field(
        default=None,
        description="Time grouping granularity. Set for trend queries, null otherwise."
    )

    @model_validator(mode='after')
    def validate_time_spec(self) -> 'TimeSpec':
        has_window = self.window is not None
        has_dates = self.start_date is not None or self.end_date is not None

        if has_window and has_dates:
            raise ValueError(
                "Cannot specify both 'window' and explicit dates. "
                "Use either a named window OR start_date/end_date."
            )

        return self

    model_config = ConfigDict(extra="forbid")


class RankingSpec(BaseModel):
    """
    Ranking configuration — top/bottom N results.

    Example: {"enabled": true, "order": "desc", "limit": 5}
    """
    enabled: bool = Field(
        default=False,
        description="Whether ranking is active"
    )
    order: Optional[Literal["asc", "desc"]] = Field(
        default="desc",
        description="Sort order: 'desc' for top N, 'asc' for bottom N"
    )
    limit: Optional[int] = Field(
        default=None,
        description="Maximum number of ranked results (e.g. 5 for 'top 5')"
    )

    model_config = ConfigDict(extra="forbid")


class ComparisonSpec(BaseModel):
    """
    Comparison configuration — period-over-period or segment comparison.

    Example (period): {"type": "period", "comparison_window": "last_month"}
    Example (dimension): {"type": "dimension", "comparison_window": null}
    """
    type: Literal["none", "dimension", "period"] = Field(
        default="none",
        description="Comparison type"
    )
    comparison_window: Optional[str] = Field(
        default=None,
        description="The time window to compare against (for 'period' type)"
    )

    model_config = ConfigDict(extra="forbid")


class PostProcessing(BaseModel):
    """
    Post-processing operations applied after data retrieval.

    All fields are optional. Set to null if not applicable.
    """
    ranking: Optional[RankingSpec] = Field(
        default=None,
        description="Ranking configuration (top/bottom N)"
    )
    comparison: Optional[ComparisonSpec] = Field(
        default=None,
        description="Comparison configuration (period or dimension)"
    )
    derived_metric: Optional[Literal[
        "none", "wow_growth", "mom_growth", "yoy_growth", "period_change",
        "contribution_percent", "avg_price"
    ]] = Field(
        default="none",
        description="Derived metric to compute after aggregation"
    )

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# CANONICAL INTENT MODEL
# =============================================================================

class Intent(BaseModel):
    """
    The canonical intent representation for an analytical query.

    This is the contract between intent extraction and query generation.
    Fields are structurally validated here; semantic validation (catalog
    membership, cross-field completeness) happens in intent_validator.
    """
    sales_scope: Literal["PRIMARY", "SECONDARY"] = Field(
        default="SECONDARY",
        description="The sales scope (PRIMARY or SECONDARY)"
    )

    metrics: List[Metric] = Field(
        ...,
        description="One or more metrics to compute",
        min_length=1
    )

    group_by: Optional[List[str]] = Field(
        default=None,
        description="Dimensions to group results by (e.g. ['zone', 'brand'])"
    )

    filters: Optional[List[Filter]] = Field(
        default=None,
        description="Filter conditions to apply before aggregation"
    )

    time: Optional[TimeSpec] = Field(
        default=None,
        description="Time range and granularity specification"
    )

    post_processing: Optional[PostProcessing] = Field(
        default=None,
        description="Post-aggregation operations: ranking, comparison, derived metrics"
    )

    @model_validator(mode='after')
    def validate_basic_structure(self) -> 'Intent':
        """Enforce structural constraints only. Semantic validation is downstream."""
        # Metrics must be non-empty (also enforced by min_length=1 on Field)
        if not self.metrics:
            raise ValueError("At least one metric must be specified")

        # Metric names must be non-empty strings
        for m in self.metrics:
            if not m.name.strip():
                raise ValueError("Metric name must be a non-empty string")

        return self

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


# =============================================================================
# DETERMINISTIC INTENT TYPE DERIVATION
# =============================================================================

def derive_intent_type(intent: Intent) -> IntentType:
    """
    Derive the intent type deterministically from the structured intent fields.
    
    Decision tree (in priority order):
    1. COMPARISON   → post_processing.comparison.type in {"period", "dimension"}
    2. RANKING      → post_processing.ranking.enabled is True
    3. TREND        → time.granularity is not None
    4. DISTRIBUTION → group_by is set (dimension breakdown, no ranking/trend)
    5. SNAPSHOT     → single aggregate, no grouping

    DRILL_DOWN is reserved for hierarchical drill-through. Not yet auto-classified.
    """
    has_group_by = bool(intent.group_by)
    has_time_granularity = (
        intent.time is not None and
        intent.time.granularity is not None
    )
    has_ranking = bool(
        intent.post_processing and
        intent.post_processing.ranking and
        intent.post_processing.ranking.enabled
    )
    has_comparison = bool(
        intent.post_processing and
        intent.post_processing.comparison and
        intent.post_processing.comparison.type in {"period", "dimension"}
    )
    has_growth_metric = bool(
        intent.post_processing and
        intent.post_processing.derived_metric in {"period_growth", "yoy_growth", "mom_growth", "wow_growth", "mtm_growth"}
    )

    # Comparison always wins (explicit dual-axis)
    if has_comparison:
        return IntentType.COMPARISON

    # Growth queries inherently represent trends (even if ranked for ordering)
    if has_growth_metric:
        return IntentType.TREND

    # Ranking (ordering + limit)
    if has_ranking:
        return IntentType.RANKING

    # Trend (time grouping present)
    if has_time_granularity:
        return IntentType.TREND

    # Distribution (dimension grouping only)
    if has_group_by:
        return IntentType.DISTRIBUTION

    # Snapshot (single aggregate, no grouping)
    return IntentType.SNAPSHOT


# =============================================================================
# TYPE ALIASES
# =============================================================================

IntentDict = dict  # When serialized via .model_dump()
