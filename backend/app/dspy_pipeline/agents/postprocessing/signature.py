import dspy
from app.dspy_pipeline.schemas import PostProcessingResult, TimeResult, DimensionsResult

class ResolvePostProcessing(dspy.Signature):
    """Infer high-level post-processing intent."""

    original_query: str = dspy.InputField(desc="Original query text")
    query_intent: str = dspy.InputField(
        desc="The query_intent extracted from the classified query (e.g., RANKING, COMPARISON, TREND, etc.)"
    )

    classified_terms: str = dspy.InputField(
        desc="JSON string containing only the classified terms with roles RANKING, COMPARISON, and TREND"
    )

    time_result: TimeResult = dspy.InputField(
        desc="Resolved time context (window, dates, granularity)"
    )

    dimensions_result: DimensionsResult = dspy.InputField(
        desc="Contains group_by (required for ranking)"
    )

    post_processing_result: PostProcessingResult = dspy.OutputField(
    desc=(
        "Return PostProcessingResult with: "
        "ranking (enabled/order/limit), "
        "comparison.comparison_window must be one of: "
        "'today','yesterday','last_7_days','last_30_days','last_90_days','month_to_date',"
        "'quarter_to_date','year_to_date','last_month','last_quarter','last_year','all_time' "
        "or null. "
        "If the query compares explicit dates/months like 'feb vs march', set comparison_window=null. "
        "NEVER output 'previous_period' or any unlisted value — use null instead. "
        "derived_metric: none|wow_growth|mom_growth|yoy_growth|period_change|contribution_percent|avg_price."
        )
    )
