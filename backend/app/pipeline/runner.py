"""
Pipeline Execution Engine

Extracted from query_orchestrator.py to provide reusable pipeline infrastructure
for executing registered step functions with proper error handling and observability.
"""

import json
import logging
from functools import wraps
from typing import Callable, List

from opentelemetry.trace import Status, StatusCode
from app.utils.tracer import get_tracer

from app.pipeline.context import PipelineContext, OrchestratorError, Stage

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


# =============================================================================
# PIPELINE HALT SIGNAL
# =============================================================================

class _Halt(Exception):
    """Raised inside a step to stop the pipeline without setting ctx.error."""


# =============================================================================
# SPAN HELPERS
# =============================================================================

def _span_set(span, **kwargs) -> None:
    """
    Write key/value pairs onto an OTel span in one call.

    Key convention: first underscore → dot  (input_query → "input.query").
    Values are auto-serialized:
      dict/list → json.dumps (≤ 2000 chars)
      str       → truncated to 1000 chars
      None      → ""
      other     → str()
    """
    for raw_key, value in kwargs.items():
        key = raw_key.replace("_", ".", 1)
        if isinstance(value, (dict, list)):
            span.set_attribute(key, json.dumps(value, default=str)[:2000])
        elif isinstance(value, str):
            span.set_attribute(key, value[:1000])
        elif value is None:
            span.set_attribute(key, "")
        else:
            span.set_attribute(key, str(value))


def _span_error(span, err: OrchestratorError) -> None:
    span.set_status(Status(StatusCode.ERROR, err.message))
    _span_set(span, error_type=err.error_type, error_stage=err.stage, error_message=err.message)


# =============================================================================
# STEP DECORATOR
# =============================================================================

def pipeline_step(span_name: str):
    """
    Wraps a step function with an OTel span.
    The step receives (ctx, span) so it can call _span_set directly.
    Signals pipeline halt by raising _Halt (clarification) or setting ctx.error (hard fail).
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(ctx: PipelineContext) -> PipelineContext:
            with tracer.start_as_current_span(span_name) as span:
                fn(ctx, span)
                return ctx
        return wrapper
    return decorator


# =============================================================================
# STEP REGISTRY
# =============================================================================

# Pipeline steps are registered by importing the tool modules
PIPELINE_STEPS: List[Callable[[PipelineContext], PipelineContext]] = []


def register_step(step_function: Callable[[PipelineContext], PipelineContext]) -> None:
    """Register a pipeline step function."""
    PIPELINE_STEPS.append(step_function)


def clear_steps() -> None:
    """Clear all registered steps (for testing)."""
    PIPELINE_STEPS.clear()


# =============================================================================
# PIPELINE RUNNER
# =============================================================================

def run_pipeline(ctx: PipelineContext, start_step: int = 0) -> PipelineContext:
    """
    Chain PIPELINE_STEPS[start_step:] against ctx.

    Stops early on:
      - ctx.error set            → hard failure
      - _Halt raised             → soft stop (clarification requested)
    """
    with tracer.start_as_current_span("pipeline") as root_span:
        _span_set(root_span,
            input_query=ctx.query[:500],
            input_session_id=ctx.session_id or "",
            input_start_step=start_step,
        )
        logger.info(f"Pipeline started: '{ctx.query[:100]}' (session={ctx.session_id}, request={ctx.request_id}, start_step={start_step})")

        for step_fn in PIPELINE_STEPS[start_step:]:
            try:
                step_fn(ctx)
            except _Halt:
                if ctx.stage == Stage.COMPLETED:
                    # Compound query completed successfully — not a clarification halt
                    return ctx
                _span_set(root_span,
                    output_clarification_requested=True,
                    output_missing_fields=str(ctx.missing_fields or []),
                    output_clarification_message=ctx.clarification_message or "",
                )
                return ctx

            if ctx.error:
                _span_error(root_span, ctx.error)
                return ctx

        _span_set(root_span,
            output_success=ctx.success,
            output_stage=ctx.stage,
            output_duration_ms=ctx.duration_ms,
            output_row_count=len(ctx.data or []),
            output_chart_type=getattr(ctx.visual_spec, "chart_type", "") or "",
            output_primary_insight=getattr(getattr(ctx.insights, "primary_insight", None), "label", ""),
            output_value=ctx.to_dict(),
        )
        return ctx


# =============================================================================
# PIPELINE INITIALIZATION
# =============================================================================

def initialize_pipeline():
    """
    Initialize the pipeline by importing all tool modules.
    This registers all step functions in the correct order.
    """
    # Clear any existing steps
    clear_steps()

    # Import tool modules to register their steps
    # Use dynamic imports to avoid circular dependencies
    try:
        from app.services.tools import qco_tool
        from app.services.tools import intent_tool
        from app.services.tools import query_tool
        from app.services.tools import insights_tool

        # Register steps in order
        register_step(qco_tool.step_load_qco)        # 0
        register_step(intent_tool.step_extract_intent)  # 1
        register_step(intent_tool.step_drill_merge)     # 2
        register_step(intent_tool.step_validate_intent) # 3
        register_step(query_tool.step_build_query)      # 4
        register_step(query_tool.step_execute_query)    # 5
        register_step(insights_tool.step_gen_insights)  # 6
        register_step(qco_tool.step_resolve_qco)        # 7
        register_step(qco_tool.step_complete)           # 8

        logger.info(f"Pipeline initialized with {len(PIPELINE_STEPS)} steps")
    except ImportError as e:
        logger.error(f"Failed to import pipeline tools: {e}")
        raise