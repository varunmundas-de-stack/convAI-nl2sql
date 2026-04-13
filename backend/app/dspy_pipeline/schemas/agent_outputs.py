
from __future__ import annotations
from typing import List, Optional, Dict, Any, Literal, Union
from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator
from .primitives import *
from app.dspy_pipeline.schemas.catalog import TIME_WINDOWS

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
 
 

class RefinedInsights(BaseModel):
    executive_summary: str = Field(
        description="1-2 sentences in plain business language referencing actual numeric values. No jargon. Use Indian numbering (Lakhs/Crores)."
    )
    key_risks: dict[str, str] = Field(
        min_length=2,
        description="Numbered keys '1','2','3'. Format: '[what is at risk] because [plain-language evidence]'. Always populate — infer from data even if no rule_insights flagged."
    )
    possible_drivers: dict[str, str] = Field(
        min_length=2,
        description="Numbered keys '1','2','3'. Format: '[hypothesis] — supported by [plain-language data point]'. Always populate."
    )
    recommendations: dict[str, str] = Field(
        min_length=2,
        description="Numbered keys '1','2','3'. Format: '[verb] [what] to [goal]'. Always populate with actionable steps for frontline reps."
    )
 