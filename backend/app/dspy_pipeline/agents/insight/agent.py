from typing import Optional, Dict, Any
import dspy
import json
import logging
from app.utils.tracer import get_tracer

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)

from app.dspy_pipeline.agents.insight.signature import RefineInsights
from app.services.insights.insight_engine import InsightResult
from app.models.qco import QueryContextObject


class InsightsModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.refine = dspy.ChainOfThought(RefineInsights)

    def forward(self,
                query: str,
                insight_result: InsightResult,
                previous_qco: Optional[QueryContextObject] = None) -> Dict[str, Any]:
        try:
            insight_summary = self._prepare_insight_summary(insight_result)

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

            result = self.refine(
                query=query,
                insight_summary=insight_summary,
                previous_context=previous_context
            )

            # ✅ Pydantic object — no json.loads() needed
            refined_output = result.refined_insights.model_dump()
            refined_output["source"] = "dspy"
            refined_output["original_insights_count"] = len(insight_result.insights)

            logger.info(f"DSPy insight refinement completed: {len(insight_result.insights)} insights processed")
            return refined_output

        except Exception as e:
            logger.warning(f"DSPy insight refinement failed: {e}")
            raise

    def _prepare_insight_summary(self, insight_result: InsightResult) -> str:
        try:
            summary = {
                "total_rows": insight_result.total_rows,
                "total_value": insight_result.total_value,
                "total_formatted": insight_result.total_formatted,
                "metric": insight_result.metric,
                "dimensions": insight_result.dimensions,
                "intent_type": insight_result.intent_type,
                "has_previous_context": insight_result.has_previous_context
            }

            insights_data = []
            for insight in insight_result.insights:
                insights_data.append({
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
                })

            summary["insights"] = insights_data

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
            return json.dumps({
                "total_rows": insight_result.total_rows,
                "total_value": insight_result.total_value,
                "metric": insight_result.metric,
                "insights": [{"headline": i.headline, "metric_value": i.metric_value} for i in insight_result.insights]
            }, default=str)