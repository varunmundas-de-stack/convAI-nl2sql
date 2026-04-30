"""
Query Orchestrator - Refactored

Slim coordinator containing only:
- Public API functions: execute_query(), execute_query_dict(), execute_retry_query(), resume_query()
- Complex orchestration: resume_query() (keeps ~180 lines of clarification state management)

All step functions and compound handling moved to modular tools.
Pipeline infrastructure moved to pipeline/runner.py.
"""

import logging
import uuid
from typing import Any, Dict, Optional

from opentelemetry.trace import Status, StatusCode
from app.utils.tracer import get_tracer

# Import pipeline infrastructure
from app.pipeline.context import PipelineContext, Stage
from app.pipeline.runner import run_pipeline, initialize_pipeline, _span_set

# Import state management
from app.pipeline.state_store import save_state, load_state, delete_state, PipelineStateNotFound
from app.pipeline.pipeline_state import PipelineState as PersistedState
from app.pipeline.qco_store import load_qco

# Import for clarification resumption
from app.services.intent.intent_merger import merge_intent

# Import for compound clarification
from app.services.tools.compound_tool import resume_compound_clarification
from app.dspy_pipeline.clarification_tool import CompoundClarificationState

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)

# Ensure pipeline is initialized
initialize_pipeline()

# Re-export Stage for backward compatibility
# (main.py imports Stage from query_orchestrator)
__all__ = ["execute_query", "execute_query_dict", "resume_query", "execute_retry_query", "Stage"]


# =============================================================================
# CLARIFICATION TERM HELPERS
# =============================================================================

def _extract_term_mapping(field_name: str) -> tuple[str | None, str | None]:
    """
    Extract (term_type, original_term) from a clarification field key.

    Supported formats:
    - metric_term_<original_term>
    - dimension_term_<original_term>
    """
    if field_name.startswith("metric_term_"):
        return "metric", field_name[len("metric_term_"):]
    if field_name.startswith("dimension_term_"):
        return "dimension", field_name[len("dimension_term_"):]
    return None, None


def _store_session_resolved_terms(
    session_id: str,
    missing_fields: list[str],
    clarification_answers: Dict[str, Any],
) -> None:
    """Persist term-level clarifications so follow-up queries don't re-ask them."""
    from app.dspy_pipeline.clarification_tool import clarification_tool as _ct

    for field, answer in clarification_answers.items():
        if field not in missing_fields:
            continue

        term_type, original_term = _extract_term_mapping(field)
        if not term_type or not original_term:
            # Only persist term-scoped clarifications; generic fields (metrics/group_by)
            # are not stable keys for future term matching.
            continue

        resolved_value = str(answer).strip() if not isinstance(answer, list) else str(answer[0]).strip()
        _ct.store_resolved_term(session_id, term_type, original_term, resolved_value)
        logger.debug(f"Stored resolved term for session {session_id}: {original_term} -> {resolved_value}")


# =============================================================================
# PUBLIC API
# =============================================================================

def execute_query(
    query: str,
    session_id: Optional[str] = None,
    _skip_reset_overrides: bool = False,
    _resolved_clarifications: Optional[Dict[str, Any]] = None,
) -> PipelineContext:
    """Run the full pipeline from step 0."""
    ctx = PipelineContext(
        query=query,
        session_id=session_id,
        original_query=query,
        skip_reset_overrides=_skip_reset_overrides,
        resolved_clarifications=_resolved_clarifications,
    )
    ctx = run_pipeline(ctx, start_step=0)

    if ctx.stage == Stage.CLARIFICATION_REQUESTED:
        save_state(PersistedState(
            request_id=ctx.request_id,
            original_query=query,
            intent=ctx.raw_intent or {},
            missing_fields=ctx.missing_fields or [],
            session_id=session_id,
            resolved_clarifications=_resolved_clarifications or {},
        ))
        logger.info(f"Clarification state saved: {ctx.request_id}")

    return ctx


def execute_query_dict(query: str, session_id: Optional[str] = None) -> Dict[str, Any]:
    """Convenience wrapper — returns a JSON-serializable dict."""
    return execute_query(query, session_id=session_id).to_dict()


def resume_query(
    request_id: str,
    clarification_answers: Dict[str, Any],
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resume a pipeline paused at CLARIFICATION_REQUESTED.

    Loads saved state, patches intent with user answers,
    re-enters at step 3 (validate_intent).
    """
    with tracer.start_as_current_span("pipeline.resume") as span:
        _span_set(span,
            input_request_id=request_id,
            input_session_id=session_id or "",
            input_clarification_keys=str(list(clarification_answers.keys())),
            input_value=clarification_answers,
        )

        try:
            state = load_state(request_id)
        except PipelineStateNotFound:
            logger.warning(f"Pipeline state not found: request_id={request_id}")
            return {
                "success": False,
                "stage": "invalid_request",
                "request_id": request_id,
                "session_id": session_id,
                "error": {
                    "error_type": "PipelineStateNotFound",
                    "message": "Invalid or expired request_id. Please start a new query.",
                    "details": {"request_id": request_id, "hint": "State expires after 1 hour or on server restart"},
                },
            }

        resolved_session_id = session_id or state.session_id

        # Check if this is a compound clarification
        compound_state_data = state.intent.get("compound_query_state")
        if compound_state_data:
            logger.info(f"Handling compound query clarification resumption")
            try:
                # Convert dict back to CompoundClarificationState
                compound_state = CompoundClarificationState(**compound_state_data)

                # Get the clarification answer (assuming single field for now)
                clarification_answer = list(clarification_answers.values())[0] if clarification_answers else None

                # Accumulate overrides
                overrides = getattr(state, "resolved_clarifications", {}) or {}
                overrides.update(clarification_answers)

                # Resume compound clarification
                result_ctx = resume_compound_clarification(
                    compound_state=compound_state,
                    clarification_answer=clarification_answer,
                    session_id=resolved_session_id,
                    overrides=overrides
                )

                # Clean up state on success
                if result_ctx.success:
                    try:
                        delete_state(state.request_id)
                    except Exception:
                        pass
                elif result_ctx.stage == Stage.CLARIFICATION_REQUESTED:
                    # Save the new clarification state so the next reply works
                    state_to_save = PersistedState(
                        request_id=result_ctx.request_id,
                        original_query=state.original_query,
                        intent={"compound_query_state": result_ctx.compound_clarification_state.model_dump() if hasattr(result_ctx.compound_clarification_state, "model_dump") else result_ctx.compound_clarification_state} if result_ctx.compound_clarification_state else {},
                        missing_fields=result_ctx.missing_fields or [],
                        session_id=resolved_session_id,
                        resolved_clarifications=overrides,
                    )
                    save_state(state_to_save)
                    logger.info(f"Updated clarification state saved: {result_ctx.request_id}")

                result = result_ctx.to_dict()
                _span_set(span,
                    output_success=result.get("success", False),
                    output_stage=result.get("stage", ""),
                    output_compound_resumption=True
                )
                return result

            except Exception as e:
                logger.error(f"Compound clarification resumption failed: {e}")
                # Fall through to standard clarification handling

        # DSPy clarification — resolved overrides, full re-run from step 0
        if state.intent.get("dspy_clarification_request_id"):
            logger.info(f"Handling DSPy clarification for {state.intent.get('dspy_clarification_request_id')}")

            # Check if this is a compound query clarification
            compound_state = state.intent.get("compound_query_state")
            subquery_index = state.intent.get("dspy_clarification_subquery_index")

            if compound_state and subquery_index is not None:
                logger.info(f"Resuming compound query clarification for sub-query {subquery_index}")

                # Handle compound query clarification by re-running with the specific sub-query resolved
                # This is a complex scenario that would require partial pipeline resumption
                # For now, we'll treat it as a regular clarification and re-run the full query
                # TODO: Implement partial sub-query resumption for compound queries

            try:
                resolved = getattr(state, "resolved_clarifications", {}) or {}
                if state.intent.get("dspy_clarification_request_id"):
                    resolved["dspy_clarification_request_id"] = state.intent.get("dspy_clarification_request_id")
                if state.intent.get("dspy_clarification_term"):
                    resolved["dspy_clarification_term"] = state.intent.get("dspy_clarification_term")

                # Store resolved terms in session-level clarification tool for DSPy clarifications
                if resolved_session_id:
                    try:
                        _store_session_resolved_terms(
                            resolved_session_id,
                            state.missing_fields or [],
                            clarification_answers,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to store DSPy resolved clarification terms: {e}")

                for f, answer in clarification_answers.items():
                    if f not in state.missing_fields:
                        continue
                    resolved[f] = [str(a).strip() for a in answer] if isinstance(answer, list) else str(answer).strip()

                # Add compound query context if available
                if compound_state:
                    resolved["compound_query_clarification"] = {
                        "subquery_index": subquery_index,
                        "compound_state": compound_state
                    }

                logger.info(f"DSPy resolved overrides: {resolved}")
                try:
                    delete_state(state.request_id)
                except Exception:
                    pass
                result = execute_query(
                    query=state.original_query,
                    session_id=resolved_session_id,
                    _skip_reset_overrides=True,
                    _resolved_clarifications=resolved,
                ).to_dict()
                _span_set(span, output_success=result.get("success", False), output_stage=result.get("stage", ""))
                return result
            except Exception as e:
                logger.error(f"DSPy clarification resume error: {e}")
                # fall through to standard path

        # Standard clarification — patch intent, re-enter at step 3
        previous_qco = None
        if resolved_session_id:
            try:
                previous_qco = load_qco(resolved_session_id)
            except Exception as e:
                logger.warning(f"Could not load QCO on resume: {e}")

        # Store resolved terms in session-level clarification tool
        if resolved_session_id:
            try:
                _store_session_resolved_terms(
                    resolved_session_id,
                    state.missing_fields or [],
                    clarification_answers,
                )
            except Exception as e:
                logger.warning(f"Failed to store resolved clarification terms: {e}")

        patched_intent = {
            **state.intent,
            **{k: v for k, v in clarification_answers.items() if k in state.missing_fields},
        }
        # BUG-02 FIX: merge so QCO context (filters, group_by, etc.) is inherited
        merged_intent = merge_intent(patched_intent, previous_qco) if previous_qco else patched_intent
        logger.info(f"Resume merged intent: {merged_intent}")

        ctx = PipelineContext(
            query=state.original_query,
            session_id=resolved_session_id,
            original_query=state.original_query,
            request_id=request_id,          # preserve original so callers can correlate
            previous_qco=previous_qco,
            raw_intent=patched_intent,
            merged_intent=merged_intent,
            clarification_answers=clarification_answers,
            stage=Stage.INTENT_EXTRACTED,
        )

        # BUG-01 FIX: do NOT delete state here — only after full success
        ctx = run_pipeline(ctx, start_step=3)

        if ctx.stage == Stage.CLARIFICATION_REQUESTED:
            save_state(PersistedState(
                request_id=request_id,
                original_query=state.original_query,
                intent=merged_intent,
                missing_fields=ctx.missing_fields or [],
                session_id=resolved_session_id,
                resolved_clarifications=getattr(state, "resolved_clarifications", {}) or {},
            ))

        if ctx.success:
            delete_state(request_id)

        result = ctx.to_dict()
        _span_set(span,
            output_success=result.get("success", False),
            output_stage=result.get("stage", ""),
            output_row_count=len(result.get("data") or []),
            output_value=result,
        )
        if not result.get("success") and result.get("error"):
            err = result["error"]
            span.set_status(Status(StatusCode.ERROR, err.get("message", "")))
            _span_set(span, error_type=err.get("error_type", ""), error_message=err.get("message", ""))

        return result


def execute_retry_query(
    original_request_id: str,
    modified_query: str,
    session_id: str,
    original_query: str,
) -> PipelineContext:
    """
    Log the retry for RLHF analysis, then run the full pipeline on the modified query.

    Args:
        original_request_id: Request ID of the query being retried.
        modified_query:      The user's revised query text.
        session_id:          Session ID for context continuity.
        original_query:      Original query kept for comparison/logging.
    """
    logger.info(f"Query retry: original_request_id={original_request_id}, session_id={session_id}")
    logger.info(f"Original query: {original_query}")
    logger.info(f"Modified query: {modified_query}")

    try:
        # Log the retry for RLHF analysis
        # Note: RLHF logging is not currently implemented but structure is preserved
        pass
    except Exception as e:
        logger.warning(f"RLHF retry logging failed (non-fatal): {e}")

    # Run the modified query through the full pipeline
    return execute_query(query=modified_query, session_id=session_id)
