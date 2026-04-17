"""
QCO Management Tool

Handles QueryContextObject (QCO) lifecycle management including loading,
resolving, and session persistence. Extracted from query_orchestrator.py.
"""

import logging
from pathlib import Path
from typing import Optional

from opentelemetry.trace import Status, StatusCode

from app.pipeline.context import PipelineContext, Stage
from app.pipeline.runner import pipeline_step, _span_set
from app.services.helpers.catalog_manager import CatalogManager
from app.services.helpers.qco_resolver import resolve_qco
from app.pipeline.qco_store import save_qco, load_qco

logger = logging.getLogger(__name__)


# =============================================================================
# CATALOG SINGLETON
# =============================================================================

_catalog: Optional[CatalogManager] = None

def _get_catalog() -> CatalogManager:
    """Get the catalog manager singleton. Session lifecycle concern."""
    global _catalog
    if _catalog is None:
        catalog_path = Path(__file__).parent.parent.parent.parent / "catalog" / "catalog.yaml"
        _catalog = CatalogManager(str(catalog_path))
    return _catalog


# =============================================================================
# PIPELINE STEPS
# =============================================================================

@pipeline_step("qco.load")
def step_load_qco(ctx: PipelineContext, span) -> None:
    """Step 0 — reset clarification tool, load QCO."""

    # Reset clarification tool for fresh queries (start_step=0)
    # This ensures clarification state is cleared for both new sessions AND follow-up queries
    if not ctx.skip_reset_overrides:
        try:
            from app.dspy_pipeline.clarification_tool import clarification_tool as _ct
            if ctx.session_id:
                # For existing sessions, reset clarification state to prevent stale clarifications
                _ct.reset_for_new_request(session_id=ctx.session_id)
                logger.debug(f"Reset clarification state for existing session {ctx.session_id}")
            else:
                # For brand-new sessions, global reset
                _ct.reset_for_new_request()
                logger.debug("Reset clarification state for new session")
        except Exception as e:
            logger.warning(f"Failed to reset clarification tool: {e}")

    _span_set(span, input_session_id=ctx.session_id or "")

    if ctx.session_id:
        try:
            qco = load_qco(ctx.session_id)
            if qco:
                ctx.previous_qco = qco
                ctx.stage = Stage.QCO_LOADED
                _span_set(span, output_found=True, output_metric=qco.metric or "", output_sales_scope=qco.sales_scope or "")
                logger.info(f"Loaded QCO for session {ctx.session_id}: metric={qco.metric}")
            else:
                _span_set(span, output_found=False)
                logger.info(f"No previous QCO for session {ctx.session_id} (first query)")
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            logger.warning(f"Failed to load QCO for session {ctx.session_id}: {e}")


@pipeline_step("qco.resolve")
def step_resolve_qco(ctx: PipelineContext, span) -> None:
    """Step 7 — persist QCO snapshot for the next query in this session."""
    if not ctx.session_id or not ctx.validated_intent:
        return

    _span_set(span, input_session_id=ctx.session_id)
    try:
        qco = resolve_qco(ctx.original_intent or ctx.validated_intent, ctx.query)

        # Populate x_axis_labels to inject into context
        is_trend = qco.intent_type.lower() == "trend"
        x_axis_key_val = getattr(ctx.visual_spec, "x_axis_key", "") or ""
        is_date_key = "date" in x_axis_key_val.lower() or "time" in x_axis_key_val.lower()

        if not is_trend and not is_date_key and ctx.visual_spec:
            x_axis_labels = None
            if getattr(ctx.visual_spec, "x_axis", None) and getattr(ctx.visual_spec.x_axis, "values", None):
                x_axis_labels = ctx.visual_spec.x_axis.values
            elif getattr(ctx.visual_spec, "x_axis_key", None) and ctx.data:
                key = ctx.visual_spec.x_axis_key
                x_axis_labels = [r.get(key) for r in ctx.data if key in r]

            if x_axis_labels:
                # Deduplicate and limit to prevent context window bloat
                unique_labels = list(dict.fromkeys(str(x) for x in x_axis_labels if x is not None))
                qco.x_axis_labels = unique_labels[:50]

        save_qco(ctx.session_id, qco)
        ctx.stage = Stage.QCO_RESOLVED
        _span_set(span, output_resolved=True, output_qco_metric=qco.metric or "")
        logger.info(f"QCO resolved and saved for session {ctx.session_id}")
    except Exception as e:
        span.set_status(Status(StatusCode.ERROR, str(e)))
        span.record_exception(e)
        _span_set(span, output_resolved=False)
        logger.warning(f"Failed to resolve/save QCO: {e}")


@pipeline_step("pipeline.complete")
def step_complete(ctx: PipelineContext, span) -> None:
    """Step 8 — mark success, cleanup clarification tool state."""
    try:
        from app.dspy_pipeline.clarification_tool import clarification_tool as _ct
        # Clean up by request ID
        cleaned = _ct.cleanup_request_state(request_id_prefix=ctx.request_id, max_entries=100)
        if cleaned > 0:
            logger.debug(f"Cleaned up {cleaned} clarification entries for {ctx.request_id}")

        # Also clean up any remaining state for this session to prevent stale clarifications
        # But preserve resolved term mappings for future queries in the same session
        if ctx.session_id:
            _ct.reset_for_new_request(session_id=ctx.session_id)
            logger.debug(f"Final clarification cleanup for session {ctx.session_id}")
    except Exception as e:
        logger.warning(f"Failed to cleanup clarification tool: {e}")

    ctx.success = True
    ctx.stage = Stage.COMPLETED
    ctx.duration_ms = ctx.elapsed_ms()
    logger.info(f"Pipeline completed in {ctx.duration_ms}ms")
    _span_set(span, output_duration_ms=ctx.duration_ms)