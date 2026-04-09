"""
Compound Query Tool

Handles compound query processing including response handling and clarification resumption.
Extracted from query_orchestrator.py to isolate complex compound query mini-pipeline logic.
"""

import logging
from typing import Any, Optional

from app.pipeline.context import PipelineContext, Stage
from app.dspy_pipeline.clarification_tool import (
    CompoundClarificationState,
    format_compound_clarification_response
)

logger = logging.getLogger(__name__)


def _handle_compound_query_response(compound_result: dict, ctx: PipelineContext) -> dict:
    """
    Handle compound query response by processing each sub-query through the full pipeline.

    Enhanced to support:
    - compound_partial_results: Progressive display of completed sub-queries
    - compound_clarification_required: Clarifications that preserve partial state

    This function takes compound query results and runs each completed sub-query
    through the full pipeline (validation, cube query, execution, insights) to
    generate complete results for the frontend.
    """
    result_type = compound_result.get("type", "compound_query_results")
    completed_subqueries = compound_result.get("completed_subqueries", [])
    pending_subqueries = compound_result.get("pending_subqueries", [])

    logger.info(f"Processing {len(completed_subqueries)} completed sub-queries through full pipeline")

    # Mark if this is a partial result
    if result_type == "compound_partial_results":
        ctx.is_compound_partial = True

    # Build combined results from completed sub-queries
    combined_results = []
    combined_insights = []
    visual_specs = []

    for completed in completed_subqueries:
        subquery_result = completed.get("result", {})
        subquery_index = completed["index"]
        subquery_text = completed["query"]

        logger.info(f"Processing sub-query {subquery_index}: '{subquery_text}'")

        try:
            # Create a new pipeline context for this sub-query
            subquery_ctx = PipelineContext(
                query=subquery_text,
                session_id=ctx.session_id,
                original_query=ctx.original_query,
                skip_reset_overrides=True  # Don't reset clarification state
            )

            # Set the extracted intent from the compound query
            subquery_ctx.raw_intent = subquery_result
            subquery_ctx.stage = Stage.INTENT_EXTRACTED

            # Run the sub-query through the remaining pipeline steps (2-8)
            # Skip step 0 (load_qco) and step 1 (extract_intent) since we already have the intent

            try:
                # Import step functions from their respective tools
                from app.services.tools.intent_tool import step_drill_merge, step_validate_intent
                from app.services.tools.query_tool import step_build_query, step_execute_query
                from app.services.tools.insights_tool import step_gen_insights

                # Step 2: Drill merge
                step_drill_merge(subquery_ctx)
                logger.info(f"Sub-query {subquery_index}: Drill merge completed")

                # Step 3: Validate intent
                step_validate_intent(subquery_ctx)
                logger.info(f"Sub-query {subquery_index}: Intent validation completed")

                # Step 4: Build query
                step_build_query(subquery_ctx)
                logger.info(f"Sub-query {subquery_index}: Query building completed")

                # Step 5: Execute query
                step_execute_query(subquery_ctx)
                logger.info(f"Sub-query {subquery_index}: Query execution completed")

                # Step 6: Generate insights and visual spec
                step_gen_insights(subquery_ctx)
                logger.info(f"Sub-query {subquery_index}: Insights generation completed")

                # Mark as successful if we made it this far without errors
                if not subquery_ctx.error:
                    subquery_ctx.success = True
                    subquery_ctx.stage = Stage.COMPLETED
                    logger.info(f"Sub-query {subquery_index}: Pipeline completed successfully")

            except Exception as step_error:
                logger.error(f"Sub-query {subquery_index} failed at pipeline step: {type(step_error).__name__}: {step_error}")

                # Check which step failed by examining the context
                if subquery_ctx.error:
                    logger.error(f"Sub-query {subquery_index} context error: {subquery_ctx.error.error_type}: {subquery_ctx.error.message}")

                raise step_error

            # Check if the pipeline succeeded
            if subquery_ctx.error:
                logger.error(f"Sub-query {subquery_index} has error: {subquery_ctx.error.error_type}: {subquery_ctx.error.message}")
                raise Exception(f"{subquery_ctx.error.error_type}: {subquery_ctx.error.message}")

            # Check if we have the minimum required outputs for a successful sub-query
            if subquery_ctx.visual_spec and subquery_ctx.data is not None:
                # Force success flag if we have visual spec and data, regardless of what pipeline steps did
                subquery_ctx.success = True
                logger.info(f"Sub-query {subquery_index}: Verified success with visual_spec and data")

            if subquery_ctx.success and subquery_ctx.visual_spec:
                # Convert Pydantic models to dictionaries for JSON serialization
                visual_spec_dict = subquery_ctx.visual_spec.model_dump() if hasattr(subquery_ctx.visual_spec, 'model_dump') else subquery_ctx.visual_spec
                insights_dict = None
                if subquery_ctx.refined_insights:
                    insights_dict = subquery_ctx.refined_insights.model_dump() if hasattr(subquery_ctx.refined_insights, 'model_dump') else subquery_ctx.refined_insights
                elif subquery_ctx.insights:
                    insights_dict = subquery_ctx.insights.model_dump() if hasattr(subquery_ctx.insights, 'model_dump') else subquery_ctx.insights

                section_data = {
                    "subquery_index": subquery_index,
                    "subquery_text": subquery_text,
                    "data": subquery_ctx.data or [],
                    "visual_spec": visual_spec_dict,
                    "insights": insights_dict,
                    "status": "completed"
                }

                logger.info(f"Sub-query {subquery_index} completed successfully with {len(subquery_ctx.data or [])} rows")
            else:
                # Pipeline failed but didn't raise exception
                error_msg = "Pipeline processing failed"
                if subquery_ctx.error:
                    error_msg = f"{subquery_ctx.error.error_type}: {subquery_ctx.error.message}"
                else:
                    # No explicit error, check what's missing
                    missing_parts = []
                    if not subquery_ctx.success:
                        missing_parts.append("success=False")
                    if not subquery_ctx.visual_spec:
                        missing_parts.append("no visual_spec")
                    if not subquery_ctx.data:
                        missing_parts.append("no data")

                    error_msg = f"Pipeline incomplete: {', '.join(missing_parts)}"
                    logger.error(f"Sub-query {subquery_index} pipeline incomplete: success={subquery_ctx.success}, stage={subquery_ctx.stage}, visual_spec={subquery_ctx.visual_spec is not None}, data_rows={len(subquery_ctx.data or [])}")

                section_data = {
                    "subquery_index": subquery_index,
                    "subquery_text": subquery_text,
                    "data": [],
                    "visual_spec": {
                        "chart_type": "bar",
                        "title": f"Error: {subquery_text}",
                        "empty": True,
                        "annotations": [{
                            "text": error_msg,
                            "severity": "high",
                            "position": "header"
                        }]
                    },
                    "insights": None,
                    "status": "error"
                }

                logger.warning(f"Sub-query {subquery_index} failed: {error_msg}")

        except Exception as e:
            logger.error(f"Failed to process sub-query {subquery_index}: {e}")

            # Create error section
            section_data = {
                "subquery_index": subquery_index,
                "subquery_text": subquery_text,
                "data": [],
                "visual_spec": {
                    "chart_type": "bar",
                    "title": f"Error: {subquery_text}",
                    "empty": True,
                    "annotations": [{
                        "text": f"Processing failed: {str(e)}",
                        "severity": "high",
                        "position": "header"
                    }]
                },
                "insights": None,
                "status": "error"
            }

        combined_results.append(section_data)

        # Collect insights and visual specs
        if section_data.get("insights"):
            combined_insights.append({
                "subquery_index": subquery_index,
                "subquery_text": subquery_text,
                "insights": section_data["insights"]
            })

        if section_data.get("visual_spec"):
            visual_specs.append({
                "subquery_index": subquery_index,
                "subquery_text": subquery_text,
                "visual_spec": section_data["visual_spec"],
                "status": section_data["status"]
            })

    # Add pending sub-queries to visual specs for progress display
    for pending in pending_subqueries:
        pending_status = pending.get("status", "pending")
        visual_specs.append({
            "subquery_index": pending["index"],
            "subquery_text": pending["query"],
            "visual_spec": None,
            "status": pending_status,
            "reason": pending.get("reason", "Pending processing"),
            "blocked_by": pending.get("blocked_by", [])
        })

    # Determine chart type based on result type
    if result_type == "compound_partial_results":
        chart_type = "compound_sections_partial"
        status_summary = f"Showing {len(completed_subqueries)} of {len(completed_subqueries) + len(pending_subqueries)} results (partial)"
    else:
        chart_type = "compound_sections"
        status_summary = f"Analysis completed for {len(completed_subqueries)} of {len(completed_subqueries) + len(pending_subqueries)} queries"

    # Create compound visual spec that represents multiple sections
    compound_visual_spec = {
        "chart_type": chart_type,
        "sections": visual_specs,
        "total_sections": len(completed_subqueries) + len(pending_subqueries),
        "completed_sections": len(completed_subqueries),
        "pending_sections": len(pending_subqueries),
        "is_partial": result_type == "compound_partial_results"
    }

    # Create compound insights
    compound_insights = {
        "type": "compound_insights",
        "sections": combined_insights,
        "summary": status_summary,
        "is_partial": result_type == "compound_partial_results"
    }

    logger.info(f"Compound query processing complete: {len(combined_results)} sections with data")

    return {
        "results": combined_results,
        "visual_spec": compound_visual_spec,
        "insights": compound_insights,
        "compound_metadata": {
            "original_query": compound_result.get("original_query"),
            "total_subqueries": compound_result.get("total_subqueries"),
            "completed_count": len(completed_subqueries),
            "pending_count": len(pending_subqueries),
            "pending_subqueries": pending_subqueries
        }
    }


def resume_compound_clarification(
    compound_state: CompoundClarificationState,
    clarification_answer: Any,
    session_id: Optional[str] = None,
    overrides: Optional[dict] = None
) -> PipelineContext:
    """
    Resume compound query processing after clarification is provided.

    Args:
        compound_state: The compound clarification state from when the query was suspended
        clarification_answer: The user's answer to the clarification
        session_id: Session ID for the request

    Returns:
        PipelineContext with the resumed compound query results
    """
    from app.dspy_pipeline.pipeline import IntentExtractionPipeline

    try:
        # Create pipeline and resume from clarification
        pipeline = IntentExtractionPipeline()
        result = pipeline.resume_compound_query_from_clarification(
            compound_state=compound_state,
            clarification_answer=clarification_answer,
            current_date=None,
            overrides=overrides or {}
        )

        # Create context to wrap the result
        ctx = PipelineContext(
            query=compound_state.pending_clarification.subquery_text if compound_state.pending_clarification else "",
            session_id=session_id,
            request_id=compound_state.request_id
        )

        if isinstance(result, CompoundClarificationState):
            # Another clarification is needed
            ctx.compound_clarification_state = result
            ctx.is_compound_query = True
            ctx.clarification = True
            ctx.compound_metadata = format_compound_clarification_response(result)
            
            # Populate standard clarification fields for the frontend wrapper
            pending_clarification = result.pending_clarification
            if pending_clarification:
                clarification_obj = pending_clarification.clarification
                ctx.missing_fields = [clarification_obj.field]
                ctx.clarification_message = f"For sub-query {pending_clarification.subquery_index + 1}: {clarification_obj.question}"
                ctx.allowed_values = clarification_obj.options
                
            ctx.stage = Stage.CLARIFICATION_REQUESTED
        elif isinstance(result, dict):
            # Compound results are ready
            ctx.is_compound_query = True
            ctx.raw_intent = result

            compound_response = _handle_compound_query_response(result, ctx)
            ctx.data = compound_response.get("results", [])
            ctx.visual_spec = compound_response.get("visual_spec")
            ctx.insights = compound_response.get("insights")
            ctx.compound_metadata = compound_response.get("compound_metadata")
            ctx.success = True
            ctx.stage = Stage.COMPLETED

        ctx.duration_ms = ctx.elapsed_ms()
        return ctx

    except Exception as e:
        logger.error(f"Error resuming compound clarification: {e}")
        ctx = PipelineContext(
            query=compound_state.pending_clarification.subquery_text if compound_state.pending_clarification else "",
            session_id=session_id,
            request_id=compound_state.request_id
        )
        ctx.fail(Stage.INTENT_EXTRACTED, "CompoundResumptionError", str(e))
        return ctx