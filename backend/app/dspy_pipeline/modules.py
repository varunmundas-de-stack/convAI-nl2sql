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
from datetime import date
from typing import Optional

import dspy

from .schemas import (
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
    build_scope_clarification,
    build_metric_clarification,
    build_dimension_clarification,
    build_time_clarification,
)
from .signatures import (
    ClassifyQuery,
    ResolveScope,
    ResolveTime,
    ExtractMetrics,
    ResolveDimensions,
    ResolvePostProcessing,
)

logger = logging.getLogger(__name__)


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

    def forward(self, query: str) -> ClassifiedQuery:
        """
        Run ClassifyQuery signature and return a validated ClassifiedQuery.

        Args:
            query: Raw natural-language query from the user.

        Returns:
            ClassifiedQuery with classified_terms, query_intent,
            filter_hints, and explicit_scope populated.
        """

        prediction = self.predict(query=query)
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
        prediction = self.predict(classified_query=classified_query)
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
        previous_context: Optional[dict] = None,
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

        context_str = json.dumps(previous_context) if previous_context else ""

        prediction = self.predict(
            classified_query=classified_query,
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
            # assuming comparison_window is handled in schema
            if not result.time_window:
                raise ClarificationRequired(
                    build_time_clarification(
                        ambiguous_expression="primary time period",
                        candidate_windows=sorted(TIME_WINDOWS)
                    )
                )

            # if comparison missing → ask
            if not getattr(result, "comparison_window", None):
                raise ClarificationRequired(
                    build_time_clarification(
                        ambiguous_expression="comparison time period",
                        candidate_windows=sorted(TIME_WINDOWS)
                    )
                )

            return result

        # -------------------------
        # 7. Rule 4 — KPI / DISTRIBUTION / RANKING
        # -------------------------
        if intent in ["KPI", "DISTRIBUTION", "RANKING"]:

            # explicit handled already
            # fallback to context
            if not has_window and previous_context:
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
        prediction = self.predict(
            classified_query=classified_query,
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

        # ❗ Multiple candidates → ambiguity
        if len(valid_metrics) > 1:
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
        previous_context: Optional[dict] = None,
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
        context_str = json.dumps(previous_context) if previous_context else ""
        catalog_str = self._build_dimensions_catalog(sales_scope)

        prediction = self.predict(
            classified_query=classified_query,
            sales_scope=sales_scope,
            available_dimensions=catalog_str,
            previous_context=context_str,
        )

        result: DimensionsResult = prediction.dimensions_result

        # -------------------------
        # 3. Validate candidates
        # -------------------------
        valid_group_by = [
            d for d in (result.group_by or [])
            if d in valid_dims and d != "invoice_date"
        ]

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

        # ❗ Multiple candidates → ambiguity
        if len(valid_group_by) > 1:
            raise ClarificationRequired(
                build_dimension_clarification(
                    ambiguous_terms=dim_terms,
                    candidate_dimensions=valid_group_by,
                )
            )

        # -------------------------
        # 5. Filters validation
        # -------------------------
        valid_filters = None
        if result.filters:
            valid_filters = [
                f for f in result.filters
                if f.dimension in valid_dims
            ]
            if not valid_filters:
                valid_filters = None

        # -------------------------
        # 6. Final result
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
        has_grouping = bool(dimensions_result.group_by)

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

            comparison_window = (
                llm_comparison.comparison_window
                if llm_comparison and llm_comparison.comparison_window
                else time_result.time_window or "previous_period"
            )

            derived_metric = (
                llm_metric
                if llm_metric != "none"
                else "period_change"
            )

            return PostProcessingResult(
                ranking=None,
                comparison=ComparisonConfig(
                    type="period",
                    comparison_window=comparison_window,
                ),
                derived_metric=derived_metric,
            )

        # =====================================================
        # INTENT: TREND
        # =====================================================
        if intent == "TREND":

            window = time_result.time_window

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

        llm_output = self.predict(
            classified_query=classified_query,
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
        metrics = metrics_result.metrics

        # -------------------------
        # Time
        # -------------------------
        time_spec = None
        if (
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
        # Final Intent
        # -------------------------
        return Intent(
            sales_scope=scope_result.sales_scope,
            metrics=metrics,
            group_by=dimensions_result.group_by,
            filters=dimensions_result.filters,
            time=time_spec,
            post_processing=post_processing_result,
        )

# =============================================================================
# PIPELINE — IntentExtractionPipeline
# =============================================================================

class IntentExtractionPipeline(dspy.Module):
    """
    Orchestrates all six agents in sequence and returns the final Intent.

    Usage:
        pipeline = IntentExtractionPipeline()
        intent   = pipeline(query="top 5 brands by net value last month")

    The pipeline is stateless. Multi-turn context must be supplied via
    `previous_context` on each call.
    """

    def __init__(self):
        super().__init__()
        self.classifier  = ClassifierModule()
        self.scope       = ScopeModule()
        self.time        = TimeModule()
        self.metrics     = MetricsModule()
        self.dimensions  = DimensionsModule()
        self.assembler   = AssemblerModule()

    def forward(
        self,
        query: str,
        current_date: Optional[date] = None,
        previous_context: Optional[dict] = None,
    ) -> Intent:
        """
        Run the full intent extraction pipeline for a single query.

        Execution order:
            1. ClassifierModule  — classify all terms and determine query_intent
            2. ScopeModule       — resolve PRIMARY / SECONDARY (parallel-safe)
            3. TimeModule        — resolve time window + granularity (parallel-safe)
            4. MetricsModule     — extract and validate metrics (parallel-safe)
            5. DimensionsModule  — resolve group_by and filters (parallel-safe)
            6. AssemblerModule   — merge outputs into final Intent

        Steps 2–5 are data-independent after step 1 and can be parallelised if
        the execution framework supports it (e.g. dspy.Parallel or asyncio).

        Args:
            query            : Raw natural-language query from the user.
            current_date     : Today's date; defaults to date.today().
            previous_context : Prior QCO result dict for multi-turn conversations.

        Returns:
            Intent object ready for downstream query construction.
        """
        # Step 1: Classify
        classified_query = self.classifier(query=query)

        # Steps 2-5: Resolve independently (sequential for now)
        scope_result = self.scope(classified_query=classified_query)

        time_result = self.time(
            classified_query=classified_query,
            current_date=current_date,
            previous_context=previous_context,
        )

        metrics_result = self.metrics(
            classified_query=classified_query,
            sales_scope=scope_result.sales_scope,
        )

        dimensions_result = self.dimensions(
            classified_query=classified_query,
            sales_scope=scope_result.sales_scope,
            previous_context=previous_context,
        )

        # Step 6: Assemble
        intent = self.assembler(
            classified_query=classified_query,
            scope_result=scope_result,
            time_result=time_result,
            metrics_result=metrics_result,
            dimensions_result=dimensions_result,
        )

        return intent