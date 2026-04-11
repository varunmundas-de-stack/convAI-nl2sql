import dspy
from app.dspy_pipeline.schemas import PostProcessingResult

class RefineInsights(dspy.Signature):
    """Refine insights with enhanced interpretation while preserving all numeric values.

    Enhance insights with executive-style commentary, confidence levels, and contextual interpretation.
    NEVER modify numeric fields (metric_value, change_pct, total_value, etc.) - only interpretation.
    Focus on business significance, severity assessment, and actionable recommendations.
    """

    query: str = dspy.InputField(desc="Original user query for context")
    insight_summary: str = dspy.InputField(
        desc="JSON string containing InsightResult with deterministic insights, "
             "metrics facts, total values, and original numeric calculations"
    )
    previous_context: str = dspy.InputField(
        desc="Previous QueryContextObject context as JSON string for continuity",
        default=""
    )

    refined_insights: str = dspy.OutputField(
        desc="JSON object containing: "
             "executive_summary (concise business interpretation), "
             "refined_headlines (array of enhanced insight headlines maintaining original numeric values), "
             "key_risks (object with risk categories and descriptions), "
             "possible_drivers (object with potential business causes), "
             "recommendations (object with actionable next steps). "
             "CRITICAL: Preserve ALL numeric values exactly as provided. "
             "Only refine interpretation, severity assessment, and business context. "
             "Headlines should be executive-ready while maintaining factual precision."
    )