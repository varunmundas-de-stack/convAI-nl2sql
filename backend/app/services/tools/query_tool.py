"""
Query Execution Tool

Handles Cube.js interaction: build query → execute query.
Extracted from query_orchestrator.py to provide focused query processing logic.

Responsibilities:
  step_build_query  — ALL query construction (primary + secondary), intent transformation
  step_execute_query — pure execution only; delegates to CubeDBTool
"""

import logging

from opentelemetry.trace import Status, StatusCode
from app.utils.tracer import get_tracer

from app.pipeline.context import PipelineContext, Stage
from app.pipeline.runner import pipeline_step, _span_set, _span_error
from app.services.cube.cube_query_builder import (
    build_cube_query, build_comparison_query, build_total_query, CubeQueryBuildError,
)
from app.services.cube.cube_client import CubeHTTPError, CubeQueryExecutionError
from app.services.cube.period_planner import determine_strategy, QueryStrategy, transform_intent_for_strategy
from app.services.tools.cube_db_tool import CubeDBTool

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


# =============================================================================
# PIPELINE STEPS
# =============================================================================

@pipeline_step("cube.build_query")
def step_build_query(ctx: PipelineContext, span) -> None:
    """Step 4 — determine period strategy, transform intent, build ALL Cube queries.

    Owns all query construction so that step_execute_query is pure I/O.
    Writes to ctx:
        period_strategy     — strategy enum value string
        original_intent     — pre-transform intent (preserved for downstream)
        validated_intent    — post-transform intent
        cube_query          — primary query dict
        comparison_query    — secondary query dict, or None
    """
    try:
        logger.info("Step 4: Building Cube query...")

        # --- Strategy determination ---
        try:
            strategy = determine_strategy(ctx.validated_intent)
            ctx.period_strategy = strategy.value
        except Exception as e:
            logger.warning(f"Period strategy determination failed (non-fatal): {e}")
            strategy = QueryStrategy.SINGLE_QUERY
            ctx.period_strategy = strategy.value

        _span_set(span, output_strategy=ctx.period_strategy)

        # --- Intent transformation ---
        ctx.original_intent = ctx.validated_intent
        transformed = transform_intent_for_strategy(ctx.validated_intent, strategy)
        ctx.validated_intent = transformed

        # --- Primary query ---
        ctx.cube_query = build_cube_query(transformed)

        _span_set(span,
            input_value=getattr(transformed, "model_dump", lambda: str(transformed))(),
            output_measures=str(ctx.cube_query.get("measures", [])),
            output_dimensions=str(ctx.cube_query.get("dimensions", [])),
            output_filters=str(ctx.cube_query.get("filters", []))[:500],
            output_value=ctx.cube_query,
        )
        logger.info(f"Primary Cube query built: {ctx.cube_query}")

        # --- Secondary query (strategy-dependent) ---
        # Built here so step_execute_query has zero query-construction logic.
        ctx.comparison_query = None

        if strategy.value == QueryStrategy.DUAL_QUERY.value:
            ctx.comparison_query = _build_dual_query(ctx, transformed)

        elif strategy.value == QueryStrategy.CONTRIBUTION.value:
            try:
                ctx.comparison_query = build_total_query(transformed)
                logger.info("Total (contribution) query built.")
            except Exception as e:
                logger.warning(f"Total query build failed (non-fatal): {e}")

        ctx.stage = Stage.CUBE_QUERY_BUILT

    except CubeQueryBuildError as e:
        logger.error(f"Cube query build error: {e}")
        span.record_exception(e)
        ctx.fail(Stage.INTENT_VALIDATED, "CubeQueryBuildError", str(e))
        _span_error(span, ctx.error)


def _build_dual_query(ctx: PipelineContext, transformed_intent) -> dict | None:
    """Build the comparison query for DUAL_QUERY strategy.

    Handles the explicit date-swap case where the intent's date range IS the
    comparison period (e.g. 'compare with Feb') and the current period comes
    from the previous QCO.

    Returns the built query dict, or None if build fails (non-fatal).
    """
    try:
        intent_for_comparison = transformed_intent

        comp = getattr(
            getattr(intent_for_comparison.post_processing, "comparison", None),
            "comparison_window",
            None,
        )

        # Explicit date comparison: swap intent dates with previous QCO range
        if not comp and intent_for_comparison.time and intent_for_comparison.time.start_date:
            prev_qco = getattr(ctx, "previous_qco", None)
            logger.info(
                f"DUAL_QUERY debug: prev_qco={prev_qco}, "
                f"time_range={getattr(prev_qco, 'time_range', None)}"
            )
            if prev_qco and prev_qco.time_range:
                intent_for_comparison = intent_for_comparison.model_copy(deep=True)
                object.__setattr__(intent_for_comparison.time, "start_date", prev_qco.time_range.start_date)
                object.__setattr__(intent_for_comparison.time, "end_date", prev_qco.time_range.end_date)
                object.__setattr__(intent_for_comparison.time, "window", None)
                logger.info(
                    f"DUAL_QUERY: explicit date comparison — "
                    f"comparison period set to QCO range "
                    f"{prev_qco.time_range.start_date} → {prev_qco.time_range.end_date}"
                )

        query = build_comparison_query(intent_for_comparison)
        logger.info("Comparison query built.")
        return query

    except Exception as e:
        logger.warning(f"Comparison query build failed (non-fatal): {e}")
        return None


@pipeline_step("cube.execute")
def step_execute_query(ctx: PipelineContext, span) -> None:
    """Step 5 — execute pre-built Cube queries via CubeDBTool. No query construction here.

    Reads from ctx:
        cube_query          — primary query (required)
        comparison_query    — secondary query, or None
        period_strategy     — for logging/tracing only
    Writes to ctx:
        data                — primary result rows
        comparison_data     — secondary result rows (if applicable)
        stage               — CUBE_EXECUTED on success
    """
    strategy = ctx.period_strategy or QueryStrategy.SINGLE_QUERY.value
    _span_set(span, input_strategy=strategy, input_cube_query=str(ctx.cube_query)[:1000])

    db = CubeDBTool()
    logger.info(f"Step 5: Executing Cube query (strategy={strategy})...")

    # --- Primary query ---
    with tracer.start_as_current_span("cube.primary_query") as primary_span:
        try:
            ctx.data = db.run(ctx.cube_query)
            _span_set(primary_span,
                output_row_count=len(ctx.data),
                output_sample_row=str(ctx.data[0])[:500] if ctx.data else "",
            )
            logger.info(f"Primary query: {len(ctx.data)} rows")

        except CubeHTTPError as e:
            primary_span.set_status(Status(StatusCode.ERROR, str(e)))
            ctx.fail(
                Stage.CUBE_QUERY_BUILT, "CubeHTTPError", "Cube query failed",
                details=e.to_dict() if hasattr(e, "to_dict") else None,
            )
            _span_error(span, ctx.error)
            return  # runner halts on ctx.error

        except CubeQueryExecutionError as e:
            primary_span.set_status(Status(StatusCode.ERROR, str(e)))
            ctx.fail(Stage.CUBE_QUERY_BUILT, "CubeQueryExecutionError", str(e))
            _span_error(span, ctx.error)
            return

    _span_set(span, output_primary_row_count=len(ctx.data))

    # --- Secondary query (non-fatal if it fails) ---
    if ctx.comparison_query:
        span_name = (
            "cube.comparison_query"
            if strategy == QueryStrategy.DUAL_QUERY.value
            else "cube.total_query"
        )
        with tracer.start_as_current_span(span_name) as s:
            try:
                ctx.comparison_data = db.run(ctx.comparison_query)
                _span_set(s, output_row_count=len(ctx.comparison_data))
                logger.info(f"Secondary query ({strategy}): {len(ctx.comparison_data)} rows")
                if strategy == QueryStrategy.DUAL_QUERY.value:
                    logger.info(f"Comparison raw data sample: {ctx.comparison_data[:2]}")
            except Exception as e:
                s.set_status(Status(StatusCode.ERROR, str(e)))
                s.record_exception(e)
                logger.warning(f"Secondary query failed (non-fatal): {e}")

    ctx.stage = Stage.CUBE_EXECUTED