"""
Pydantic schemas for DSPy pipeline intermediate results and catalog constants.

Following RULE P1: One Pydantic model per agent output
Following RULE P4: Catalog constants in schemas.py, import everywhere
"""
from __future__ import annotations
from typing import List, Optional, Dict, Any, Literal, Union
from pydantic import BaseModel, Field, ConfigDict, model_validator

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
    "brand", "category", "sub_category", "pack_size", "sku_code", "product_desc",
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
    "KPI",             # single aggregated value, no dimension breakdown
    "DISTRIBUTION",    # breakdown by one or more dimensions
    "RANKING",         # top/bottom N with a grouping dimension
    "TREND",           # metric over time requiring granularity
    "COMPARISON",      # current period vs another period or dimension
    "DRILL_DOWN",      # navigating deeper into a hierarchy from previous context
    "MINIMAL_MESSAGE", # bare dimension or metric name only — context-dependent
    "STRUCTURAL",      # asking what entities exist, not how they performed
]
 
 
class ClassifiedTerm(BaseModel):
    """
    One term from the query with its semantic role and resolved catalog name.
 
    WHY A UNIFIED LIST (not separate metric_terms=[], dimension_terms=[] lists):
        Flat role-specific lists lose the term↔role pairing. Downstream agents
        need to know both what the term was AND what role it plays. For example,
        "Gold Flake" is a FILTER_VALUE that resolves to dimension "brand" —
        that two-part relationship cannot be stored in a flat string list.
 
    WHY catalog_match IS RESOLVED HERE:
        Alias resolution (quantity→billed_qty, territory→zone) happens once in
        the Classifier. All downstream agents receive canonical names and never
        need to know about aliases. This is the single point of alias resolution.
    """
    term: str = Field(
        description="Exact word or phrase as it appears in the query."
    )
    role: TermRole = Field(
        description="Semantic role this term plays in the query."
    )
    catalog_match: Optional[str] = Field(
        default=None,
        description=(
            "Resolved canonical catalog name. Apply aliases: "
            "quantity/volume → billed_qty, territory/region → zone, "
            "distributor → distributor_name, retailer → retailer_name, "
            "product → product_desc, sales/revenue → net_value. "
            "Null for RANKING/TREND/COMPARISON/SCOPE terms with no catalog entry."
        )
    )
 
    model_config = ConfigDict(extra="forbid")
 
 
class FilterHint(BaseModel):
    """
    A specific filter value paired with the dimension it qualifies.
 
    WHY SEPARATE FROM ClassifiedTerm:
        A FILTER_VALUE term like 'Gold Flake' needs its dimension ('brand')
        stored alongside it. ClassifiedTerm carries one catalog_match for the
        term itself — FilterHint carries the dimension the value belongs to.
        DimensionsAgent consumes these to build FilterCondition objects.
 
    WHY NO OPERATOR:
        Operator (equals/in/contains) is resolved by DimensionsAgent based on
        value cardinality and query phrasing. Classifying operators is not the
        Classifier's job — it only identifies what the value is and which
        dimension it belongs to.
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
 
    This replaces the old flat-list model (metric_terms, dimension_terms,
    filter_terms, time_expressions, ranking_indicators, scope_indicators,
    comparison_indicators). Those fields had three problems:
      1. Lost the term↔role pairing needed by downstream agents.
      2. Had no query_intent — forcing _infer_intent_category() in the pipeline.
      3. Mixed operators with values in filter_terms.
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
 
    WHY has_time_constraint IS REMOVED:
        It was a derived field stored as data. Whether time is present is
        already expressed by time_window/start_date being non-null. Storing
        a redundant bool creates consistency bugs (bool says True, all fields
        are None). Downstream agents check `time_result.time_window is not None`
        or `time_result.start_date is not None` directly.
 
    WHY window XOR dates IS A model_validator:
        This is a binary constraint — either satisfied or not. It belongs in
        Python, not in agent prompts. If the LLM sets both, the validator
        clears start_date/end_date silently and keeps the window.
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
 
    WHY metric_confidence IS REMOVED:
        It had no downstream consumer in the pipeline. Storing it forced the
        LLM to produce a float per metric on every call, adding prompt noise
        and output tokens with zero benefit to assembly or validation.
 
    WHY aggregations IS KEPT:
        The Assembler needs aggregation per metric to build the final Intent.
        It is parallel to metrics (same index = same metric).
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
 
    WHY operator HAS NO DEFAULT:
        A default of 'equals' silently masks operator resolution failures.
        DimensionsAgent must explicitly choose the operator — it has the
        context to make that decision (single value → equals, list → in).
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
 
    WHY context_operation AND hierarchy_level ARE REMOVED:
        These were internal bookkeeping fields the Assembler never consumed.
        The Assembler needs group_by and filters — not metadata about how the
        DimensionsAgent arrived at them. Internal state belongs inside the
        agent's forward() method, not on its output model.
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
    comparison_window: Optional[Literal[
        "today", "yesterday",
        "last_7_days", "last_30_days", "last_90_days",
        "month_to_date", "quarter_to_date", "year_to_date",
        "last_month", "last_quarter", "last_year",
        "all_time",
    ]] = Field(
        default=None,
        description="Comparison time window. Required when type='period'."
    )
 
    model_config = ConfigDict(extra="forbid")
 
 
class PostProcessingResult(BaseModel):
    """
    Post-processing specification.
 
    WHY NESTED CONFIGS (not flat fields like ranking_enabled, ranking_order):
        Flat fields require the Assembler to reconstruct the nested final schema
        from separate fields, adding unnecessary translation logic. Nested configs
        map directly to the final Intent schema with no reconstruction needed.
 
    WHY derived_metric IS NOT Optional:
        It must always be present when post_processing is non-null so the
        Assembler never has to guess whether it was omitted or intentionally absent.
        Use "none" as the explicit no-op value.
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

 
# def resolve_metric_alias(term: str) -> str:
#     """Resolves a metric alias to its canonical name. Returns term unchanged if not an alias."""
#     return METRIC_ALIASES.get(term.lower(), term)
 
 
# def resolve_dimension_alias(term: str) -> str:
#     """Resolves a dimension alias to its canonical name. Returns term unchanged if not an alias."""
#     return DIMENSION_ALIASES.get(term.lower(), term)
 
# def get_hierarchy_next_level(current_dim: str) -> Optional[str]:
#     """Returns the next level down in the hierarchy for drill-down operations."""
#     for hierarchy in (GEO_HIERARCHY, PRODUCT_HIERARCHY):
#         if current_dim in hierarchy:
#             idx = hierarchy.index(current_dim)
#             return hierarchy[idx + 1] if idx < len(hierarchy) - 1 else None
#     return None
 
 
# def find_ambiguous_dimension_candidates(term: str, valid_dims: frozenset) -> list:
#     """
#     Returns candidate catalog dimensions when a term is ambiguous (2+ matches).
#     Returns empty list if the term resolves cleanly to one dimension.
#     """
#     t = term.strip().lower()
 
#     # Direct alias or catalog match → unambiguous
#     if resolve_dimension_alias(t) in valid_dims:
#         return []
 
#     # Semantic group match
#     group = DIMENSION_SEMANTIC_GROUPS.get(t)
#     if group:
#         candidates = [d for d in group if d in valid_dims]
#         if len(candidates) >= 2:
#             return candidates
 
#     # Substring fallback
#     matches = [d for d in valid_dims if t in d.replace("_", " ") or d.replace("_", " ") in t]
#     return matches if len(matches) >= 2 else []
 
 
# def find_ambiguous_metric_candidates(term: str) -> list:
#     """
#     Returns candidate metrics when a term is ambiguous (2+ matches).
#     Returns empty list if the term resolves cleanly to one metric.
#     """
#     t = term.strip().lower()
 
#     if resolve_metric_alias(t) in CATALOG_METRICS:
#         return []
 
#     group = METRIC_SEMANTIC_GROUPS.get(t)
#     if group:
#         candidates = [m for m in group if m in CATALOG_METRICS]
#         if len(candidates) >= 2:
#             return candidates
 
#     return []