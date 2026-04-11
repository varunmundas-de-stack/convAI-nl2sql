import dspy
from ...schemas import DecomposedQuery

class DecomposeQuery(dspy.Signature):
    """Identify and split compound queries into independent analytical sub-queries.
    
    ONLY split when there are clearly independent analytical intents.
    Examples to SPLIT: 'Show me revenue vs last quarter and also which reps are underperforming' → 2 queries.
    Examples to NOT SPLIT: 'Show me revenue by zone and by product' → 1 query (multiple dimensions).
    For single queries, return is_compound=false with original query as single sub_query.
    """

    query: str = dspy.InputField(desc="Natural language query to analyze")
    session_context: str = dspy.InputField(desc="Previous context from session", default="")

    decomposed_query: DecomposedQuery = dspy.OutputField(
        desc="Structured decomposition of the query into independent sub-queries."
    )

