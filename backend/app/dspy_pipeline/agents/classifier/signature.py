import dspy
from ...schemas import ClassifiedQuery

class ClassifyQuery(dspy.Signature):
    """Classify query terms with semantic roles and determine query intent."""

    query: str = dspy.InputField(desc="Natural language query to classify")
    session_context: str = dspy.InputField(desc="Previous context from session", default="")

    # Output the complete classified query as JSON
    classified_query: ClassifiedQuery = dspy.OutputField(
        desc="JSON object with ClassifiedQuery structure containing: "
             "original_query (string), "
             "classified_terms (array of objects with term, role, catalog_match, scope), "
             "query_intent (SNAPSHOT|DISTRIBUTION|RANKING|TREND|COMPARISON|DRILL_DOWN|MINIMAL_MESSAGE|STRUCTURAL), "
             "filter_hints (array of objects with dimension and value), "
             "explicit_scope (PRIMARY|SECONDARY or null). "
             "Intent type MUST be determined based on the query structure and terms. "
             "SNAPSHOT = single aggregated value with no breakdown. "
             "DO NOT guess catalog_match for generic/vague terms like 'region', 'location', 'product'. Leave catalog_match null if ambiguous. "
             "Use roles: METRIC, DIMENSION, TIME_RANGE, TIME_GRANULARITY, FILTER_VALUE, RANKING, SCOPE, COMPARISON, TREND"
    )