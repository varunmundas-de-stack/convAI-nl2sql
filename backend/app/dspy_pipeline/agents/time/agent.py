from typing import Optional, List, Dict, Any, Union
from datetime import date
import dspy
import json
import logging
import time
from opentelemetry.trace import Status, StatusCode
from app.utils.tracer import get_tracer
from app.utils.tracer import _span_set

logger = logging.getLogger(__name__)
from app.dspy_pipeline.schemas import TimeResult, ClassifiedQuery, TIME_WINDOWS
from .signature import ResolveTime
from app.dspy_pipeline.clarification_tool import ClarificationRequired, Clarification, build_time_clarification
import uuid
tracer = get_tracer(__name__)


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
        with tracer.start_as_current_span("dspy.time") as span:
            time_terms = [t for t in classified_query.classified_terms if t.role in ("TIME_RANGE", "TIME_GRANULARITY")]
            _span_set(span,
                input_intent=classified_query.query_intent,
                input_time_terms=len(time_terms),
                input_has_context=previous_context is not None,
                input_has_overrides=bool(overrides),
                input_current_date=current_date.isoformat() if hasattr(current_date, 'isoformat') else str(current_date or "")
            )

            try:
                start_time = time.monotonic()
                overrides = overrides or {}

                # -------------------------
                # 1. Override
                # -------------------------
                if "time" in overrides:
                    result = TimeResult(time_window=overrides["time"])
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="override",
                        output_time_window=result.time_window or "",
                        output_duration_ms=duration_ms
                    )
                    logger.debug(f"[DSPy Time] Override used: {result.time_window}")
                    return result

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
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="clarification_required",
                        output_duration_ms=duration_ms,
                        clarification_field="time",
                        clarification_reason="structural_intent"
                    )
                    logger.debug(f"[DSPy Time] Clarification required for structural intent")
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
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="explicit_terms",
                        output_time_window=result.time_window or "",
                        output_start_date=result.start_date or "",
                        output_end_date=result.end_date or "",
                        output_duration_ms=duration_ms,
                        output_value=result.model_dump() if hasattr(result, "model_dump") else str(result)
                    )
                    logger.debug(f"[DSPy Time] Explicit terms - completed in {duration_ms}ms")
                    return result  # trust extraction fully

                # -------------------------
                # 5. Rule 2 — TREND
                # -------------------------
                if intent == "TREND":
                    if not has_window:
                        duration_ms = int((time.monotonic() - start_time) * 1000)
                        _span_set(span,
                            output_source="clarification_required",
                            output_duration_ms=duration_ms,
                            clarification_field="time",
                            clarification_reason="trend_missing_window"
                        )
                        logger.debug(f"[DSPy Time] Clarification required for TREND without window")
                        raise ClarificationRequired(
                            build_time_clarification(
                                ambiguous_expression="time period",
                                candidate_windows=sorted(TIME_WINDOWS)
                            )
                        )

                    # default granularity
                    if not result.granularity:
                        result.granularity = "week"

                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="trend_logic",
                        output_time_window=result.time_window or "",
                        output_granularity=result.granularity,
                        output_duration_ms=duration_ms,
                        output_value=result.model_dump() if hasattr(result, "model_dump") else str(result)
                    )
                    logger.debug(f"[DSPy Time] TREND logic - completed in {duration_ms}ms")
                    return result

                # -------------------------
                # 6. Rule 3 — COMPARISON
                # -------------------------
                if intent == "COMPARISON":
                    # If explicit TIME_RANGE terms exist (feb, last quarter, etc.)
                    # trust the LLM extraction fully — dates or window are the comparison period
                    if has_time_terms:
                        duration_ms = int((time.monotonic() - start_time) * 1000)
                        _span_set(span,
                            output_source="comparison_explicit",
                            output_time_window=result.time_window or "",
                            output_duration_ms=duration_ms,
                            output_value=result.model_dump() if hasattr(result, "model_dump") else str(result)
                        )
                        logger.debug(f"[DSPy Time] COMPARISON explicit - completed in {duration_ms}ms")
                        return result

                    # No explicit time terms — fall back to previous context
                    if not has_window and previous_context:
                        if hasattr(previous_context, 'time_range') and previous_context.time_range:
                            context_result = TimeResult(
                                start_date=previous_context.time_range.start_date,
                                end_date=previous_context.time_range.end_date,
                            )
                            duration_ms = int((time.monotonic() - start_time) * 1000)
                            _span_set(span,
                                output_source="context_qco",
                                output_start_date=context_result.start_date,
                                output_end_date=context_result.end_date,
                                output_duration_ms=duration_ms
                            )
                            logger.debug(f"[DSPy Time] COMPARISON from QCO context - completed in {duration_ms}ms")
                            return context_result
                        elif isinstance(previous_context, dict):
                            prev_time = previous_context.get("time")
                            if prev_time:
                                context_result = TimeResult(**prev_time)
                                duration_ms = int((time.monotonic() - start_time) * 1000)
                                _span_set(span,
                                    output_source="context_dict",
                                    output_duration_ms=duration_ms,
                                    output_value=context_result.model_dump() if hasattr(context_result, "model_dump") else str(context_result)
                                )
                                logger.debug(f"[DSPy Time] COMPARISON from dict context - completed in {duration_ms}ms")
                                return context_result

                    # Has window or nothing available — return as-is
                    # PostProcessingResolver will map time_window → comparison_window
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="comparison_fallback",
                        output_time_window=result.time_window or "",
                        output_duration_ms=duration_ms,
                        output_value=result.model_dump() if hasattr(result, "model_dump") else str(result)
                    )
                    logger.debug(f"[DSPy Time] COMPARISON fallback - completed in {duration_ms}ms")
                    return result

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
                            context_result = TimeResult(**prev_time)
                            duration_ms = int((time.monotonic() - start_time) * 1000)
                            _span_set(span,
                                output_source="kpi_context",
                                output_duration_ms=duration_ms,
                                output_value=context_result.model_dump() if hasattr(context_result, "model_dump") else str(context_result)
                            )
                            logger.debug(f"[DSPy Time] KPI/DIST/RANK from context - completed in {duration_ms}ms")
                            return context_result

                    # still nothing → ask
                    if not has_window:
                        duration_ms = int((time.monotonic() - start_time) * 1000)
                        _span_set(span,
                            output_source="clarification_required",
                            output_duration_ms=duration_ms,
                            clarification_field="time",
                            clarification_reason="kpi_missing_window"
                        )
                        logger.debug(f"[DSPy Time] Clarification required for KPI/DIST/RANK without window")
                        raise ClarificationRequired(
                            build_time_clarification(
                                ambiguous_expression="time period",
                                candidate_windows=sorted(TIME_WINDOWS)
                            )
                        )

                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="kpi_window",
                        output_time_window=result.time_window or "",
                        output_duration_ms=duration_ms,
                        output_value=result.model_dump() if hasattr(result, "model_dump") else str(result)
                    )
                    logger.debug(f"[DSPy Time] KPI/DIST/RANK with window - completed in {duration_ms}ms")
                    return result

                # -------------------------
                # Default fallback
                # -------------------------
                duration_ms = int((time.monotonic() - start_time) * 1000)
                _span_set(span,
                    output_source="default_fallback",
                    output_time_window=result.time_window or "",
                    output_duration_ms=duration_ms,
                    output_value=result.model_dump() if hasattr(result, "model_dump") else str(result)
                )
                logger.debug(f"[DSPy Time] Default fallback - completed in {duration_ms}ms")
                return result

            except ClarificationRequired:
                # Re-raise clarifications without logging as errors
                raise
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                _span_set(span, error_type=type(e).__name__, error_message=str(e))
                logger.error(f"[DSPy Time] Error: {e}")
                raise