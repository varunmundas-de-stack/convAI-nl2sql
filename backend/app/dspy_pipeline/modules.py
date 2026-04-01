"""
DSPy Modules for Intent Extraction Pipeline.

Each module wraps a single Signature and contains:
  - Typed predict call via dspy.Predict
  - Lightweight post-validation using Pydantic schemas
  - No catalog logic here — that belongs in schemas.py constants

Following RULE M1: One Module class per Signature
Following RULE M2: forward() returns the typed Pydantic output, not the raw dspy Prediction
Following RULE M3: Validation/correction belongs in the module, not the caller
Following RULE M4: Modules are stateless; all context is passed as arguments
"""

import json
import logging
import uuid
from datetime import date
from typing import Optional

import dspy

from .schemas import (
    # Decomposition output
    DecomposedQuery,
    # Intermediate outputs
    ClassifiedQuery,
    ScopeResult,
    TimeResult,
    MetricsResult,
    DimensionsResult,
    ComparisonConfig,
    RankingConfig,
    PostProcessingResult,
    Intent,
    CATALOG_METRICS,
    METRICS_CATALOG,
    TIME_WINDOWS,
    TimeSpec,
    MetricSpec,
    get_valid_dimensions_for_scope,

)
from .clarification_tool import (
    ClarificationRequired,
    MultipleClarificationsRequired,
    Clarification,
    build_scope_clarification,
    build_metric_clarification,
    build_individual_metric_clarifications,
    build_dimension_clarification,
    build_individual_dimension_clarifications,
    build_time_clarification,
)
from .signatures import (
    DecomposeQuery,
    ClassifyQuery,
    ResolveScope,
    ResolveTime,
    ExtractMetrics,
    ResolveDimensions,
    ResolvePostProcessing,
)
from app.dspy_pipeline.schemas import FilterCondition
logger = logging.getLogger(__name__)


# =============================================================================
# QUERY DECOMPOSER — Before Agent Pipeline
# =============================================================================

class QueryDecomposerModule(dspy.Module):
    """
    Decomposes compound queries into independent analytical sub-queries.

    This is the first agent in the pipeline and determines if a query
    contains multiple independent intents that should be processed separately.
    """

    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(DecomposeQuery)

    def forward(self, query: str, previous_context=None) -> DecomposedQuery:
        context_str = ""
        if previous_context:
            # Handle different context types
            try:
                if hasattr(previous_context, 'to_decomposer_context'):
                    # It's a QCO object
                    context_str = previous_context.to_decomposer_context()
                elif isinstance(previous_context, dict):
                    # It's a dict, convert to QCO
                    from app.models.qco import QueryContextObject
                    qco = QueryContextObject(**previous_context)
                    context_str = qco.to_decomposer_context()
                else:
                    # It's already a string
                    context_str = str(previous_context)
            except Exception:
                # Fallback to JSON if conversion fails
                context_str = json.dumps(previous_context) if isinstance(previous_context, dict) else str(previous_context)

        prediction = self.predict(query=query, session_context=context_str)
        return prediction.decomposed_query


# =============================================================================
# AGENT 1 — ClassifierModule
# =============================================================================
class ClassifierModule(dspy.Module):
    """
    Classifies each term in a natural-language query and determines query intent.

    Inputs  : raw query string
    Outputs : ClassifiedQuery (typed Pydantic model)
    """

    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(ClassifyQuery)

    def forward(self, query: str, session_context=None) -> ClassifiedQuery:
        """
        Run ClassifyQuery signature and return a validated ClassifiedQuery.

        Args:
            query: Raw natural-language query from the user.
            session_context: Previous context from session for better intent determination.

        Returns:
            ClassifiedQuery with classified_terms, query_intent,
            filter_hints, and explicit_scope populated.
        """
        # Handle different context types - convert to string for LLM
        context_str = ""
        if session_context:
            if hasattr(session_context, 'to_prompt_context'):
                # It's a QCO object
                context_str = session_context.to_prompt_context()
            elif isinstance(session_context, dict):
                context_str = json.dumps(session_context)
            else:
                # Already a string
                context_str = str(session_context)

        prediction = self.predict(query=query, session_context=context_str)
        classified: ClassifiedQuery = prediction.classified_query

        # No alias resolution — downstream modules handle ambiguity
        return classified

# =============================================================================
# AGENT 2 — ScopeModule
# =============================================================================

class ScopeModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(ResolveScope)

    def forward(
        self,
        classified_query: ClassifiedQuery,
        overrides: Optional[dict] = None,
    ) -> ScopeResult:

        overrides = overrides or {}

        # -------------------------
        # 1. Override
        # -------------------------
        if "sales_scope" in overrides:
            return ScopeResult(sales_scope=overrides["sales_scope"])

        # -------------------------
        # 2. LLM extraction
        # -------------------------
        relevant_terms = [t.model_dump() for t in classified_query.classified_terms if t.role == "SCOPE"]
        prediction = self.predict(classified_terms=json.dumps(relevant_terms))
        result: ScopeResult = prediction.scope_result

        # -------------------------
        # 3. Ambiguity / Missing handling
        # -------------------------

        # If LLM couldn't determine scope → clarify
        has_scope_term = any(
            t.role == "SCOPE"
            for t in classified_query.classified_terms
        )

        if not has_scope_term:
            raise ClarificationRequired(build_scope_clarification())

        return result

# =============================================================================
# AGENT 3 — TimeModule
# =============================================================================

class TimeModule(dspy.Module):
    """
    Determines time window and granularity from the classified query.

    Inputs  : ClassifiedQuery, current_date, query_intent, previous_context
    Outputs : TimeResult
    """

    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(ResolveTime)

    def forward(
        self,
        classified_query: ClassifiedQuery,
        current_date: Optional[date] = None,
        previous_context=None,
        overrides: Optional[dict] = None,
    ) -> TimeResult:

        overrides = overrides or {}

        # -------------------------
        # 1. Override
        # -------------------------
        if "time" in overrides:
            return TimeResult(time_window=overrides["time"])

        intent = classified_query.query_intent
        resolved_date = current_date or date.today()

        if isinstance(resolved_date, str):
            resolved_date = date.fromisoformat(resolved_date)

        # Handle different context types - convert to string for LLM
        context_str = ""
        if previous_context:
            if hasattr(previous_context, 'to_prompt_context'):
                # It's a QCO object
                context_str = previous_context.to_prompt_context()
            elif isinstance(previous_context, dict):
                context_str = json.dumps(previous_context)
            else:
                # Already a string
                context_str = str(previous_context)

        relevant_terms = [t.model_dump() for t in classified_query.classified_terms if t.role in ("TIME_RANGE", "TIME_GRANULARITY")]
        prediction = self.predict(
            classified_terms=json.dumps(relevant_terms),
            current_date=resolved_date.isoformat(),
            query_intent=intent,
            previous_context=context_str,
        )

        result: TimeResult = prediction.time_result

        # -------------------------
        # 2. Rule 5 — STRUCTURAL
        # -------------------------
        if intent in ["STRUCTURAL", "MINIMAL_MESSAGE"]:
            raise ClarificationRequired(build_time_clarification(ambiguous_expression="time period", candidate_windows=sorted(TIME_WINDOWS)))

        # -------------------------
        # 3. Detect explicit time
        # -------------------------
        has_time_terms = any(
            t.role == "TIME_RANGE"
            for t in classified_query.classified_terms
        )

        has_window = bool(result.time_window or result.start_date or result.end_date)

        # -------------------------
        # 4. Rule 1 — Explicit time
        # -------------------------
        if has_time_terms:
            return result  # trust extraction fully

        # -------------------------
        # 5. Rule 2 — TREND
        # -------------------------
        if intent == "TREND":
            if not has_window:
                raise ClarificationRequired(
                    build_time_clarification(
                        ambiguous_expression="time period",
                        candidate_windows=sorted(TIME_WINDOWS)
                    )
                )

            # default granularity
            if not result.granularity:
                result.granularity = "week"

            return result

        # -------------------------
        # 6. Rule 3 — COMPARISON
        # -------------------------
        if intent == "COMPARISON":

            # For explicit date comparisons (feb vs march), window is None — dates are in TimeResult
            comparison_window = None
            if llm_comparison and llm_comparison.comparison_window:
                comparison_window = llm_comparison.comparison_window
            elif time_result and time_result.time_window:
                comparison_window = time_result.time_window
            # else: leave as None — explicit date ranges don't need a window

            derived_metric = (
                llm_metric if llm_metric != "none" else "period_change"
            )

            return PostProcessingResult(
                ranking=None,
                comparison=ComparisonConfig(
                    type="period",
                    comparison_window=comparison_window,  # None is valid per your model
                ),
                derived_metric=derived_metric,
            )

        # -------------------------
        # 7. Rule 4 — KPI / DISTRIBUTION / RANKING
        # -------------------------
        if intent in ["KPI", "DISTRIBUTION", "RANKING"]:

            # explicit handled already
            # fallback to context
            if not has_window and previous_context:
                # Handle QCO object for time context
                prev_time = None
                if hasattr(previous_context, 'time_range') and previous_context.time_range:
                    # Convert QCO time_range to TimeResult format
                    prev_time = {
                        "start_date": previous_context.time_range.start_date,
                        "end_date": previous_context.time_range.end_date
                    }
                elif isinstance(previous_context, dict):
                    prev_time = previous_context.get("time")

                if prev_time:
                    return TimeResult(**prev_time)

            # still nothing → ask
            if not has_window:
                raise ClarificationRequired(
                    build_time_clarification(
                        ambiguous_expression="time period",
                        candidate_windows=sorted(TIME_WINDOWS)
                    )
                )

            return result

        # -------------------------
        # Default fallback
        # -------------------------
        return result
# =============================================================================
# AGENT 4 — MetricsModule
# =============================================================================

class MetricsModule(dspy.Module):
    """
    Extracts canonical metric names and their aggregations from the classified query.

    Design:
        - LLM returns candidate metrics from catalog
        - Module enforces:
            1 candidate → accept
            >1 candidates → clarification
            0 candidates → clarification
    """

    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(ExtractMetrics)

        # Build once from schema
        self._catalog_str = json.dumps(METRICS_CATALOG)

        # Aggregation lookup
        self._agg_map = {
            m["name"]: m["aggregation"]
            for m in METRICS_CATALOG
        }

    def forward(
        self,
        classified_query: ClassifiedQuery,
        sales_scope: str,
        overrides: Optional[dict] = None,
    ) -> MetricsResult:

        overrides = overrides or {}

        # -------------------------
        # 1. Override (resume flow)
        # -------------------------
        if "metrics" in overrides:
            metrics_list = overrides["metrics"]
            if isinstance(metrics_list, str):
                metrics_list = [metrics_list]

            return MetricsResult(
                metrics=[
                    MetricSpec(
                        name=m,
                        aggregation=self._agg_map.get(m, "sum")
                    )
                    for m in metrics_list
                ],
                aggregations=[
                    self._agg_map.get(m, "sum")
                    for m in metrics_list
                ],
            )

        # -------------------------
        # 2. LLM extraction
        # -------------------------
        relevant_terms = [t.model_dump() for t in classified_query.classified_terms if t.role == "METRIC"]
        prediction = self.predict(
            classified_terms=json.dumps(relevant_terms),
            sales_scope=sales_scope,
            available_metrics=self._catalog_str,
        )

        result: MetricsResult = prediction.metrics_result

        # -------------------------
        # 3. Validate against catalog
        # -------------------------
        valid_metrics = [
            m for m in result.metrics
            if m.name in CATALOG_METRICS
        ]

        # -------------------------
        # 4. Ambiguity handling
        # -------------------------

        metric_terms = [
            t.term for t in classified_query.classified_terms
            if t.role == "METRIC"
        ]

        # ❗ No valid metric → ask user
        if len(valid_metrics) == 0:
            raise ClarificationRequired(
                build_metric_clarification(
                    ambiguous_terms=metric_terms or ["metric"],
                    candidate_metrics=sorted(CATALOG_METRICS),
                )
            )

        # ❗ Multiple candidates or multiple terms → sequential clarification
        if len(valid_metrics) > 1 or len(metric_terms) > 1:

            # For multiple terms, use term-specific field names to track individual resolutions
            if len(metric_terms) > 1:
                resolved_metrics = []
                pending_terms = []

                # Check which terms have been resolved using term-specific override keys
                for term in metric_terms:
                    term_field_key = f"metric_term_{term}"
                    if term_field_key in overrides:
                        resolved_metric = overrides[term_field_key]
                        if resolved_metric in CATALOG_METRICS:
                            resolved_metrics.append(MetricSpec(
                                name=resolved_metric,
                                aggregation=self._agg_map.get(resolved_metric, "sum")
                            ))
                    else:
                        pending_terms.append(term)

                if pending_terms:
                    # Loop through pending terms — auto-resolve singletons, ask only when truly ambiguous
                    for first_pending in list(pending_terms):
                        term_field_key = f"metric_term_{first_pending}"

                        # Create context message about progress
                        total_terms = len(metric_terms)
                        resolved_count = total_terms - len(pending_terms)
                        context = f"Resolving metric term {resolved_count + 1} of {total_terms}: '{first_pending}'"

                        # Get term-specific candidates by running LLM scoped to just this term
                        term_classified = [t.model_dump() for t in classified_query.classified_terms if t.role == "METRIC" and t.term == first_pending]
                        term_prediction = self.predict(
                            classified_terms=json.dumps(term_classified),
                            sales_scope=sales_scope,
                            available_metrics=self._catalog_str,
                        )
                        term_candidates = [
                            m.name for m in (term_prediction.metrics_result.metrics or [])
                            if m.name in CATALOG_METRICS
                        ]

                        if len(term_candidates) == 1:
                            # Exactly one match — auto-resolve, no question needed
                            resolved_metrics.append(MetricSpec(
                                name=term_candidates[0],
                                aggregation=self._agg_map.get(term_candidates[0], "sum")
                            ))
                            pending_terms.remove(first_pending)
                        else:
                            # 0 or 2+ candidates — ask the user
                            term_options = sorted(term_candidates) if term_candidates else sorted(CATALOG_METRICS)
                            raise ClarificationRequired(Clarification(
                                request_id=str(uuid.uuid4()),
                                field=term_field_key,
                                question=f"Which metric do you mean by '{first_pending}'?",
                                options=term_options,
                                multi_select=False,
                                context=context,
                                clarifying_term=first_pending,
                            ))

                    # All pending terms auto-resolved — return immediately
                    return MetricsResult(
                        metrics=resolved_metrics,
                        aggregations=[self._agg_map.get(m.name, "sum") for m in resolved_metrics],
                    )

                else:
                    # All terms resolved
                    if resolved_metrics:
                        return MetricsResult(
                            metrics=resolved_metrics,
                            aggregations=[self._agg_map.get(m.name, "sum") for m in resolved_metrics],
                        )
                    else:
                        # Fallback if resolution failed
                        raise ClarificationRequired(
                            build_metric_clarification(
                                ambiguous_terms=metric_terms,
                                candidate_metrics=sorted(CATALOG_METRICS),
                            )
                        )

            else:
                # Single term, multiple candidates → standard clarification
                raise ClarificationRequired(
                    build_metric_clarification(
                        ambiguous_terms=metric_terms,
                        candidate_metrics=[m.name for m in valid_metrics],
                    )
                )

        # -------------------------
        # 5. Single metric → accept
        # -------------------------
        metric = valid_metrics[0]

        return MetricsResult(
            metrics=[metric],
            aggregations=[self._agg_map[metric.name]],
        )

# =============================================================================
# AGENT 5 — DimensionsModule
# =============================================================================

class DimensionsModule(dspy.Module):
    """
    Resolves group-by dimensions and filter conditions from the classified query.

    Design:
        - LLM returns candidate dimensions from catalog
        - Module enforces:
            1 candidate → accept
            >1 candidates → clarification
            0 candidates → clarification
    """

    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(ResolveDimensions)

    @staticmethod
    def _build_dimensions_catalog(sales_scope: str) -> str:
        """Return JSON catalog of valid dimensions (minimal, LLM-friendly)."""
        valid_dims = get_valid_dimensions_for_scope(sales_scope)

        catalog = [
            {
                "name": d,
                "description": d.replace("_", " ")
            }
            for d in sorted(valid_dims)
        ]

        return json.dumps(catalog)

    def forward(
        self,
        classified_query: ClassifiedQuery,
        sales_scope: str,
        previous_context=None,
        x_axis_values: Optional[list[str]] = None,
        overrides: Optional[dict] = None,
    ) -> DimensionsResult:

        overrides = overrides or {}

        # -------------------------
        # 1. Override
        # -------------------------
        if "group_by" in overrides:
            gb = overrides["group_by"]
            if isinstance(gb, str):
                gb = [gb]

            return DimensionsResult(group_by=gb, filters=None)

        valid_dims = get_valid_dimensions_for_scope(sales_scope)

        # -------------------------
        # 2. LLM extraction
        # -------------------------
        # Handle different context types - convert to string for LLM
        context_str = ""
        x_axis_labels_str = "[]"
        if previous_context:
            if hasattr(previous_context, 'to_prompt_context'):
                x_axis_list = getattr(previous_context, "x_axis_labels", [])
                x_axis_dim = getattr(previous_context, "group_by", [None])[0]  # e.g. "zone"
                if x_axis_list and x_axis_dim:
                    x_axis_labels_str = json.dumps({
                        "dimension": x_axis_dim,
                        "values": x_axis_list
                    })
            elif isinstance(previous_context, dict):
                x_axis_list = previous_context.get("x_axis_labels", [])
                x_axis_dim = (previous_context.get("group_by") or [None])[0]
                if x_axis_list and x_axis_dim:
                    x_axis_labels_str = json.dumps({
                        "dimension": x_axis_dim,
                        "values": x_axis_list
                    })
            else:
                # Already a string
                context_str = str(previous_context)

        # Override with explicit parameter if provided
        if x_axis_values:
            x_axis_labels_str = json.dumps(x_axis_values)

        catalog_str = self._build_dimensions_catalog(sales_scope)

        relevant_terms = [t.model_dump() for t in classified_query.classified_terms if t.role in ("DIMENSION", "FILTER_VALUE")]
        prediction = self.predict(
            classified_terms=json.dumps(relevant_terms),
            sales_scope=sales_scope,
            available_dimensions=catalog_str,
            previous_context=context_str,
            x_axis_values=x_axis_labels_str,
        )

        result: DimensionsResult = prediction.dimensions_result

        # -------------------------
        # 3. Validate candidates
        # -------------------------
        valid_group_by = [
            d for d in (result.group_by or [])
            if d in valid_dims and d != "invoice_date"
        ]

        # Compute valid_filters early so it's available in all branches below
        valid_filters = None
        if result.filters:
            valid_filters = [
                f for f in result.filters
                if f.dimension in valid_dims
            ] or None

        # -------------------------
        # 4. Ambiguity handling (CORE)
        # -------------------------
        dim_terms = [
            t.term for t in classified_query.classified_terms
            if t.role == "DIMENSION"
        ]

        # ❗ No valid dimension
        if len(valid_group_by) == 0 and classified_query.query_intent in ["DISTRIBUTION", "RANKING"]:
            raise ClarificationRequired(
                build_dimension_clarification(
                    ambiguous_terms=dim_terms or ["dimension"],
                    candidate_dimensions=sorted(valid_dims),
                )
            )

        # ❗ Multiple candidates or multiple terms → sequential clarification
        if len(valid_group_by) > 1 or len(dim_terms) > 1:

            # For multiple terms, use term-specific field names to track individual resolutions
            if len(dim_terms) > 1:
                resolved_dimensions = []
                pending_terms = []

                # Check which terms have been resolved using term-specific override keys
                for term in dim_terms:
                    term_field_key = f"dimension_term_{term}"
                    if term_field_key in overrides:
                        resolved_dimension = overrides[term_field_key]
                        if resolved_dimension in valid_dims and resolved_dimension != "invoice_date":
                            resolved_dimensions.append(resolved_dimension)
                    else:
                        pending_terms.append(term)

                if pending_terms:
                    # Loop through pending terms — auto-resolve singletons, ask only when truly ambiguous
                    for first_pending in list(pending_terms):
                        term_field_key = f"dimension_term_{first_pending}"

                        # Create context message about progress
                        total_terms = len(dim_terms)
                        resolved_count = total_terms - len(pending_terms)
                        context = f"Resolving dimension term {resolved_count + 1} of {total_terms}: '{first_pending}'"

                        # Get term-specific candidates by running LLM scoped to just this term
                        term_classified = [t.model_dump() for t in classified_query.classified_terms if t.role in ("DIMENSION", "FILTER_VALUE") and t.term == first_pending]
                        term_prediction = self.predict(
                            classified_terms=json.dumps(term_classified),
                            sales_scope=sales_scope,
                            available_dimensions=catalog_str,
                            previous_context=context_str,
                            x_axis_values=x_axis_labels_str,
                        )
                        term_candidates = [
                            d for d in (term_prediction.dimensions_result.group_by or [])
                            if d in valid_dims and d != "invoice_date"
                        ]

                        if len(term_candidates) == 1:
                            # Exactly one match — auto-resolve, no question needed
                            resolved_dimensions.append(term_candidates[0])
                            pending_terms.remove(first_pending)
                        else:
                            # 0 or 2+ candidates — ask the user
                            term_options = sorted(term_candidates) if term_candidates else sorted(valid_dims)
                            raise ClarificationRequired(Clarification(
                                request_id=str(uuid.uuid4()),
                                field=term_field_key,
                                question=f"Which dimension do you mean by '{first_pending}'?",
                                options=term_options,
                                multi_select=False,
                                context=context,
                                clarifying_term=first_pending,
                            ))

                    # All pending terms auto-resolved — return immediately
                    return DimensionsResult(
                        group_by=resolved_dimensions if resolved_dimensions else None,
                        filters=valid_filters,
                    )

                else:
                    # All terms resolved via overrides
                    return DimensionsResult(
                        group_by=resolved_dimensions if resolved_dimensions else None,
                        filters=valid_filters,
                    )

            else:
                # Single term, multiple candidates → standard clarification
                raise ClarificationRequired(
                    build_dimension_clarification(
                        ambiguous_terms=dim_terms,
                        candidate_dimensions=valid_group_by,
                    )
                )

        # -------------------------
        # 5. Final result
        # -------------------------
        return DimensionsResult(
            group_by=valid_group_by if valid_group_by else None,
            filters=valid_filters,
        )

# =============================================================================
# AGENT 6 — PostProcessingModule
# =============================================================================

## HELPER CLASS

class PostProcessingResolver:
    def resolve(
        self,
        classified_query: ClassifiedQuery,
        time_result: TimeResult,
        dimensions_result: DimensionsResult,
        llm_output: PostProcessingResult,
    ) -> PostProcessingResult:

        intent = classified_query.query_intent

        # Extract LLM hints safely
        llm_ranking = llm_output.ranking
        llm_comparison = llm_output.comparison
        llm_metric = llm_output.derived_metric

        # =====================================================
        # HARD CONSTRAINT: ranking requires group_by
        # =====================================================
        has_grouping = bool(dimensions_result and dimensions_result.group_by)

        # =====================================================
        # INTENT: RANKING
        # =====================================================
        if intent == "RANKING" and has_grouping:

            order = (
                llm_ranking.order
                if llm_ranking and llm_ranking.order
                else "desc"
            )

            limit = (
                llm_ranking.limit
                if llm_ranking and llm_ranking.limit
                else 10
            )

            return PostProcessingResult(
                ranking=RankingConfig(
                    enabled=True,
                    order=order,
                    limit=limit,
                ),
                comparison=None,
                derived_metric="none",
            )

        # If no grouping → ranking invalid
        if intent == "RANKING" and not has_grouping:
            return PostProcessingResult(
                ranking=None,
                comparison=None,
                derived_metric="none",
            )

        # =====================================================
        # INTENT: COMPARISON
        # =====================================================
        if intent == "COMPARISON":
            # Check if explicit date ranges are present in the query
            time_range_terms = [
                t for t in classified_query.classified_terms 
                if t.role == "TIME_RANGE"
            ]
            
            comparison_window = None
            if llm_comparison and llm_comparison.comparison_window:
                comparison_window = llm_comparison.comparison_window
            elif not time_range_terms and time_result and time_result.time_window:
                # Only fall back to time_window if no explicit date terms exist
                comparison_window = time_result.time_window

            return PostProcessingResult(
                ranking=None,
                comparison=ComparisonConfig(
                    type="period",
                    comparison_window=comparison_window,
                ),
                derived_metric=llm_metric if llm_metric != "none" else "period_change",
            )

        # =====================================================
        # INTENT: TREND
        # =====================================================
        if intent == "TREND":

            window = time_result.time_window if time_result else None

            if window == "last_7_days":
                metric = "wow_growth"
            elif window in ["last_30_days", "month_to_date"]:
                metric = "mom_growth"
            elif window in ["last_year", "year_to_date"]:
                metric = "yoy_growth"
            else:
                metric = "none"

            return PostProcessingResult(
                ranking=None,
                comparison=None,
                derived_metric=metric,
            )

        # =====================================================
        # DEFAULT: KPI / DISTRIBUTION / DRILL_DOWN / etc.
        # =====================================================
        return PostProcessingResult(
            ranking=None,
            comparison=None,
            derived_metric="none",
        )

class PostProcessingModule(dspy.Module):

    def __init__(self):
        super().__init__()
        self.predict = dspy.Predict(ResolvePostProcessing)
        self.resolver = PostProcessingResolver()

    def forward(
        self,
        classified_query: ClassifiedQuery,
        time_result: TimeResult,
        dimensions_result: DimensionsResult,
    ) -> PostProcessingResult:

        relevant_terms = [t.model_dump() for t in classified_query.classified_terms if t.role in ("RANKING", "COMPARISON", "TREND")]
        llm_output = self.predict(
            query_intent=classified_query.query_intent,
            classified_terms=json.dumps(relevant_terms),
            time_result=time_result,
            dimensions_result=dimensions_result,
        ).post_processing_result

        return self.resolver.resolve(
            classified_query,
            time_result,
            dimensions_result,
            llm_output,
        )


# =============================================================================
# AGENT 7 — AssemblerModule
# =============================================================================

# class AssemblerModule(dspy.Module):
#     """
#     Merges all upstream agent outputs into the final typed Intent.

#     Inputs  : ClassifiedQuery, ScopeResult, TimeResult, MetricsResult, DimensionsResult
#     Outputs : Intent
#     """

#     def __init__(self):
#         super().__init__()
#         self.predict = dspy.Predict(AssembleIntent)

#     def forward(
#         self,
#         classified_query: ClassifiedQuery,
#         scope_result: ScopeResult,
#         time_result: TimeResult,
#         metrics_result: MetricsResult,
#         dimensions_result: DimensionsResult,
#         post_processing_result: PostProcessingResult,
#     ) -> Intent:
#         """
#         Assemble the final Intent from all upstream results.

#         The LLM handles post_processing derivation (RANKING/COMPARISON/TREND
#         logic) as described in the AssembleIntent signature.  The module
#         trusts Pydantic validation on the Intent model to catch structural
#         issues, logging a warning and re-raising for the caller to handle.

#         Args:
#             classified_query   : Output of ClassifierModule.
#             scope_result       : Output of ScopeModule.
#             time_result        : Output of TimeModule.
#             metrics_result     : Output of MetricsModule.
#             dimensions_result  : Output of DimensionsModule.

#         Returns:
#             Fully populated Intent object.
#         """
#         prediction = self.predict(
#             classified_query=classified_query,
#             scope_result=scope_result,
#             time_result=time_result,
#             metrics_result=metrics_result,
#             dimensions_result=dimensions_result,
#             post_processing_result=post_processing_result,
#         )
#         intent: Intent = prediction.final_intent
#         return intent


class AssemblerModule:
    def forward(
        self,
        classified_query,
        scope_result,
        time_result,
        metrics_result,
        dimensions_result,
        post_processing_result,
    ) -> Intent:

        # -------------------------
        # Metrics (already structured)
        # -------------------------
        # MetricsResult.metrics is already List[MetricSpec]
        metrics = metrics_result.metrics if metrics_result else []

        # -------------------------
        # Time
        # -------------------------
        time_spec = None
        if time_result and (
            time_result.time_window or
            time_result.start_date or
            time_result.end_date
        ):
            time_spec = TimeSpec(
                # alias handles mapping internally
                time_window=time_result.time_window,
                start_date=time_result.start_date,
                end_date=time_result.end_date,
                granularity=time_result.granularity,
            )

        # -------------------------
        # Filters — merge dimensions filters + classifier filter_hints
        # -------------------------
        filters = dimensions_result.filters if dimensions_result else None

        if not filters and classified_query.filter_hints:
            filters = [
                FilterCondition(
                    dimension=hint.dimension,
                    operator="equals",
                    value=hint.value,
                )
                for hint in classified_query.filter_hints
            ]

        # -------------------------
        # Final Intent
        # -------------------------
        return Intent(
            sales_scope=scope_result.sales_scope if scope_result else "SECONDARY",
            metrics=metrics,
            group_by=dimensions_result.group_by if dimensions_result else None,
            filters=filters,  # ← use merged filters
            time=time_spec,
            post_processing=post_processing_result,
        )

# =============================================================================
# PIPELINE — IntentExtractionPipeline
# # =============================================================================

# class IntentExtractionPipeline(dspy.Module):
#     """
#     Orchestrates all six agents in sequence and returns the final Intent.

#     Usage:
#         pipeline = IntentExtractionPipeline()
#         intent   = pipeline(query="top 5     The pipeline is stateless. Multi-turn context must be supplied via
#     `previous_context` on each call.
#     """

#     def __init__(self):
#         super().__init__()
#         self.classifier  = ClassifierModule()
#         self.scope       = ScopeModule()
#         self.time        = TimeModule()
#         self.metrics     = MetricsModule()
#         self.dimensions  = DimensionsModule()
#         self.assembler   = AssemblerModule()

#     def forward(
#         self,
#         query: str,
#         current_date: Optional[date] = None,
#         previous_context: Optional[dict] = None,
#     ) -> Intent:
#         """
#         Run the full intent extraction pipeline for a single query.

#         Execution order:
#             1. ClassifierModule  — classify all terms and determine query_intent
#             2. ScopeModule       — resolve PRIMARY / SECONDARY (parallel-safe)
#             3. TimeModule        — resolve time window + granularity (parallel-safe)
#             4. MetricsModule     — extract and validate metrics (parallel-safe)
#             5. DimensionsModule  — resolve group_by and filters (parallel-safe)
#             6. AssemblerModule   — merge outputs into final Intent

#         Steps 2–5 are data-independent after step 1 and can be parallelised if
#         the execution framework supports it (e.g. dspy.Parallel or asyncio).

#         Args:
#             query            : Raw natural-language query from the user.
#             current_date     : Today's date; defaults to date.today().
#             previous_context : Prior QCO result dict for multi-turn conversations.

#         Returns:
#             Intent object ready for downstream query construction.
#         """
#         # Step 1: Classify
#         classified_query = self.classifier(query=query)

#         # Steps 2-5: Resolve independently (sequential for now)
#         scope_result = self.scope(classified_query=classified_query)

#         time_result = self.time(
#             classified_query=classified_query,
#             current_date=current_date,
#             previous_context=previous_context,
#         )

#         metrics_result = self.metrics(
#             classified_query=classified_query,
#             sales_scope=scope_result.sales_scope,
#         )

#         dimensions_result = self.dimensions(
#             classified_query=classified_query,
#             sales_scope=scope_result.sales_scope,
#             previous_context=previous_context,
#         )

#         # Step 6: Assemble
#         intent = self.assembler(
#             classified_query=classified_query,
#             scope_result=scope_result,
#             time_result=time_result,
#             metrics_result=metrics_result,
#             dimensions_result=dimensions_result,
#         )

#         return intent