from typing import Optional, List, Dict, Any, Union
import dspy
import json
import logging
import time
from opentelemetry.trace import Status, StatusCode
from app.utils.tracer import get_tracer
from app.utils.tracer import _span_set
from app.dspy_pipeline.schemas import MetricsResult, ClassifiedQuery, METRICS_CATALOG, CATALOG_METRICS, MetricSpec
from .signature import ExtractMetrics
from app.dspy_pipeline.clarification_tool import ClarificationRequired, Clarification, build_metric_clarification, build_individual_metric_clarifications
import uuid



logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)

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
        with tracer.start_as_current_span("dspy.metrics") as span:
            metric_terms = [t for t in classified_query.classified_terms if t.role == "METRIC"]
            _span_set(span,
                input_intent=classified_query.query_intent,
                input_metric_terms=len(metric_terms),
                input_sales_scope=sales_scope,
                input_has_overrides=bool(overrides)
            )

            try:
                start_time = time.monotonic()
                overrides = overrides or {}

                # -------------------------
                # 1. Override (resume flow)
                # -------------------------
                if "metrics" in overrides:
                    metrics_list = overrides["metrics"]
                    if isinstance(metrics_list, str):
                        metrics_list = [metrics_list]

                    result = MetricsResult(
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

                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="override",
                        output_metrics=str([m.name for m in result.metrics]),
                        output_duration_ms=duration_ms
                    )
                    logger.debug(f"[DSPy Metrics] Override used: {[m.name for m in result.metrics]}")
                    return result

                # -------------------------
                # 2. LLM extraction
                # -------------------------
                relevant_terms = [t.model_dump() for t in classified_query.classified_terms if t.role == "METRIC"]
                prediction = self.predict(
                    original_query=classified_query.original_query,
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
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="clarification_required",
                        output_duration_ms=duration_ms,
                        clarification_field="metrics",
                        clarification_reason="no_valid_metrics"
                    )
                    logger.debug(f"[DSPy Metrics] Clarification required - no valid metrics")
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
                                # Create a focused query context for this specific term to avoid confusion
                                focused_query = f"Show {first_pending} data"
                                term_classified = [t.model_dump() for t in classified_query.classified_terms if t.role == "METRIC" and t.term == first_pending]
                                term_prediction = self.predict(
                                    original_query=focused_query,  # Use focused query instead of full query
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
                                    duration_ms = int((time.monotonic() - start_time) * 1000)
                                    _span_set(span,
                                        output_source="clarification_required",
                                        output_duration_ms=duration_ms,
                                        clarification_field=term_field_key,
                                        clarification_reason="multiple_term_ambiguity",
                                        clarifying_term=first_pending
                                    )
                                    term_options = sorted(term_candidates) if term_candidates else sorted(CATALOG_METRICS)
                                    logger.debug(f"[DSPy Metrics] Clarification required for term: {first_pending}")
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
                            final_result = MetricsResult(
                                metrics=resolved_metrics,
                                aggregations=[self._agg_map.get(m.name, "sum") for m in resolved_metrics],
                            )
                            duration_ms = int((time.monotonic() - start_time) * 1000)
                            _span_set(span,
                                output_source="auto_resolved",
                                output_metrics=str([m.name for m in resolved_metrics]),
                                output_duration_ms=duration_ms,
                                output_value=final_result.model_dump() if hasattr(final_result, "model_dump") else str(final_result)
                            )
                            logger.debug(f"[DSPy Metrics] Auto-resolved multiple terms - completed in {duration_ms}ms")
                            return final_result

                        else:
                            # All terms resolved
                            if resolved_metrics:
                                final_result = MetricsResult(
                                    metrics=resolved_metrics,
                                    aggregations=[self._agg_map.get(m.name, "sum") for m in resolved_metrics],
                                )
                                duration_ms = int((time.monotonic() - start_time) * 1000)
                                _span_set(span,
                                    output_source="resolved_terms",
                                    output_metrics=str([m.name for m in resolved_metrics]),
                                    output_duration_ms=duration_ms,
                                    output_value=final_result.model_dump() if hasattr(final_result, "model_dump") else str(final_result)
                                )
                                logger.debug(f"[DSPy Metrics] All terms resolved - completed in {duration_ms}ms")
                                return final_result
                            else:
                                # Fallback if resolution failed
                                duration_ms = int((time.monotonic() - start_time) * 1000)
                                _span_set(span,
                                    output_source="clarification_required",
                                    output_duration_ms=duration_ms,
                                    clarification_field="metrics",
                                    clarification_reason="resolution_failed"
                                )
                                logger.debug(f"[DSPy Metrics] Resolution fallback clarification required")
                                raise ClarificationRequired(
                                    build_metric_clarification(
                                        ambiguous_terms=metric_terms,
                                        candidate_metrics=sorted(CATALOG_METRICS),
                                    )
                                )

                    else:
                        # Single term, multiple candidates → standard clarification
                        duration_ms = int((time.monotonic() - start_time) * 1000)
                        _span_set(span,
                            output_source="clarification_required",
                            output_duration_ms=duration_ms,
                            clarification_field="metrics",
                            clarification_reason="single_term_multiple_candidates"
                        )
                        logger.debug(f"[DSPy Metrics] Single term with multiple candidates - clarification required")
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

                final_result = MetricsResult(
                    metrics=[metric],
                    aggregations=[self._agg_map[metric.name]],
                )

                duration_ms = int((time.monotonic() - start_time) * 1000)
                _span_set(span,
                    output_source="single_match",
                    output_metrics=str([metric.name]),
                    output_duration_ms=duration_ms,
                    output_value=final_result.model_dump() if hasattr(final_result, "model_dump") else str(final_result)
                )

                logger.debug(f"[DSPy Metrics] Single metric resolved - completed in {duration_ms}ms | metric={metric.name}")
                return final_result

            except ClarificationRequired:
                # Re-raise clarifications without logging as errors
                raise
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                _span_set(span, error_type=type(e).__name__, error_message=str(e))
                logger.error(f"[DSPy Metrics] Error: {e}")
                raise