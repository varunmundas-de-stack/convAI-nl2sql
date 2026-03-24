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

class ClassifyQuery(dspy.Signature):
    """Classify query terms with semantic roles and determine query intent."""

    query: str = dspy.InputField(desc="Natural language query to classify")

    # Output the complete classified query as JSON
    classified_query: ClassifiedQuery = dspy.OutputField(
        desc="JSON object with ClassifiedQuery structure containing: "
             "original_query (string), "
             "classified_terms (array of objects with term, role, catalog_match), "
             "query_intent (KPI|DISTRIBUTION|RANKING|TREND|COMPARISON|DRILL_DOWN|MINIMAL_MESSAGE|STRUCTURAL), "
             "filter_hints (array of objects with dimension and value), "
             "explicit_scope (PRIMARY|SECONDARY or null). "
             "Resolve aliases: quantity→billed_qty, territory→zone, sales→net_value. "
             "Use roles: METRIC, DIMENSION, TIME_RANGE, TIME_GRANULARITY, FILTER_VALUE, RANKING, SCOPE, COMPARISON, TREND"
    )


class ResolveScope(dspy.Signature):
    """Determine sales scope from classified query."""

    classified_query: ClassifiedQuery = dspy.InputField(
        desc="ClassifiedQuery object with structured terms and roles"
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

    classified_query: ClassifiedQuery = dspy.InputField(desc="ClassifiedQuery object with structured terms and roles")
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

    classified_query: ClassifiedQuery = dspy.InputField(desc="ClassifiedQuery object with structured terms and roles")
    sales_scope: str = dspy.InputField(desc="Resolved sales scope (PRIMARY/SECONDARY)")
    available_metrics: str = dspy.InputField(desc="JSON list of available metrics with name, label, description")

    # Output MetricsResult as JSON
    metrics_result: MetricsResult = dspy.OutputField(
        desc="""
        Return a list of candidate metrics from the catalog.

        Rules:
        - If query clearly maps to ONE metric → return single-item list
        - If query is ambiguous → return MULTIPLE candidate metrics
        - All metrics MUST be from provided catalog
        - Do NOT guess if ambiguous — return all plausible matches
        """
    )


class ResolveDimensions(dspy.Signature):
    """Resolve dimensions and filters from classified query."""

    classified_query: ClassifiedQuery = dspy.InputField(desc="ClassifiedQuery object with structured terms and roles")
    sales_scope: str = dspy.InputField(desc="Resolved sales scope for dimension validation")
    available_dimensions: str = dspy.InputField(desc="JSON list of available dimensions with name, label, description")
    previous_context: str = dspy.InputField(desc="Previous QCO context as JSON string. empty on first turn")

    # Output DimensionsResult as JSON
    dimensions_result: DimensionsResult = dspy.OutputField(
        desc="JSON object with DimensionsResult structure containing: "
             "group_by (array of canonical dimension names for grouping or null), "
             "filters (array of FilterCondition objects with dimension, operator, value or null). "
             "Max 2 dimensions in group_by. Never include 'invoice_date'. "
             "Max 1 dimension per hierarchy (geo: zone/state/city, product: category/sub_category/brand/sku_code). "
             "FilterCondition has dimension (string), operator (equals|not_equals|in|not_in|contains), "
             "value (string or array for in/not_in operators). "
             "Validate dimensions against scope constraints"
    )

class ResolvePostProcessing(dspy.Signature):
    """Infer high-level post-processing intent."""

    classified_query: ClassifiedQuery = dspy.InputField(
        desc="Contains query_intent (RANKING, COMPARISON, TREND, etc.) and extracted hints like top/bottom, limits, etc."
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
            "comparison (type/comparison_window), "
            "derived_metric (none|wow_growth|mom_growth|yoy_growth|period_change|contribution_percent|avg_price). "
            "Focus only on user intent — do not enforce constraints."
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