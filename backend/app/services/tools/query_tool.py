"""
Query Execution Tool

Handles Cube.js interaction: build query → execute query.
Extracted from query_orchestrator.py to provide focused query processing logic.
"""

import logging

from opentelemetry.trace import Status, StatusCode
from app.utils.tracer import get_tracer

from app.pipeline.context import PipelineContext, Stage
from app.pipeline.runner import pipeline_step, _span_set, _span_error
from app.services.cube.cube_query_builder import (
    build_cube_query, build_comparison_query, build_total_query, CubeQueryBuildError,
)
from app.services.cube.cube_client import CubeClient, CubeHTTPError, CubeQueryExecutionError
from app.services.cube.period_planner import determine_strategy, QueryStrategy, transform_intent_for_strategy

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


# =============================================================================
# PIPELINE STEPS
# =============================================================================

@pipeline_step("cube.build_query")
def step_build_query(ctx: PipelineContext, span) -> None:
    """Step 4 — determine period strategy, transform intent, build Cube query."""
    try:
        logger.info("Step 4: Building Cube query...")

        try:
            strategy = determine_strategy(ctx.validated_intent)
            ctx.period_strategy = strategy.value
        except Exception as e:
            logger.warning(f"Period strategy determination failed (non-fatal): {e}")
            strategy = QueryStrategy.SINGLE_QUERY
            ctx.period_strategy = strategy.value

        _span_set(span, output_strategy=ctx.period_strategy)

        ctx.original_intent = ctx.validated_intent
        transformed = transform_intent_for_strategy(ctx.validated_intent, strategy)
        ctx.validated_intent = transformed

        ctx.cube_query = build_cube_query(transformed)
        ctx.stage = Stage.CUBE_QUERY_BUILT
        _span_set(span,
            input_value=getattr(transformed, "model_dump", lambda: str(transformed))(),
            output_measures=str(ctx.cube_query.get("measures", [])),
            output_dimensions=str(ctx.cube_query.get("dimensions", [])),
            output_filters=str(ctx.cube_query.get("filters", []))[:500],
            output_value=ctx.cube_query,
        )
        logger.info(f"Cube query built: {ctx.cube_query}")

    except CubeQueryBuildError as e:
        logger.error(f"Cube query build error: {e}")
        span.record_exception(e)
        ctx.fail(Stage.INTENT_VALIDATED, "CubeQueryBuildError", str(e))
        _span_error(span, ctx.error)

# MAX_RETRIES = 1

@pipeline_step("cube.execute")
def step_execute_query(ctx: PipelineContext, span) -> None:
    """Step 5 — execute primary Cube query, plus comparison/total if strategy requires."""
    strategy = ctx.period_strategy or QueryStrategy.SINGLE_QUERY.value
    _span_set(span, input_strategy=strategy, input_cube_query=str(ctx.cube_query)[:1000])

    try:
        client = CubeClient()
        logger.info(f"Step 5: Executing Cube query (strategy={strategy})...")

        # Primary query
        with tracer.start_as_current_span("cube.primary_query") as primary_span:
            try:
                client.get_sql(ctx.cube_query)
                data = client.load(ctx.cube_query).data
                if not data:
                    logger.warning("Primary query returned 0 rows, retrying...")
                    time.sleep(0.3)
                    data = client.load(ctx.cube_query).data
                ctx.data = data
                _span_set(primary_span,
                    output_row_count=len(ctx.data),
                    output_sample_row=str(ctx.data[0])[:500] if ctx.data else "",
                )
                logger.info(f"Primary query: {len(ctx.data)} rows")

            except CubeHTTPError as e:
                primary_span.set_status(Status(StatusCode.ERROR, str(e)))
                ctx.fail(Stage.CUBE_QUERY_BUILT, "CubeHTTPError", "Cube query failed",
                         details=e.to_dict() if hasattr(e, "to_dict") else None)
                _span_error(span, ctx.error)
                return  # stop this step; runner will halt on ctx.error

        _span_set(span, output_primary_row_count=len(ctx.data))

        # Secondary query (strategy-dependent, non-fatal if it fails)
        if strategy == QueryStrategy.DUAL_QUERY.value:
            with tracer.start_as_current_span("cube.comparison_query") as s:
                try:
                    intent_for_comparison = ctx.validated_intent

                    # For explicit date comparisons (e.g. "compare with feb"),
                    # the intent's start_date/end_date IS the comparison period (feb).
                    # The "current period" comes from the previous QCO.
                    comp = getattr(getattr(intent_for_comparison.post_processing, "comparison", None), "comparison_window", None)
                    if not comp and intent_for_comparison.time and intent_for_comparison.time.start_date:
                        prev_qco = getattr(ctx, "previous_qco", None)
                        logger.info(f"DUAL_QUERY debug: prev_qco={prev_qco}, time_range={getattr(prev_qco, 'time_range', None)}")
                        if prev_qco and prev_qco.time_range:
                            # Swap: make current period the primary date range for comparison query
                            from app.models.intent import Intent, TimeSpec
                            intent_for_comparison = intent_for_comparison.model_copy(deep=True)
                            object.__setattr__(
                                intent_for_comparison.time,
                                "start_date",
                                prev_qco.time_range.start_date,
                            )
                            object.__setattr__(
                                intent_for_comparison.time,
                                "end_date",
                                prev_qco.time_range.end_date,
                            )
                            object.__setattr__(
                                intent_for_comparison.time,
                                "window",
                                None,
                            )
                            logger.info(
                                f"DUAL_QUERY: explicit date comparison — "
                                f"comparison period set to QCO range "
                                f"{prev_qco.time_range.start_date} → {prev_qco.time_range.end_date}"
                            )

                    q = build_comparison_query(intent_for_comparison)
                    client.get_sql(q)
                    ctx.comparison_data = client.load(q).data
                    logger.info(f"Comparison raw data sample: {ctx.comparison_data[:2]}")
                    _span_set(s, output_row_count=len(ctx.comparison_data))
                    logger.info(f"Comparison query: {len(ctx.comparison_data)} rows")
                except Exception as e:
                    s.set_status(Status(StatusCode.ERROR, str(e)))
                    s.record_exception(e)
                    logger.warning(f"Comparison query failed (non-fatal): {e}")
        elif strategy == QueryStrategy.CONTRIBUTION.value:
            with tracer.start_as_current_span("cube.total_query") as s:
                try:
                    q = build_total_query(ctx.validated_intent)
                    client.get_sql(q)
                    ctx.comparison_data = client.load(q).data
                    _span_set(s, output_row_count=len(ctx.comparison_data))
                    logger.info(f"Total query: {len(ctx.comparison_data)} rows")
                except Exception as e:
                    s.set_status(Status(StatusCode.ERROR, str(e)))
                    s.record_exception(e)
                    logger.warning(f"Total query failed (non-fatal): {e}")

        ctx.stage = Stage.CUBE_EXECUTED

    except CubeQueryExecutionError as e:
        logger.error(f"Cube execution error: {e}")
        span.record_exception(e)
        ctx.fail(Stage.CUBE_QUERY_BUILT, "CubeQueryExecutionError", str(e))
        _span_error(span, ctx.error)