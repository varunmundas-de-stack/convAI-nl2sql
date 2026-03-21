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
    ScopeTimeResult,
    MetricsResult,
    DimensionsResult,
    PostProcessingSpec
)

# =============================================================================
# SIGNATURE DEFINITIONS
# =============================================================================

class ClassifyQuery(dspy.Signature):
    """Label query terms with their semantic roles for downstream processing."""

    query = dspy.InputField(desc="Natural language query to classify")

    # Output fields with constraint descriptions for optimizer
    metric_terms = dspy.OutputField(
        desc="comma-separated metric terms (sales, revenue, quantity). "
             "use base terms only, no derived calculations"
    )

    dimension_terms = dspy.OutputField(
        desc="comma-separated dimension terms (zone, brand, category). "
             "include both grouping and filter dimensions"
    )

    filter_terms = dspy.OutputField(
        desc="comma-separated filter condition indicators (equals, in, contains). "
             "include specific values mentioned"
    )

    time_expressions = dspy.OutputField(
        desc="comma-separated time-related terms (last month, daily, trend). "
             "include both ranges and granularities"
    )

    ranking_indicators = dspy.OutputField(
        desc="comma-separated ranking terms (top, bottom, highest, lowest). "
             "include numeric limits if specified"
    )

    scope_indicators = dspy.OutputField(
        desc="comma-separated scope terms (primary, secondary). "
             "empty if no explicit scope mentioned"
    )

    comparison_indicators = dspy.OutputField(
        desc="comma-separated comparison terms (vs, compared, growth). "
             "include period comparison signals"
    )


class ResolveScope(dspy.Signature):
    """Determine sales scope from classified query terms."""

    classified_query = dspy.InputField(desc="Query with labeled semantic terms")

    # Output fields for scope resolution
    sales_scope = dspy.OutputField(
        desc="PRIMARY or SECONDARY. default SECONDARY if no explicit scope. "
             "PRIMARY only if explicitly mentioned"
    )


class ResolveTime(dspy.Signature):
    """Determine time constraints from classified query with decision logic and clarification rules."""

    classified_query = dspy.InputField(desc="Query with labeled semantic terms")
    current_date = dspy.InputField(desc="Current date in YYYY-MM-DD format")
    intent_category = dspy.InputField(desc="Query intent category (KPI, DISTRIBUTION, RANKING, TREND, COMPARISON, etc.)")
    previous_context = dspy.InputField(desc="Previous QCO context as JSON string. empty on first turn")

    # Output fields for time resolution
    time_window = dspy.OutputField(
        desc="exact TIME_WINDOW match only (last_30_days, month_to_date). "
             "null if no exact match found"
    )

    start_date = dspy.OutputField(
        desc="YYYY-MM-DD start date. use only if time_window is null. "
             "calculate from current_date for relative expressions"
    )

    end_date = dspy.OutputField(
        desc="YYYY-MM-DD end date. use only if time_window is null. "
             "inclusive end date"
    )

    granularity = dspy.OutputField(
        desc="day|week|month|quarter|year for trend queries only. "
             "null for snapshot/distribution queries. default week for vague trends"
    )

    has_time_constraint = dspy.OutputField(
        desc="true if any time constraint specified, false otherwise"
    )

    requires_clarification = dspy.OutputField(
        desc="true if query requires time but none provided and no previous context available. "
             "false if time is provided, inherited from context, or not needed for query type"
    )

    reasoning = dspy.OutputField(
        desc="brief explanation of time decision logic and whether clarification is needed"
    )


# Keep old signature for backwards compatibility during transition
ResolveScopeTime = ResolveScope


class ExtractMetrics(dspy.Signature):
    """Extract and validate metrics from classified query with ambiguity detection."""

    classified_query = dspy.InputField(desc="Query with labeled metric terms")
    sales_scope = dspy.InputField(desc="Resolved sales scope (PRIMARY/SECONDARY)")
    available_metrics = dspy.InputField(desc="JSON list of available metrics with name, label, description")

    metrics = dspy.OutputField(
        desc="comma-separated catalog metric names only (count, net_value, gross_value, tax_value, billed_qty). "
             "resolve aliases: quantity→billed_qty, sales→net_value. minimum 1 metric"
    )

    aggregations = dspy.OutputField(
        desc="comma-separated aggregation functions parallel to metrics (sum, count, avg). "
             "default sum for value metrics, count for transaction metrics"
    )

    ambiguous_terms = dspy.OutputField(
        desc="comma-separated terms from query that could refer to multiple metrics. "
             "empty if all metric references are clear"
    )

    ambiguity_confidence = dspy.OutputField(
        desc="confidence score 0.0-1.0 that ambiguous terms exist in the query. "
             "0.0 means no ambiguity, 1.0 means high ambiguity"
    )

    ambiguous_matches = dspy.OutputField(
        desc="JSON array of metrics that could match the ambiguous terms. "
             "empty if no ambiguity detected"
    )

    reasoning = dspy.OutputField(
        desc="brief explanation of metric extraction decisions and any ambiguities found"
    )


class ResolveDimensions(dspy.Signature):
    """Resolve dimensions, filters, and apply context-aware operations with ambiguity detection."""

    classified_query = dspy.InputField(desc="Query with labeled dimension/filter terms")
    sales_scope = dspy.InputField(desc="Resolved sales scope for dimension validation")
    available_dimensions = dspy.InputField(desc="JSON list of available dimensions with name, label, description")
    previous_context = dspy.InputField(desc="Previous QCO context as JSON string. empty on first turn")

    group_by = dspy.OutputField(
        desc="comma-separated dimension names for grouping (zone, brand, category). "
             "null if no grouping. never include invoice_date. max 2 non-time dimensions"
    )

    filters = dspy.OutputField(
        desc="JSON array of filter objects with dimension, operator, value. "
             "null if no filters. validate dimensions against scope"
    )

    context_operation = dspy.OutputField(
        desc="MINIMAL_MESSAGE|DRILL_DOWN|ALSO_BY|REPLACE_BY if context operation detected. "
             "null for standalone queries"
    )

    ranking_enabled = dspy.OutputField(
        desc="true if top/bottom N requested and group_by present. false otherwise"
    )

    ranking_order = dspy.OutputField(
        desc="desc for top/highest, asc for bottom/lowest. null if no ranking"
    )

    ranking_limit = dspy.OutputField(
        desc="numeric limit for ranking (5 for top 5). null if no ranking"
    )

    ambiguous_terms = dspy.OutputField(
        desc="comma-separated terms from query that could refer to multiple dimensions. "
             "empty if all dimension references are clear"
    )

    ambiguity_confidence = dspy.OutputField(
        desc="confidence score 0.0-1.0 that ambiguous dimension terms exist. "
             "0.0 means no ambiguity, 1.0 means high ambiguity"
    )

    ambiguous_matches = dspy.OutputField(
        desc="JSON array of dimensions that could match the ambiguous terms. "
             "empty if no ambiguity detected"
    )

    reasoning = dspy.OutputField(
        desc="brief explanation of dimension resolution decisions and any ambiguities found"
    )


class AssembleIntent(dspy.Signature):
    """Merge upstream results into final intent structure."""

    # All upstream results as inputs
    scope_time_result = dspy.InputField(desc="Resolved scope and time from ScopeTimeAgent")
    metrics_result = dspy.InputField(desc="Validated metrics from MetricsAgent")
    dimensions_result = dspy.InputField(desc="Dimensions and filters from DimensionsAgent")

    # Final intent assembly
    final_intent = dspy.OutputField(
        desc="complete Intent JSON with all fields populated. "
             "metrics must be array of objects with 'name' and 'aggregation' fields. "
             "ensure consistency across all upstream results. "
             "only include valid Intent fields: sales_scope, metrics, group_by, filters, time, post_processing"
    )