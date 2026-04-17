import dspy
from app.dspy_pipeline.schemas import TimeResult

class ResolveTime(dspy.Signature):
    """Determine time constraints from classified query with decision logic and clarification rules."""

    original_query: str = dspy.InputField(desc="Original query text")
    classified_terms: str = dspy.InputField(desc="JSON string containing only the classified terms with roles TIME_RANGE and TIME_GRANULARITY")
    current_date: str = dspy.InputField(desc="Current date in YYYY-MM-DD format")
    query_intent: str = dspy.InputField(desc="Query intent from classified query (KPI, DISTRIBUTION, RANKING, TREND, COMPARISON, etc.)")
    previous_context: str = dspy.InputField(desc="Previous QCO context as JSON string. empty on first turn")

    # Output TimeResult as JSON
    time_result: TimeResult = dspy.OutputField(
        desc="JSON object with TimeResult structure containing: "
             "time_window (exact TIME_WINDOW match or null), "
             "start_date (YYYY-MM-DD or null), "
             "end_date (YYYY-MM-DD or null), "
             "granularity (day|week|month|quarter|year or null for non-trend queries). "
             "Use time_window for exact matches like 'last_30_days', 'month_to_date'. "
             "Use start_date/end_date only if no time_window matches. "
             "Default granularity to 'week' for TREND queries without explicit granularity. "
             "Window and dates are mutually exclusive - never set both"
    )
