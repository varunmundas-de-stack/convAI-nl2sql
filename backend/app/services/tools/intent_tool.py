"""
Intent Processing Tool

Handles the intent resolution pipeline: extract → merge → validate.
Extracted from query_orchestrator.py to provide focused intent processing logic.
"""

import logging

from app.pipeline.context import PipelineContext, Stage
from app.pipeline.runner import pipeline_step, _span_set, _span_error, _Halt
from app.services.intent.intent_extractor import (
    extract_intent, ExtractionError, LLMCallError, LLMTimeoutError,
)
from app.dspy_pipeline.clarification_tool import (
    CompoundClarificationRequired,
    format_compound_clarification_response
)
from app.services.intent.intent_errors import IntentValidationError, IntentIncompleteError
from app.services.intent.intent_validator import validate_intent
from app.services.intent.intent_normalizer import normalize_intent, patch_trend_intent
from app.services.intent.intent_merger import merge_intent
from app.services.intent.drill_detector import detect_drill, apply_drill_mutation

logger = logging.getLogger(__name__)


# =============================================================================
# PIPELINE STEPS
# =============================================================================

@pipeline_step("intent.extract")
def step_extract_intent(ctx: PipelineContext, span) -> None:
    """Step 1 — LLM call to extract intent from the query."""
    _span_set(span,
        input_query=ctx.query[:500],
        input_has_previous_qco=ctx.previous_qco is not None,
        input_previous_qco_metric=getattr(ctx.previous_qco, "metric", "") or "",
        input_previous_qco_scope=getattr(ctx.previous_qco, "sales_scope", "") or "",
    )
    try:
        logger.info("Step 1: Extracting intent...")

        # Prepare overrides, including session-level resolved terms
        overrides = dict(ctx.resolved_clarifications or {})

        # Inject session-level resolved terms to prevent re-asking same clarifications
        if ctx.session_id and not ctx.skip_reset_overrides:
            try:
                from app.dspy_pipeline.clarification_tool import clarification_tool as _ct
                session_resolved_terms = _ct.get_resolved_terms(ctx.session_id)
                if session_resolved_terms:
                    overrides.update(session_resolved_terms)
                    logger.info(f"Injected session resolved terms for {ctx.session_id}: {session_resolved_terms}")
                else:
                    logger.debug(f"No session resolved terms found for {ctx.session_id}")
            except Exception as e:
                logger.warning(f"Failed to inject session resolved terms: {e}")

        raw_intent = extract_intent(
            ctx.query,
            previous_qco=ctx.previous_qco,
            skip_reset_overrides=ctx.skip_reset_overrides,
            overrides=overrides,
            request_id=ctx.request_id,
            session_id=ctx.session_id,
        )

        # Capture and store any newly created resolved terms for future queries
        if ctx.session_id and isinstance(raw_intent, dict):
            try:
                from app.dspy_pipeline.clarification_tool import clarification_tool as _ct

                # Store resolved metric terms
                if "resolved_metric_terms" in raw_intent:
                    for term, value in raw_intent["resolved_metric_terms"].items():
                        _ct.store_resolved_term(ctx.session_id, "metric", term, value)
                        logger.info(f"Captured resolved metric term: {term} -> {value}")

                # Store resolved dimension terms
                if "resolved_dimension_terms" in raw_intent:
                    for term, value in raw_intent["resolved_dimension_terms"].items():
                        _ct.store_resolved_term(ctx.session_id, "dimension", term, value)
                        logger.info(f"Captured resolved dimension term: {term} -> {value}")

            except Exception as e:
                logger.warning(f"Failed to capture resolved terms: {e}")

        # Check if this is a compound query result
        if isinstance(raw_intent, dict) and raw_intent.get("type") in ["compound_query_results", "compound_partial_results"]:
            result_type = raw_intent.get("type")
            logger.info(f"{result_type.replace('_', ' ').title()} detected - handling structured response")

            ctx.raw_intent = raw_intent
            ctx.is_compound_query = True

            # Import and call compound query handler
            from app.services.tools import compound_tool
            compound_response = compound_tool._handle_compound_query_response(raw_intent, ctx)

            ctx.data = compound_response.get("results", [])
            ctx.visual_spec = compound_response.get("visual_spec")
            ctx.insights = compound_response.get("insights")
            ctx.compound_metadata = compound_response.get("compound_metadata")
            ctx.success = True
            ctx.stage = Stage.COMPLETED
            ctx.duration_ms = ctx.elapsed_ms()

            _span_set(span,
                output_compound_query=True,
                output_is_partial=result_type == "compound_partial_results",
                output_subqueries_count=raw_intent.get("total_subqueries", 0),
                output_completed_count=len(raw_intent.get("completed_subqueries", [])),
                output_pending_count=len(raw_intent.get("pending_subqueries", [])),
                output_value=raw_intent,
            )

            if result_type == "compound_partial_results":
                logger.info(f"Compound partial results processed: {len(raw_intent.get('completed_subqueries', []))} completed, {len(raw_intent.get('pending_subqueries', []))} pending")
            else:
                logger.info(f"Compound query processed: {len(raw_intent.get('completed_subqueries', []))} completed, {len(raw_intent.get('pending_subqueries', []))} pending")

            raise _Halt  # ← stop pipeline here, skip validate/build/execute steps

        # Single query result - continue with normal processing
        ctx.raw_intent = raw_intent
        ctx.stage = Stage.INTENT_EXTRACTED
        _span_set(span,
            output_intent_type=str(raw_intent.get("intent_type", "")),
            output_metric=str(raw_intent.get("metric", "")),
            output_value=raw_intent,
        )
        logger.info(f"Intent extracted: {raw_intent}")

    except IntentIncompleteError as e:
        logger.warning(f"Clarification needed at extraction: {e}")

        # Check if this is a compound query clarification
        partial_intent = e.partial_intent or {}
        if partial_intent.get("compound_query_state"):
            logger.info("Handling compound query clarification")
            ctx.raw_intent = partial_intent
        else:
            ctx.raw_intent = partial_intent

        ctx.clarification = True
        ctx.missing_fields = e.missing_fields
        ctx.clarification_message = e.clarification_message
        ctx.allowed_values = e.allowed_values
        ctx.stage = Stage.CLARIFICATION_REQUESTED
        ctx.duration_ms = ctx.elapsed_ms()
        _span_set(span, output_clarification_requested=True, output_missing_fields=str(e.missing_fields))
        raise _Halt

    except CompoundClarificationRequired as e:
        logger.info(f"Compound query clarification required: {e}")

        # Store compound clarification state
        ctx.compound_clarification_state = e.compound_state
        ctx.is_compound_query = True
        ctx.clarification = True

        # Format compound clarification response
        clarification_response = format_compound_clarification_response(e.compound_state)

        # Extract clarification details for context
        pending_clarification = e.compound_state.pending_clarification
        if pending_clarification:
            clarification_obj = pending_clarification.clarification
            ctx.missing_fields = [clarification_obj.field]
            ctx.clarification_message = clarification_obj.question
            ctx.allowed_values = clarification_obj.options

        # Store the complete clarification response
        ctx.compound_metadata = clarification_response

        ctx.stage = Stage.CLARIFICATION_REQUESTED
        ctx.duration_ms = ctx.elapsed_ms()
        _span_set(span,
            output_compound_clarification_requested=True,
            output_subquery_index=pending_clarification.subquery_index if pending_clarification else -1,
            output_completed_count=len(e.compound_state.completed_indices),
            output_total_subqueries=len(e.compound_state.decomposed_queries)
        )
        raise _Halt

    except LLMTimeoutError as e:
        logger.error(f"LLM timeout: {e}")
        span.record_exception(e)
        ctx.fail(Stage.RECEIVED, "LLMTimeoutError", str(e))
        _span_error(span, ctx.error)

    except LLMCallError as e:
        logger.error(f"LLM call error: {e}")
        span.record_exception(e)
        ctx.fail(Stage.RECEIVED, "LLMCallError", str(e))
        _span_error(span, ctx.error)

    except ExtractionError as e:
        logger.error(f"Extraction error: {e}")
        span.record_exception(e)
        ctx.fail(Stage.RECEIVED, "ExtractionError", str(e))
        _span_error(span, ctx.error)


@pipeline_step("intent.drill_merge")
def step_drill_merge(ctx: PipelineContext, span) -> None:
    """Step 2 — detect drill-down mutation, then merge intent with previous QCO."""

    # Drill detection
    if ctx.previous_qco and ctx.raw_intent:
        drill_result = detect_drill(ctx.raw_intent, ctx.previous_qco)
        _span_set(span, output_drill_case=drill_result.case)
        if drill_result.case != "none":
            ctx.raw_intent = apply_drill_mutation(ctx.raw_intent, ctx.previous_qco, drill_result)
            _span_set(span,
                output_drill_prev=drill_result.prev_dimension or "",
                output_drill_next=drill_result.next_dimension or "",
            )
            logger.info(f"Drill [{drill_result.case}]: {drill_result.prev_dimension} → {drill_result.next_dimension}")

    # Merge
    if ctx.previous_qco and ctx.raw_intent:
        ctx.merged_intent = merge_intent(ctx.raw_intent, ctx.previous_qco)
        ctx.stage = Stage.INTENT_MERGED
        _span_set(span, output_merged_with_qco=True, output_value=ctx.merged_intent)
        logger.info("Intent merged with previous QCO")
    else:
        ctx.merged_intent = ctx.raw_intent
        _span_set(span, output_merged_with_qco=False)


@pipeline_step("intent.validate")
def step_validate_intent(ctx: PipelineContext, span) -> None:
    """Step 3 — normalize + validate intent against catalog."""
    from app.services.tools.qco_tool import _get_catalog

    intent_to_log = ctx.merged_intent or ctx.raw_intent or {}
    _span_set(span,
        input_intent_source="merged" if ctx.merged_intent else "raw",
        input_value=intent_to_log,
    )
    try:
        logger.info("Step 3: Validating intent...")
        normalized = normalize_intent(ctx.merged_intent or ctx.raw_intent)
        normalized = patch_trend_intent(normalized, ctx.query)
        validated = validate_intent(normalized, _get_catalog(), original_query=ctx.query)
        ctx.validated_intent = validated
        ctx.stage = Stage.INTENT_VALIDATED
        _span_set(span,
            output_intent_type=str(getattr(validated, "intent_type", "")),
            output_metrics=str(getattr(validated, "metrics", ""))[:500],
            output_dimensions=str(getattr(validated, "group_by", ""))[:500],
            output_value=getattr(validated, "model_dump", lambda: str(validated))(),
        )
        logger.info(f"Intent validated: {validated}")

    except IntentIncompleteError as e:
        logger.warning(f"Incomplete intent: {e}")
        ctx.clarification = True
        ctx.missing_fields = e.missing_fields
        ctx.clarification_message = e.clarification_message
        ctx.allowed_values = e.allowed_values
        ctx.stage = Stage.CLARIFICATION_REQUESTED
        ctx.duration_ms = ctx.elapsed_ms()
        _span_set(span, output_clarification_requested=True, output_missing_fields=str(e.missing_fields))
        raise _Halt

    except IntentValidationError as e:
        logger.error(f"Intent validation failed: {e}")
        span.record_exception(e)
        ctx.fail(Stage.INTENT_EXTRACTED, "IntentValidationError", str(e))
        _span_error(span, ctx.error)