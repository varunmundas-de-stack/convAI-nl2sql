from typing import Optional, List, Dict, Any, Union
import dspy
import json
import logging
import time
from opentelemetry.trace import Status, StatusCode
from app.utils.tracer import get_tracer
from app.utils.tracer import _span_set

logger = logging.getLogger(__name__)
from app.dspy_pipeline.schemas import DimensionsResult, ClassifiedQuery
from .signature import ResolveDimensions
from app.dspy_pipeline.clarification_tool import ClarificationRequired, Clarification, build_dimension_clarification, build_individual_dimension_clarifications
import uuid
from app.dspy_pipeline.schemas import get_valid_dimensions_for_scope
tracer = get_tracer(__name__)

from app.dspy_pipeline.schemas import DimensionsResult, ClassifiedQuery
from .signature import ResolveDimensions
from app.dspy_pipeline.clarification_tool import ClarificationRequired, Clarification, build_dimension_clarification, build_individual_dimension_clarifications
import uuid
from app.dspy_pipeline.schemas import get_valid_dimensions_for_scope


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
        with tracer.start_as_current_span("dspy.dimensions") as span:
            dim_terms = [t for t in classified_query.classified_terms if t.role in ("DIMENSION", "FILTER_VALUE")]
            _span_set(span,
                input_intent=classified_query.query_intent,
                input_dim_terms=len(dim_terms),
                input_sales_scope=sales_scope,
                input_has_context=previous_context is not None,
                input_has_x_axis_values=x_axis_values is not None,
                input_has_overrides=bool(overrides)
            )

            try:
                start_time = time.monotonic()
                overrides = overrides or {}

                # -------------------------
                # 1. Override
                # -------------------------
                if "group_by" in overrides:
                    gb = overrides["group_by"]
                    if isinstance(gb, str):
                        gb = [gb]

                    result = DimensionsResult(group_by=gb, filters=None)
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="override",
                        output_group_by=str(gb),
                        output_duration_ms=duration_ms
                    )
                    logger.debug(f"[DSPy Dimensions] Override used: {gb}")
                    return result

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
                    original_query=classified_query.original_query,
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
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    _span_set(span,
                        output_source="clarification_required",
                        output_duration_ms=duration_ms,
                        clarification_field="dimensions",
                        clarification_reason="no_valid_dimensions"
                    )
                    logger.debug(f"[DSPy Dimensions] Clarification required - no valid dimensions for {classified_query.query_intent}")
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
                                # Create a focused query context for this specific term to avoid confusion
                                focused_query = f"Show data by {first_pending}"
                                term_classified = [t.model_dump() for t in classified_query.classified_terms if t.role in ("DIMENSION", "FILTER_VALUE") and t.term == first_pending]
                                term_prediction = self.predict(
                                    original_query=focused_query,  # Use focused query instead of full query
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
                                    duration_ms = int((time.monotonic() - start_time) * 1000)
                                    _span_set(span,
                                        output_source="clarification_required",
                                        output_duration_ms=duration_ms,
                                        clarification_field=term_field_key,
                                        clarification_reason="multiple_term_ambiguity",
                                        clarifying_term=first_pending
                                    )
                                    term_options = sorted(term_candidates) if term_candidates else sorted(valid_dims)
                                    logger.debug(f"[DSPy Dimensions] Clarification required for term: {first_pending}")
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
                            final_result = DimensionsResult(
                                group_by=resolved_dimensions if resolved_dimensions else None,
                                filters=valid_filters,
                            )
                            duration_ms = int((time.monotonic() - start_time) * 1000)
                            _span_set(span,
                                output_source="auto_resolved",
                                output_group_by=str(resolved_dimensions),
                                output_duration_ms=duration_ms,
                                output_value=final_result.model_dump() if hasattr(final_result, "model_dump") else str(final_result)
                            )
                            logger.debug(f"[DSPy Dimensions] Auto-resolved multiple terms - completed in {duration_ms}ms")
                            return final_result

                        else:
                            # All terms resolved via overrides
                            final_result = DimensionsResult(
                                group_by=resolved_dimensions if resolved_dimensions else None,
                                filters=valid_filters,
                            )
                            duration_ms = int((time.monotonic() - start_time) * 1000)
                            _span_set(span,
                                output_source="override_resolved",
                                output_group_by=str(resolved_dimensions),
                                output_duration_ms=duration_ms,
                                output_value=final_result.model_dump() if hasattr(final_result, "model_dump") else str(final_result)
                            )
                            logger.debug(f"[DSPy Dimensions] All terms resolved via overrides - completed in {duration_ms}ms")
                            return final_result

                    else:
                        # Single term, multiple candidates → standard clarification
                        duration_ms = int((time.monotonic() - start_time) * 1000)
                        _span_set(span,
                            output_source="clarification_required",
                            output_duration_ms=duration_ms,
                            clarification_field="dimensions",
                            clarification_reason="single_term_multiple_candidates"
                        )
                        logger.debug(f"[DSPy Dimensions] Single term with multiple candidates - clarification required")
                        raise ClarificationRequired(
                            build_dimension_clarification(
                                ambiguous_terms=dim_terms,
                                candidate_dimensions=valid_group_by,
                            )
                        )

                # -------------------------
                # 5. Final result
                # -------------------------
                final_result = DimensionsResult(
                    group_by=valid_group_by if valid_group_by else None,
                    filters=valid_filters,
                )
                duration_ms = int((time.monotonic() - start_time) * 1000)
                _span_set(span,
                    output_source="final_result",
                    output_group_by=str(valid_group_by),
                    output_filters_count=len(valid_filters or []),
                    output_duration_ms=duration_ms,
                    output_value=final_result.model_dump() if hasattr(final_result, "model_dump") else str(final_result)
                )

                logger.debug(f"[DSPy Dimensions] Final result - completed in {duration_ms}ms | group_by={valid_group_by} | filters={len(valid_filters or [])}")
                return final_result

            except ClarificationRequired:
                # Re-raise clarifications without logging as errors
                raise
            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                _span_set(span, error_type=type(e).__name__, error_message=str(e))
                logger.error(f"[DSPy Dimensions] Error: {e}")
                raise