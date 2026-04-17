import dspy
from app.dspy_pipeline.schemas.agent_outputs import RefinedInsights

class RefineInsights(dspy.Signature):
    """Refine insights with executive-style commentary for frontline sales reps and area managers.
    Translate analytics into plain English — no statistics background required.
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

    refined_insights: RefinedInsights = dspy.OutputField(
        desc=(
            "Structured insights object. CRITICAL RULES: "
            "(1) Never recalculate or modify any numeric values — READ-ONLY. "
            "(2) No statistical jargon — use plain sales language. "
            "(3) Indian numbering — Lakhs and Crores only. "
            "(4) NEVER return empty dicts for any section — minimum 2 entries each. "
            "(5) Every claim must trace to an input field."
        )
    )
