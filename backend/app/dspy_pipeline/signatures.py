"""
DSPy Signatures for Intent Extraction Pipeline.

Following RULE S1: Docstring = task instruction, not implementation notes
Following RULE S2: desc= on OutputField = constraint list for optimizer
Following RULE S3: Never put catalog contents inside Signatures
Following RULE S4: Pass typed upstream outputs as InputFields
Following RULE S5: One Signature class per agent, never reuse
"""

import dspy
from typing import List, Optional
from .schemas import (
    DecomposedQuery,
    ClassifiedQuery,
    ScopeResult,
    TimeResult,
    MetricsResult,
    DimensionsResult,
    PostProcessingResult,
    Intent
)

# =============================================================================
# SIGNATURE DEFINITIONS
# =============================================================================

class DecomposeQuery(dspy.Signature):
    """Identify and split compound queries into independent analytical sub-queries.
    
    ONLY split when there are clearly independent analytical intents.
    Examples to SPLIT: 'Show me revenue vs last quarter and also which reps are underperforming' → 2 queries.
    Examples to NOT SPLIT: 'Show me revenue by zone and by product' → 1 query (multiple dimensions).
    For single queries, return is_compound=false with original query as single sub_query.
    """

    query: str = dspy.InputField(desc="Natural language query to analyze")
    session_context: str = dspy.InputField(desc="Previous context from session", default="")

    decomposed_query: DecomposedQuery = dspy.OutputField(
        desc="Structured decomposition of the query into independent sub-queries."
    )


class ClassifyQuery(dspy.Signature):
    """Classify query terms with semantic roles and determine query intent."""

    query: str = dspy.InputField(desc="Natural language query to classify")
    session_context: str = dspy.InputField(desc="Previous context from session", default="")

    # Output the complete classified query as JSON
    classified_query: ClassifiedQuery = dspy.OutputField(
        desc="JSON object with ClassifiedQuery structure containing: "
             "original_query (string), "
             "classified_terms (array of objects with term, role, catalog_match, scope), "
             "query_intent (SNAPSHOT|DISTRIBUTION|RANKING|TREND|COMPARISON|DRILL_DOWN|MINIMAL_MESSAGE|STRUCTURAL), "
             "filter_hints (array of objects with dimension and value), "
             "explicit_scope (PRIMARY|SECONDARY or null). "
             "Intent type MUST be determined based on the query structure and terms. "
             "SNAPSHOT = single aggregated value with no breakdown. "
             "DO NOT guess catalog_match for generic/vague terms like 'region', 'location', 'product'. Leave catalog_match null if ambiguous. "
             "Use roles: METRIC, DIMENSION, TIME_RANGE, TIME_GRANULARITY, FILTER_VALUE, RANKING, SCOPE, COMPARISON, TREND"
    )


class ResolveScope(dspy.Signature):
    """Determine sales scope from classified query."""

    original_query: str = dspy.InputField(desc="Original query text")
    classified_terms: str = dspy.InputField(
        desc="JSON string containing only the classified terms with role SCOPE"
    )

    scope_result: ScopeResult = dspy.OutputField(
        desc=(
            "JSON object with ScopeResult containing: "
            "sales_scope (PRIMARY|SECONDARY). "
            "Only return a value if explicitly indicated in the query. "
            "Do NOT assume a default if scope is not mentioned."
        )
    )


class ResolveTime(dspy.Signature):
    """Determine time constraints from classified query with decision logic and clarification rules."""

    original_query: str = dspy.InputField(desc="Original query text")
    classified_terms: str = dspy.InputField(desc="JSON string containing only the classified terms with roles TIME_RANGE and TIME_GRANULARITY")
    current_date: str = dspy.InputField(desc="Current date in YYYY-MM-DD format")
    query_intent: str = dspy.InputField(desc="Query intent from classified query (KPI, DISTRIBUTION, RANKING, TREND, COMPARISON, etc.)")
    previous_context: str = dspy.InputField(desc="Previous QCO context as JSON string. empty on first turn")

    # Output TimeResult as JSON
    time_result: TimeResult = dspy.OutputField(
        desc="JSON object with TimeResult structure containing: "
             "time_window (exact TIME_WINDOW match or null), "
             "start_date (YYYY-MM-DD or null), "
             "end_date (YYYY-MM-DD or null), "
             "granularity (day|week|month|quarter|year or null for non-trend queries). "
             "Use time_window for exact matches like 'last_30_days', 'month_to_date'. "
             "Use start_date/end_date only if no time_window matches. "
             "Default granularity to 'week' for TREND queries without explicit granularity. "
             "Window and dates are mutually exclusive - never set both"
    )



class ExtractMetrics(dspy.Signature):
    """Extract and validate metrics from classified query."""

    original_query: str = dspy.InputField(desc="Original query text")
    classified_terms: str = dspy.InputField(desc="JSON string containing only the classified terms with role METRIC")
    sales_scope: str = dspy.InputField(desc="Resolved sales scope (PRIMARY/SECONDARY)")
    available_metrics: str = dspy.InputField(desc="JSON list of available metrics with name, label, description")

    # Output MetricsResult as JSON
    metrics_result: MetricsResult = dspy.OutputField(
        desc="""
        Return a list of candidate metrics from the catalog.

        Rules:
        - If NO metric is explicitly specified, return all the available metrics as MULTIPLE candidates.
        - If query clearly maps to ONE metric → return single-item list
        - If query is ambiguous → return MULTIPLE candidate metrics
        - All metrics MUST be from provided catalog
        - Do Not guess if ambiguous — return all plausible matches
        """
    )


class ResolveDimensions(dspy.Signature):
    """Resolve dimensions and filters from classified query."""
    original_query: str = dspy.InputField(desc="Original query text")
    classified_terms: str = dspy.InputField(desc="JSON string containing only the classified terms with roles DIMENSION and FILTER_VALUE")
    sales_scope: str = dspy.InputField(desc="Resolved sales scope for dimension validation")
    available_dimensions: str = dspy.InputField(desc="JSON list of available dimensions with name, label, description")
    previous_context: str = dspy.InputField(desc="Previous QCO context as JSON string. empty on first turn")
    x_axis_values: str = dspy.InputField(
        desc="""JSON object with 'dimension' (the catalog field name) and 'values' (list of labels 
        from the previous chart). If a classified FILTER_VALUE term semantically matches or closely matches 
        (ignoring cases, spacing, hyphens, prefixes) any of these values, emit a FilterCondition with that 
        dimension and the EXACT matched value from the 'values' list. 
        Example: if query contains 'north1' and values has 'North-1', output 'North-1'.
        Example Input: {"dimension": "fact_secondary_sales.zone", "values": ["Central", "North", "South"]}"""
    )

    # Output DimensionsResult as JSON
    dimensions_result: DimensionsResult = dspy.OutputField(
    desc="""
    JSON object with DimensionsResult containing:

    group_by:
      - array of dimension names matching the user's intent from available_dimensions.
      - If the user explicitly asks for a specific dimension (e.g. 'country'), return just that one ['country'].
      - If the user uses a VAGUE/GENERIC term that matches multiple specific catalog fields, you MUST return ALL matching candidate fields in the area.
      - NEVER arbitrarily choose just one field if the user's term is generic. Give every valid possibility.
      - A term like 'region' is VAGUE — return ALL geo-related candidates e.g. ['zone', 'region', 'state'].

    filters:
      - array of FilterCondition objects or null
      - If a classified term has role=FILTER_VALUE and its value fuzzy-matches (ignoring hyphens, spaces, typos) an item in x_axis_values,
        it is a filter NOT a dimension.
        Emit: { dimension: <group_by from previous_context>, operator: "equals", values: [<EXACT matched value from x_axis_values>] }
      - CRITICAL: You MUST use the exact string casing and format from x_axis_values. Do NOT use the raw user query string if it differs.
      - NEVER add a FILTER_VALUE term to group_by.

    Rules:
      - Max 2 dimensions for grouping (EXCEPT when returning >2 candidates for a generic/ambiguous term)
      - Never include 'invoice_date'
      - Only use dimensions exactly as named in available_dimensions
      - Respect hierarchy constraints (geo/product)
    """
    )

class ResolvePostProcessing(dspy.Signature):
    """Infer high-level post-processing intent."""

    original_query: str = dspy.InputField(desc="Original query text")
    query_intent: str = dspy.InputField(
        desc="The query_intent extracted from the classified query (e.g., RANKING, COMPARISON, TREND, etc.)"
    )

    classified_terms: str = dspy.InputField(
        desc="JSON string containing only the classified terms with roles RANKING, COMPARISON, and TREND"
    )

    time_result: TimeResult = dspy.InputField(
        desc="Resolved time context (window, dates, granularity)"
    )

    dimensions_result: DimensionsResult = dspy.InputField(
        desc="Contains group_by (required for ranking)"
    )

    post_processing_result: PostProcessingResult = dspy.OutputField(
    desc=(
        "Return PostProcessingResult with: "
        "ranking (enabled/order/limit), "
        "comparison.comparison_window must be one of: "
        "'today','yesterday','last_7_days','last_30_days','last_90_days','month_to_date',"
        "'quarter_to_date','year_to_date','last_month','last_quarter','last_year','all_time' "
        "or null. "
        "If the query compares explicit dates/months like 'feb vs march', set comparison_window=null. "
        "NEVER output 'previous_period' or any unlisted value — use null instead. "
        "derived_metric: none|wow_growth|mom_growth|yoy_growth|period_change|contribution_percent|avg_price."
        )
    )

# class AssembleIntent(dspy.Signature):
#     """Merge upstream results into the final intent structure."""
 
#     # All upstream results as inputs
#     classified_query: ClassifiedQuery = dspy.InputField(desc="ClassifiedQuery object with original query and intent")
#     scope_result: ScopeResult = dspy.InputField(desc="ScopeResult object from ScopeAgent")
#     time_result: TimeResult = dspy.InputField(desc="TimeResult object from TimeAgent")
#     metrics_result: MetricsResult = dspy.InputField(desc="MetricsResult object from MetricsAgent")
#     dimensions_result: DimensionsResult = dspy.InputField(desc="DimensionsResult object from DimensionsAgent")
#     post_processing_result: PostProcessingResult = dspy.InputField(desc="PostProcessingResult object from PostProcessingAgent")
 
#     # Final intent assembly
#     final_intent: Intent = dspy.OutputField(
#         desc="Complete Intent object assembled from all upstream inputs with no derivation: "
#              "sales_scope from scope_result.sales_scope, "
#              "metrics from metrics_result (each entry has name and aggregation), "
#              "group_by from dimensions_result.group_by (array or null), "
#              "filters from dimensions_result.filters (array or null), "
#              "time (TimeSpec with dimension='invoice_date', window from time_result.time_window, "
#              "      start_date/end_date from time_result, granularity from time_result.granularity) or null if no time constraint, "
#              "post_processing from post_processing_result or null if all fields are null/none. "
#              "Do not re-derive any field — copy values directly from the corresponding input."
#     )


class RefineInsights(dspy.Signature):
    """Refine insights with enhanced interpretation while preserving all numeric values.

    Enhance insights with executive-style commentary, confidence levels, and contextual interpretation.
    NEVER modify numeric fields (metric_value, change_pct, total_value, etc.) - only interpretation.
    Focus on business significance, severity assessment, and actionable recommendations.
    """

    query: str = dspy.InputField(desc="Original user query for context")
    insight_summary: str = dspy.InputField(
        desc="JSON string containing InsightResult with deterministic insights, "
             "metrics facts, total values, and original numeric calculations"
    )
    previous_context: str = dspy.InputField(
        desc="Previous QueryContextObject context as JSON string for continuity",
        default=""
    )

    refined_insights: str = dspy.OutputField(
        desc="JSON object containing: "
             "executive_summary (concise business interpretation), "
             "refined_headlines (array of enhanced insight headlines maintaining original numeric values), "
             "key_risks (object with risk categories and descriptions), "
             "possible_drivers (object with potential business causes), "
             "recommendations (object with actionable next steps). "
             "CRITICAL: Preserve ALL numeric values exactly as provided. "
             "Only refine interpretation, severity assessment, and business context. "
             "Headlines should be executive-ready while maintaining factual precision."
    )