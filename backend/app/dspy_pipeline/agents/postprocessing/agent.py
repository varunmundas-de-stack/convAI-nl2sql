from typing import Optional, List, Dict, Any, Union
import dspy
import json
import logging
import time
from opentelemetry.trace import Status, StatusCode
from app.utils.tracer import get_tracer
from app.utils.tracer import _span_set

logger = logging.getLogger(__name__)
from app.dspy_pipeline.schemas import PostProcessingResult, ClassifiedQuery, TimeResult, DimensionsResult, RankingConfig, ComparisonConfig
from .signature import ResolvePostProcessing
tracer = get_tracer(__name__)

from app.dspy_pipeline.schemas import PostProcessingResult, ClassifiedQuery, TimeResult, DimensionsResult, RankingConfig, ComparisonConfig
from .signature import ResolvePostProcessing

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
            time_range_terms = [
                t for t in classified_query.classified_terms
                if t.role == "TIME_RANGE"
            ]

            comparison_window = None
            if llm_comparison and llm_comparison.comparison_window:
                # LLM explicitly resolved a window
                comparison_window = llm_comparison.comparison_window
            elif time_range_terms and time_result and time_result.time_window:
                # TIME_RANGE terms present and TimeModule resolved a window → use as comparison
                comparison_window = time_result.time_window
            # else: explicit start/end dates (feb vs march case) → leave as None

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
        self.predict = dspy.ChainOfThought(ResolvePostProcessing)
        self.resolver = PostProcessingResolver()

    def forward(
        self,
        classified_query: ClassifiedQuery,
        time_result: TimeResult,
        dimensions_result: DimensionsResult,
    ) -> PostProcessingResult:
        with tracer.start_as_current_span("dspy.post_processing") as span:
            relevant_terms = [t for t in classified_query.classified_terms if t.role in ("RANKING", "COMPARISON", "TREND")]
            _span_set(span,
                input_intent=classified_query.query_intent,
                input_relevant_terms=len(relevant_terms),
                input_has_time_result=time_result is not None,
                input_has_dimensions_result=dimensions_result is not None
            )

            try:
                start_time = time.monotonic()

                relevant_terms = [t.model_dump() for t in classified_query.classified_terms if t.role in ("RANKING", "COMPARISON", "TREND")]
                llm_output = self.predict(
                    original_query=classified_query.original_query,
                    query_intent=classified_query.query_intent,
                    classified_terms=json.dumps(relevant_terms),
                    time_result=time_result,
                    dimensions_result=dimensions_result,
                ).post_processing_result

                result = self.resolver.resolve(
                    classified_query,
                    time_result,
                    dimensions_result,
                    llm_output,
                )

                duration_ms = int((time.monotonic() - start_time) * 1000)
                _span_set(span,
                    output_ranking=str(result.ranking) if result.ranking else "",
                    output_comparison=str(result.comparison) if result.comparison else "",
                    output_derived_metric=result.derived_metric or "",
                    output_duration_ms=duration_ms,
                    output_value=result.model_dump() if hasattr(result, "model_dump") else str(result)
                )

                logger.debug(f"[DSPy PostProcessing] Completed in {duration_ms}ms | ranking={bool(result.ranking)} | comparison={bool(result.comparison)} | derived={result.derived_metric}")
                return result

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                _span_set(span, error_type=type(e).__name__, error_message=str(e))
                logger.error(f"[DSPy PostProcessing] Error: {e}")
                raise
