"""
Insight Refiner - LLM-based insight refinement

WHAT IT DOES:
- Takes deterministic InsightResult from the InsightEngine
- Uses LLM to refine interpretation, severity, and confidence
- Adds executive-style commentary and context

WHAT IT DOES NOT DO:
- Does NOT recalculate metrics or change numeric values
- Does NOT override math-based insights
- Does NOT hallucinate data

PIPELINE POSITION:
Data → InsightEngine → InsightResult → InsightRefiner → RefinedInsightResult → VisualSpecGenerator
"""

import logging
import logging
from typing import Any, Optional
from pydantic import BaseModel, Field

from app.services.insights.insight_engine import InsightResult, Insight, Severity, Direction
from app.models.qco import QueryContextObject
from app.dspy_pipeline.config import get_insights_module

logger = logging.getLogger(__name__)


# # =============================================================================
# # REFINED INSIGHT MODEL
# # =============================================================================

# class RefinedInsight(BaseModel):
#     """
#     A refined insight with LLM-enhanced interpretation.
    
#     Preserves all numeric fields from the deterministic insight.
#     Only interpretation fields are modified.
#     """
#     # Preserved from original (immutable)
#     insight_type: str
#     label: str
#     metric_value: Optional[float] = None
#     metric_formatted: Optional[str] = None
#     comparison_value: Optional[float] = None
#     comparison_formatted: Optional[str] = None
#     change_pct: Optional[float] = None
#     direction: Direction = Direction.UNKNOWN
#     dimension: Optional[str] = None
#     dimension_value: Optional[str] = None
    
#     # LLM-refinable fields
#     headline: str
#     severity: Severity = Severity.LOW
#     # confidence: float = Field(default=1.0, ge=0.0, le=1.0)
#     # context_note: Optional[str] = None  # New: LLM-added context


# class RefinedInsightResult(BaseModel):
#     """
#     Complete refined insight result.
    
#     Preserves all numeric aggregates from original InsightResult.
#     Only interpretation fields are refined.
#     """
#     # Preserved from original (immutable)
#     total_rows: int = 0
#     total_value: Optional[float] = None
#     total_formatted: Optional[str] = None
#     metric: Optional[str] = None
#     dimensions: Optional[list[str]] = None
#     intent_type: Optional[str] = None
#     has_previous_context: bool = False
    
#     # Refined insights
#     insights: list[RefinedInsight] = Field(default_factory=list)
#     primary_insight: Optional[RefinedInsight] = None
    
#     # LLM-generated narrative (Layer 3)
#     executive_summary: Optional[str] = None
#     key_risks: dict[str, str] = Field(default_factory=dict)
#     possible_drivers: dict[str, str] = Field(default_factory=dict)
#     recommendations: dict[str, str] = Field(default_factory=dict)


# class InsightRefinerError(Exception):
#     """Raised when insight refinement fails."""
#     pass


# # =============================================================================
# # REFINER
# # =============================================================================

# def refine_insights(
#     insight_result: InsightResult,
#     data: list[dict[str, Any]],
#     query: str,
#     previous_qco: Optional[QueryContextObject] = None,
# ) -> RefinedInsightResult:
#     """
#     Refine insights using DSPy module with fallback to original implementation.

#     This is the ONLY public function.

#     Args:
#         insight_result: Deterministic insights from InsightEngine
#         data: Raw query result (for summary statistics)
#         query: Original user query
#         previous_qco: Previous QCO for context

#     Returns:
#         RefinedInsightResult with enhanced insights
#     """
#     logger.info(f"Refining {len(insight_result.insights)} insights")

#     # Try DSPy refinement first
#     try:

#         insights_module = get_insights_module()
#         refined_output = insights_module.forward(
#             query=query,
#             insight_result=insight_result,
#             previous_qco=previous_qco
#         )

#         # Convert DSPy output to RefinedInsightResult
#         refined_result = _convert_dspy_output(insight_result, refined_output)

#         logger.info(f"DSPy insights refined: {len(refined_result.insights)} insights, "
#                      f"executive_summary={'present' if refined_result.executive_summary else 'none'}")

#         return refined_result

#     except Exception as e:
#         logger.warning(f"DSPy insight refinement failed: {e}")
#         # Ultimate fallback: convert original insights without enhancement
#         return _fallback_to_original(insight_result)


# # =============================================================================
# # HELPER FUNCTIONS
# # =============================================================================

# def _convert_dspy_output(insight_result: InsightResult, dspy_output: dict[str, Any]) -> RefinedInsightResult:
#     """
#     Convert DSPy structured output to RefinedInsightResult.

#     Args:
#         insight_result: Original InsightResult with numeric values
#         dspy_output: DSPy module output with refinements

#     Returns:
#         RefinedInsightResult with DSPy enhancements applied
#     """
#     # Convert original insights to refined format
#     refined_insights = []
#     for i, original_insight in enumerate(insight_result.insights):
#         refined_insight = RefinedInsight(
#             # Preserve all numeric fields exactly
#             insight_type=original_insight.insight_type,
#             label=original_insight.label,
#             metric_value=original_insight.metric_value,
#             metric_formatted=original_insight.metric_formatted,
#             comparison_value=original_insight.comparison_value,
#             comparison_formatted=original_insight.comparison_formatted,
#             change_pct=original_insight.change_pct,
#             direction=original_insight.direction,
#             dimension=original_insight.dimension,
#             dimension_value=original_insight.dimension_value,
#             # Apply DSPy refinements to interpretation fields
#             headline=_get_refined_headline(original_insight, dspy_output, i),
#             severity=original_insight.severity,  # Could be enhanced by DSPy in future
#             confidence=original_insight.confidence,  # Could be enhanced by DSPy in future
#             context_note=None  # Could be enhanced by DSPy in future
#         )
#         refined_insights.append(refined_insight)

#     # Create refined result with DSPy narrative
#     return RefinedInsightResult(
#         # Preserve all numeric aggregates exactly
#         total_rows=insight_result.total_rows,
#         total_value=insight_result.total_value,
#         total_formatted=insight_result.total_formatted,
#         metric=insight_result.metric,
#         dimensions=insight_result.dimensions,
#         intent_type=insight_result.intent_type,
#         has_previous_context=insight_result.has_previous_context,
#         # Add refined content
#         insights=refined_insights,
#         primary_insight=refined_insights[0] if refined_insights else None,
#         # Apply DSPy narrative enhancements
#         executive_summary=dspy_output.get("executive_summary"),
#         key_risks=dspy_output.get("key_risks", {}),
#         possible_drivers=dspy_output.get("possible_drivers", {}),
#         recommendations=dspy_output.get("recommendations", {})
#     )


# def _get_refined_headline(original_insight: Insight, dspy_output: dict[str, Any], index: int) -> str:
#     """
#     Extract refined headline for a specific insight from DSPy output.

#     Args:
#         original_insight: Original insight object
#         dspy_output: DSPy structured output
#         index: Index of the insight in the list

#     Returns:
#         Refined headline or original if not found
#     """
#     try:
#         refined_headlines = dspy_output.get("refined_headlines", [])
#         if isinstance(refined_headlines, list) and index < len(refined_headlines):
#             refined_headline = refined_headlines[index]
#             if isinstance(refined_headline, str) and refined_headline.strip():
#                 return refined_headline.strip()
#             elif isinstance(refined_headline, dict) and "headline" in refined_headline:
#                 return str(refined_headline["headline"]).strip()

#         # Fallback to original
#         return original_insight.headline

#     except Exception as e:
#         logger.debug(f"Failed to extract refined headline for index {index}: {e}")
#         return original_insight.headline





# def _fallback_to_original(insight_result: InsightResult) -> RefinedInsightResult:
#     """
#     Convert original InsightResult to RefinedInsightResult without LLM refinement.
    
#     Used as fallback when LLM refinement fails.
#     """
#     refined_insights = [
#         RefinedInsight(
#             insight_type=i.insight_type.value,
#             label=i.label,
#             headline=i.headline,
#             severity=i.severity,
#             confidence=i.confidence,
#             metric_value=i.metric_value,
#             metric_formatted=i.metric_formatted,
#             comparison_value=i.comparison_value,
#             comparison_formatted=i.comparison_formatted,
#             change_pct=i.change_pct,
#             direction=i.direction,
#             dimension=i.dimension,
#             dimension_value=i.dimension_value,
#         )
#         for i in insight_result.insights
#     ]
    
#     primary = None
#     if insight_result.primary_insight:
#         primary = RefinedInsight(
#             insight_type=insight_result.primary_insight.insight_type.value,
#             label=insight_result.primary_insight.label,
#             headline=insight_result.primary_insight.headline,
#             severity=insight_result.primary_insight.severity,
#             confidence=insight_result.primary_insight.confidence,
#             metric_value=insight_result.primary_insight.metric_value,
#             metric_formatted=insight_result.primary_insight.metric_formatted,
#             comparison_value=insight_result.primary_insight.comparison_value,
#             comparison_formatted=insight_result.primary_insight.comparison_formatted,
#             change_pct=insight_result.primary_insight.change_pct,
#             direction=insight_result.primary_insight.direction,
#             dimension=insight_result.primary_insight.dimension,
#             dimension_value=insight_result.primary_insight.dimension_value,
#         )
    
#     return RefinedInsightResult(
#         total_rows=insight_result.total_rows,
#         total_value=insight_result.total_value,
#         total_formatted=insight_result.total_formatted,
#         metric=insight_result.metric,
#         dimensions=insight_result.dimensions,
#         intent_type=insight_result.intent_type,
#         has_previous_context=insight_result.has_previous_context,
#         insights=refined_insights,
#         primary_insight=primary,
#     )

class RefinedInsightResult(BaseModel):
    """LLM-generated narrative layer only. No raw computed insights preserved."""
    executive_summary: Optional[str] = None
    key_risks: dict[str, str] = Field(default_factory=dict)
    possible_drivers: dict[str, str] = Field(default_factory=dict)
    recommendations: dict[str, str] = Field(default_factory=dict)
    source: str = "dspy"


# =============================================================================
# PUBLIC FUNCTION
# =============================================================================

def refine_insights(
    insight_result: InsightResult,
    query: str,
    previous_qco: Optional[QueryContextObject] = None,
) -> RefinedInsightResult:
    """
    Refine insights using DSPy module with fallback to empty result.

    Args:
        insight_result: Deterministic insights from InsightEngine
        query: Original user query
        previous_qco: Previous QCO for context

    Returns:
        RefinedInsightResult with executive narrative
    """
    logger.info(f"Refining {len(insight_result.insights)} insights for query: {query}")

    try:
        insights_module = get_insights_module()
        refined_output = insights_module(
            query=query,
            insight_result=insight_result,
            previous_qco=previous_qco
        )

        result = RefinedInsightResult(
            executive_summary=refined_output.get("executive_summary"),
            key_risks=refined_output.get("key_risks", {}),
            possible_drivers=refined_output.get("possible_drivers", {}),
            recommendations=refined_output.get("recommendations", {}),
            source=refined_output.get("source", "dspy")
        )

        logger.info(f"DSPy refinement completed — summary: {'present' if result.executive_summary else 'missing'}")
        return result

    except Exception as e:
        logger.warning(f"DSPy insight refinement failed: {e}")
        return RefinedInsightResult(source="fallback")