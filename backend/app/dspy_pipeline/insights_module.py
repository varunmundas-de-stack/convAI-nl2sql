"""
DSPy Insights Module

Replaces raw call_claude() approach with structured DSPy module for insight refinement.
Provides optimization capabilities and consistent structured output.
"""

import json
import logging
from typing import Dict, Any, Optional

import dspy

from app.dspy_pipeline.signatures import RefineInsights
from app.services.insight_engine import InsightResult
from app.models.qco import QueryContextObject

logger = logging.getLogger(__name__)


class InsightsModule(dspy.Module):
    """
    DSPy module for insight refinement and narrative generation.

    Converts deterministic InsightResult into executive-ready insights
    with enhanced interpretation, severity assessment, and recommendations
    while preserving all numeric values.
    """

    def __init__(self):
        super().__init__()
        self.refine = dspy.ChainOfThought(RefineInsights)

    def forward(self,
                query: str,
                insight_result: InsightResult,
                previous_qco: Optional[QueryContextObject] = None) -> Dict[str, Any]:
        """
        Refine insights using DSPy structured approach.

        Args:
            query: Original user query for context
            insight_result: Deterministic insights from InsightEngine
            previous_qco: Previous QueryContextObject for context

        Returns:
            Dict containing refined insights with enhanced narrative
        """
        try:
            # Convert insight_result to structured prompt input
            insight_summary = self._prepare_insight_summary(insight_result)

            # Convert previous context to JSON string
            previous_context = ""
            if previous_qco:
                try:
                    previous_context = json.dumps({
                        "metric": previous_qco.metric,
                        "sales_scope": previous_qco.sales_scope,
                        "dimensions": previous_qco.dimensions,
                        "time_range": {
                            "start_date": str(previous_qco.time_range.start_date) if previous_qco.time_range and previous_qco.time_range.start_date else None,
                            "end_date": str(previous_qco.time_range.end_date) if previous_qco.time_range and previous_qco.time_range.end_date else None
                        } if previous_qco.time_range else None,
                        "x_axis_labels": previous_qco.x_axis_labels[:10] if previous_qco.x_axis_labels else None
                    }, default=str)
                except Exception as e:
                    logger.debug(f"Failed to serialize previous_qco: {e}")
                    previous_context = ""

            # Process via DSPy signature
            result = self.refine(
                query=query,
                insight_summary=insight_summary,
                previous_context=previous_context
            )

            # Parse the structured output
            refined_output = self._parse_refined_output(result.refined_insights)

            # Add source metadata
            refined_output["source"] = "dspy"
            refined_output["original_insights_count"] = len(insight_result.insights)

            logger.info(f"DSPy insight refinement completed: {len(insight_result.insights)} insights processed")

            return refined_output

        except Exception as e:
            logger.warning(f"DSPy insight refinement failed: {e}")
            raise

    def _prepare_insight_summary(self, insight_result: InsightResult) -> str:
        """
        Convert InsightResult to compact JSON summary for DSPy processing.

        Includes only essential structured information, not raw data rows.
        """
        try:
            # Build structured summary
            summary = {
                "total_rows": insight_result.total_rows,
                "total_value": insight_result.total_value,
                "total_formatted": insight_result.total_formatted,
                "metric": insight_result.metric,
                "dimensions": insight_result.dimensions,
                "intent_type": insight_result.intent_type,
                "has_previous_context": insight_result.has_previous_context
            }

            # Add insights with preserved numeric values
            insights_data = []
            for insight in insight_result.insights:
                insight_data = {
                    "insight_type": insight.insight_type,
                    "label": insight.label,
                    "headline": insight.headline,
                    "metric_value": insight.metric_value,
                    "metric_formatted": insight.metric_formatted,
                    "comparison_value": insight.comparison_value,
                    "comparison_formatted": insight.comparison_formatted,
                    "change_pct": insight.change_pct,
                    "direction": insight.direction.value if insight.direction else None,
                    "dimension": insight.dimension,
                    "dimension_value": insight.dimension_value,
                    "severity": insight.severity.value if insight.severity else None,
                    "confidence": insight.confidence
                }
                insights_data.append(insight_data)

            summary["insights"] = insights_data

            # Add metrics facts if available
            if hasattr(insight_result, 'metrics_facts') and insight_result.metrics_facts:
                mf = insight_result.metrics_facts
                summary["metrics_facts"] = {
                    "trend_class": mf.trend_class,
                    "percent_change_latest": mf.percent_change_latest,
                    "percent_change_overall": mf.percent_change_overall,
                    "growth_acceleration": mf.growth_acceleration,
                    "is_accelerating": mf.is_accelerating,
                    "volatility_flag": mf.volatility_flag,
                    "anomaly_flag": mf.anomaly_flag
                }

            return json.dumps(summary, default=str)

        except Exception as e:
            logger.error(f"Failed to prepare insight summary: {e}")
            # Fallback minimal summary
            return json.dumps({
                "total_rows": insight_result.total_rows,
                "total_value": insight_result.total_value,
                "metric": insight_result.metric,
                "insights": [{"headline": i.headline, "metric_value": i.metric_value} for i in insight_result.insights]
            }, default=str)

    def _parse_refined_output(self, refined_insights_text: str) -> Dict[str, Any]:
        """
        Parse the DSPy output into structured format.

        Handles JSON parsing with fallbacks for malformed output.
        """
        try:
            # Try direct JSON parsing
            refined_data = json.loads(refined_insights_text)

            # Validate expected structure
            expected_fields = ["executive_summary", "refined_headlines", "key_risks", "possible_drivers", "recommendations"]
            for field in expected_fields:
                if field not in refined_data:
                    refined_data[field] = {} if field in ["key_risks", "possible_drivers", "recommendations"] else None

            return refined_data

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parsing failed for DSPy output: {e}")

            # Try JSON repair if available
            try:
                from json_repair import repair_json
                repaired = repair_json(refined_insights_text)
                return json.loads(repaired)
            except (ImportError, Exception) as repair_error:
                logger.warning(f"JSON repair failed: {repair_error}")

            # Fallback: extract executive summary from text
            fallback_data = {
                "executive_summary": self._extract_executive_summary_fallback(refined_insights_text),
                "refined_headlines": [],
                "key_risks": {},
                "possible_drivers": {},
                "recommendations": {}
            }

            logger.info("Using fallback parsing for DSPy output")
            return fallback_data

    def _extract_executive_summary_fallback(self, text: str) -> Optional[str]:
        """
        Extract executive summary from text using pattern matching.

        Fallback method when JSON parsing fails completely.
        """
        try:
            # Look for executive summary patterns
            patterns = [
                r"executive[_\s]+summary[:\s]+(.*?)(?:\n\n|\n[A-Z]|$)",
                r"summary[:\s]+(.*?)(?:\n\n|\n[A-Z]|$)",
                r"^(.*?)(?:\n\n|\n[A-Z])"
            ]

            for pattern in patterns:
                import re
                match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
                if match:
                    summary = match.group(1).strip()
                    if len(summary) > 20:  # Ensure meaningful content
                        return summary

            # Ultimate fallback: first meaningful sentence
            sentences = text.split('.')
            for sentence in sentences:
                clean_sentence = sentence.strip()
                if len(clean_sentence) > 20:
                    return clean_sentence + "."

            return text[:200] + "..." if len(text) > 200 else text

        except Exception as e:
            logger.debug(f"Executive summary extraction failed: {e}")
            return None