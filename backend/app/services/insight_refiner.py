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
import json
from typing import Any, Optional
from pathlib import Path
from pydantic import BaseModel, Field

from app.services.insight_engine import InsightResult, Insight, Severity, Direction
from app.services.llm_service import call_claude, count_tokens
from app.models.qco import QueryContextObject

logger = logging.getLogger(__name__)


# =============================================================================
# REFINED INSIGHT MODEL
# =============================================================================

class RefinedInsight(BaseModel):
    """
    A refined insight with LLM-enhanced interpretation.
    
    Preserves all numeric fields from the deterministic insight.
    Only interpretation fields are modified.
    """
    # Preserved from original (immutable)
    insight_type: str
    label: str
    metric_value: Optional[float] = None
    metric_formatted: Optional[str] = None
    comparison_value: Optional[float] = None
    comparison_formatted: Optional[str] = None
    change_pct: Optional[float] = None
    direction: Direction = Direction.UNKNOWN
    dimension: Optional[str] = None
    dimension_value: Optional[str] = None
    
    # LLM-refinable fields
    headline: str
    severity: Severity = Severity.LOW
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    context_note: Optional[str] = None  # New: LLM-added context


class RefinedInsightResult(BaseModel):
    """
    Complete refined insight result.
    
    Preserves all numeric aggregates from original InsightResult.
    Only interpretation fields are refined.
    """
    # Preserved from original (immutable)
    total_rows: int = 0
    total_value: Optional[float] = None
    total_formatted: Optional[str] = None
    metric: Optional[str] = None
    dimensions: Optional[list[str]] = None
    intent_type: Optional[str] = None
    has_previous_context: bool = False
    
    # Refined insights
    insights: list[RefinedInsight] = Field(default_factory=list)
    primary_insight: Optional[RefinedInsight] = None
    
    # LLM-generated narrative (Layer 3)
    executive_summary: Optional[str] = None
    key_risks: list[str] = Field(default_factory=list)
    possible_drivers: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class InsightRefinerError(Exception):
    """Raised when insight refinement fails."""
    pass


# =============================================================================
# REFINER
# =============================================================================

def refine_insights(
    insight_result: InsightResult,
    data: list[dict[str, Any]],
    query: str,
    previous_qco: Optional[QueryContextObject] = None,
) -> RefinedInsightResult:
    """
    Refine insights using LLM.
    
    This is the ONLY public function.
    
    Args:
        insight_result: Deterministic insights from InsightEngine
        data: Raw query result (for summary statistics)
        query: Original user query
        previous_qco: Previous QCO for context
        
    Returns:
        RefinedInsightResult with LLM-enhanced insights
    """
    logger.info(f"Refining {len(insight_result.insights)} insights with LLM")
    
    try:
        # Build compact data summary (not full raw rows)
        data_summary = _build_data_summary(insight_result, data)
        
        # Build LLM prompt
        prompt = _build_prompt(insight_result, data_summary, query, previous_qco)
        
        # Call LLM
        logger.debug(f"Calling LLM for insight refinement (prompt length: {len(prompt)} chars)")
        response = call_claude(prompt)
        try:
            token_count = count_tokens(prompt)
            logger.info(f"Input token count: {token_count.input_tokens}")
        except Exception as e:
            logger.warning(f"Error counting tokens: {e}")
        # Parse response
        raw_text = response.content[0].text
        refinements = _parse_refinements(raw_text)
        
        # Apply refinements
        refined_result = _apply_refinements(insight_result, refinements)
        
        logger.info(f"Insights refined: {len(refined_result.insights)} insights, "
                     f"executive_summary={'present' if refined_result.executive_summary else 'none'}")
        
        return refined_result
        
    except Exception as e:
        logger.warning(f"Insight refinement failed (non-fatal): {e}, falling back to original insights")
        # Fallback: convert original insights to refined format without LLM changes
        return _fallback_to_original(insight_result)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _build_data_summary(insight_result: InsightResult, data: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Build a compact summary of data + insights for LLM.
    
    We do NOT pass 1000 raw rows. We pass aggregated statistics.
    Includes Layer 1 (MetricsFact) and Layer 2 (RuleInsights) for structured LLM input.
    """
    summary: dict[str, Any] = {
        "total_rows": insight_result.total_rows,
        "total_value": insight_result.total_value,
        "total_formatted": insight_result.total_formatted,
        "metric": insight_result.metric,
        "dimensions": insight_result.dimensions,
        "intent_type": insight_result.intent_type,
        "has_previous_context": insight_result.has_previous_context,
    }

    # Layer 1: structured metrics facts (pure math)
    if insight_result.metrics_facts:
        mf = insight_result.metrics_facts
        summary["metrics_facts"] = {
            "trend_class": mf.trend_class,
            "percent_change_latest": mf.percent_change_latest,
            "percent_change_overall": mf.percent_change_overall,
            "growth_acceleration": mf.growth_acceleration,
            "is_accelerating": mf.is_accelerating,
            "consecutive_growth_periods": mf.consecutive_growth_periods,
            "consecutive_decline_periods": mf.consecutive_decline_periods,
            "largest_drop_period": mf.largest_drop_period,
            "largest_drop_pct": mf.largest_drop_pct,
            "largest_gain_period": mf.largest_gain_period,
            "largest_gain_pct": mf.largest_gain_pct,
            "mean": mf.mean,
            "std_dev": mf.std_dev,
            "coefficient_of_variation": mf.coefficient_of_variation,
            "volatility_flag": mf.volatility_flag,
            "anomaly_flag": mf.anomaly_flag,
            "anomaly_periods": mf.anomaly_periods,
            "top_contributor": mf.top_contributor,
            "top_contributor_pct": mf.top_contributor_pct,
            "top3_contributor_pct": mf.top3_contributor_pct,
            "concentration_flag": mf.concentration_flag,
        }

    # Layer 2: rule-triggered insights (business logic)
    if insight_result.rule_insights:
        summary["rule_insights"] = [
            {
                "type": ri.type,
                "severity": ri.severity.value,
                "message_key": ri.message_key,
                "description": ri.description,
                "context": ri.context,
                "triggered_by": ri.triggered_by,
            }
            for ri in insight_result.rule_insights
        ]

    # Sample data points (max 5 rows — for grounding)
    if data:
        summary["sample_data"] = data[:5]

    return summary


def _build_prompt(
    insight_result: InsightResult,
    data_summary: dict[str, Any],
    query: str,
    previous_qco: Optional[QueryContextObject],
) -> str:
    """
    Build the LLM prompt from template.
    """
    # Load prompt template
    prompt_path = Path(__file__).parent.parent / "prompts" / "insight_refiner.txt"
    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()
    
    # Build input data structure
    input_data = {
        "query": query,
        "data_summary": data_summary,
        "previous_context": (
            {
                "metric": previous_qco.metric,
                "sales_scope": previous_qco.sales_scope,
                "time_range": previous_qco.time_range.model_dump() if previous_qco.time_range else None,
                "previous_query": previous_qco.original_query,
            }
            if previous_qco
            else None
        ),
    }
    
    # Inject into template
    prompt = template.replace("{{INPUT_DATA}}", json.dumps(input_data, indent=2))
    
    return prompt


def _parse_refinements(raw_text: str) -> dict[str, Any]:
    """
    Parse LLM response as JSON.
    
    Expected format:
    {
      "executive_summary": "...",
      "key_risks": ["risk 1", "risk 2"],
      "possible_drivers": ["driver 1", "driver 2"],
      "recommendations": ["action 1", "action 2"],
      "refined_insights": [
        {
          "label": "...",
          "headline": "...",
          "severity": "...",
          "confidence": 0.8,
          "context_note": "..."
        }
      ]
    }
    """
    # Extract JSON from markdown code blocks if present
    if "```json" in raw_text:
        start = raw_text.find("```json") + 7
        end = raw_text.find("```", start)
        raw_text = raw_text[start:end].strip()
    elif "```" in raw_text:
        start = raw_text.find("```") + 3
        end = raw_text.find("```", start)
        raw_text = raw_text[start:end].strip()
    
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM refinement response: {e}")
        logger.debug(f"Raw response: {raw_text}")
        raise InsightRefinerError(f"LLM returned invalid JSON: {e}")


def _apply_refinements(
    insight_result: InsightResult,
    refinements: dict[str, Any],
) -> RefinedInsightResult:
    """
    Apply LLM refinements to insights.
    
    CRITICAL: Only interpretation fields are modified.
    All numeric fields are preserved from the original.
    """
    # Build refinement map by label — support both old "insights" key and new "refined_insights" key
    refinement_map = {
        r["label"]: r
        for r in (refinements.get("refined_insights") or refinements.get("insights") or [])
    }
    
    # Convert insights to refined format
    refined_insights = []
    for original in insight_result.insights:
        refinement = refinement_map.get(original.label, {})
        
        refined = RefinedInsight(
            # Immutable fields (preserved from original)
            insight_type=original.insight_type.value,
            label=original.label,
            metric_value=original.metric_value,
            metric_formatted=original.metric_formatted,
            comparison_value=original.comparison_value,
            comparison_formatted=original.comparison_formatted,
            change_pct=original.change_pct,
            direction=original.direction,
            dimension=original.dimension,
            dimension_value=original.dimension_value,
            
            # Refinable fields (may be overridden by LLM)
            headline=refinement.get("headline", original.headline),
            severity=Severity(refinement.get("severity", original.severity.value)),
            confidence=refinement.get("confidence", original.confidence),
            context_note=refinement.get("context_note"),
        )
        
        refined_insights.append(refined)
    
    # Build refined result
    refined_result = RefinedInsightResult(
        # Preserved from original
        total_rows=insight_result.total_rows,
        total_value=insight_result.total_value,
        total_formatted=insight_result.total_formatted,
        metric=insight_result.metric,
        dimensions=insight_result.dimensions,
        intent_type=insight_result.intent_type,
        has_previous_context=insight_result.has_previous_context,
        
        # Refined insights
        insights=refined_insights,
        
        # LLM-generated narrative (Layer 3)
        executive_summary=refinements.get("executive_summary"),
        key_risks=refinements.get("key_risks") or [],
        possible_drivers=refinements.get("possible_drivers") or [],
        recommendations=refinements.get("recommendations") or [],
    )
    
    # Set primary insight (highest severity + confidence)
    if refined_insights:
        refined_result.primary_insight = max(
            refined_insights,
            key=lambda i: (
                ["low", "medium", "high", "critical"].index(i.severity),
                i.confidence,
            )
        )
    
    return refined_result


def _fallback_to_original(insight_result: InsightResult) -> RefinedInsightResult:
    """
    Convert original InsightResult to RefinedInsightResult without LLM refinement.
    
    Used as fallback when LLM refinement fails.
    """
    refined_insights = [
        RefinedInsight(
            insight_type=i.insight_type.value,
            label=i.label,
            headline=i.headline,
            severity=i.severity,
            confidence=i.confidence,
            metric_value=i.metric_value,
            metric_formatted=i.metric_formatted,
            comparison_value=i.comparison_value,
            comparison_formatted=i.comparison_formatted,
            change_pct=i.change_pct,
            direction=i.direction,
            dimension=i.dimension,
            dimension_value=i.dimension_value,
        )
        for i in insight_result.insights
    ]
    
    primary = None
    if insight_result.primary_insight:
        primary = RefinedInsight(
            insight_type=insight_result.primary_insight.insight_type.value,
            label=insight_result.primary_insight.label,
            headline=insight_result.primary_insight.headline,
            severity=insight_result.primary_insight.severity,
            confidence=insight_result.primary_insight.confidence,
            metric_value=insight_result.primary_insight.metric_value,
            metric_formatted=insight_result.primary_insight.metric_formatted,
            comparison_value=insight_result.primary_insight.comparison_value,
            comparison_formatted=insight_result.primary_insight.comparison_formatted,
            change_pct=insight_result.primary_insight.change_pct,
            direction=insight_result.primary_insight.direction,
            dimension=insight_result.primary_insight.dimension,
            dimension_value=insight_result.primary_insight.dimension_value,
        )
    
    return RefinedInsightResult(
        total_rows=insight_result.total_rows,
        total_value=insight_result.total_value,
        total_formatted=insight_result.total_formatted,
        metric=insight_result.metric,
        dimensions=insight_result.dimensions,
        intent_type=insight_result.intent_type,
        has_previous_context=insight_result.has_previous_context,
        insights=refined_insights,
        primary_insight=primary,
    )
