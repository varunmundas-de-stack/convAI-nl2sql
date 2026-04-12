"""
Insights Generation Tool

Handles insight generation: insight engine → refiner → visual spec.
Extracted from query_orchestrator.py and prepared for DSPy integration.
"""

import logging

from opentelemetry.trace import Status, StatusCode
from app.utils.tracer import get_tracer

from app.pipeline.context import PipelineContext, Stage
from app.pipeline.runner import pipeline_step, _span_set, _span_error
from app.services.insights.insight_engine import generate_insights, InsightEngineError
from app.services.insights.insight_refiner import refine_insights
from app.services.insights.visual_spec_generator import generate_visual_spec

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)


# =============================================================================
# PIPELINE STEPS
# =============================================================================

@pipeline_step("insights")
def step_gen_insights(ctx: PipelineContext, span) -> None:
    """Step 6 — insight engine → refiner → visual spec."""
    _span_set(span,
        input_data_row_count=len(ctx.data or []),
        input_has_comparison_data=ctx.comparison_data is not None,
        input_strategy=ctx.period_strategy or "",
    )
    try:
        # 6a — Insight engine
        with tracer.start_as_current_span("insights.engine") as s:
            logger.info("Step 6a: Generating insights...")
            result = generate_insights(
                data=ctx.data or [],
                intent=ctx.validated_intent,
                previous_qco=ctx.previous_qco,
                strategy=ctx.period_strategy,
                comparison_data=ctx.comparison_data,
            )
            ctx.insights = result
            ctx.stage = Stage.INSIGHTS_GENERATED
            try:
                _span_set(s,
                    output_insight_count=len(result.insights),
                    output_total_formatted=result.total_formatted or "",
                    output_intent_type=result.intent_type or "",
                    output_primary_label=getattr(result.primary_insight, "label", ""),
                    output_value=getattr(result, "model_dump", lambda: str(result))(),
                )
            except Exception as _e:
                logger.debug(f"Non-fatal span log error: {_e}")
            logger.info(f"Insights generated: {len(result.insights)}")

        # 6b — Refiner (non-fatal)
        with tracer.start_as_current_span("insights.refine") as s:
            logger.info("Step 6b: Refining insights...")
            try:
                refined = refine_insights(
                    insight_result=result,
                    query=ctx.query,
                    previous_qco=ctx.previous_qco,
                )
                ctx.refined_insights = refined
                ctx.stage = Stage.INSIGHTS_REFINED
                try:
                    _span_set(s,
                        output_executive_summary=refined.executive_summary or "",
                        output_value=getattr(refined, "model_dump", lambda: str(refined))(),
                    )
                except Exception as _e:
                    logger.debug(f"Non-fatal span log error: {_e}")
                logger.info("Insights refined (narrative layer generated).")
            except Exception as e:
                s.set_status(Status(StatusCode.ERROR, str(e)))
                s.record_exception(e)
                logger.warning(f"Insight refinement failed (non-fatal): {e}")
                ctx.refined_insights = None

        # 6c — Visual spec
        with tracer.start_as_current_span("visual_spec") as s:
            logger.info("Step 6c: Generating visual spec...")
            spec = generate_visual_spec(
                data=ctx.data or [],
                insights=result,
                chart_type_hint=None,
                query=ctx.query,
                comparison_data=ctx.comparison_data,
                strategy=ctx.period_strategy,
                intent=ctx.validated_intent,
            )
            ctx.visual_spec = spec
            ctx.stage = Stage.VISUAL_SPEC_GENERATED
            _span_set(s,
                output_chart_type=spec.chart_type or "",
                output_annotations_count=len(spec.annotations),
                output_markers_count=len(spec.markers),
                output_title=getattr(spec, "title", "") or "",
                output_value=getattr(spec, "model_dump", lambda: str(spec))(),
            )
            logger.info(f"Visual spec generated: chart_type={spec.chart_type}")

    except InsightEngineError as e:
        logger.error(f"Insight engine error: {e}")
        span.record_exception(e)
        ctx.fail(Stage.CUBE_EXECUTED, e.__class__.__name__, str(e))
        _span_error(span, ctx.error)

    except Exception as e:
        span.set_status(Status(StatusCode.ERROR, str(e)))
        span.record_exception(e)
        logger.warning(f"Insight/spec generation failed (non-fatal): {e}")