import dspy
from app.dspy_pipeline.schemas import ScopeResult


class ResolveScope(dspy.Signature):
    """Determine sales scope from classified query."""

    original_query: str = dspy.InputField(desc="Original query text")
    classified_terms: str = dspy.InputField(
        desc="JSON string containing only the classified terms with role SCOPE"
    )

    scope_result: ScopeResult = dspy.OutputField(
        desc=(
            "JSON object with ScopeResult containing: "
            "sales_scope (PRIMARY|SECONDARY). "
            "Only return a value if explicitly indicated in the query. "
            "Do NOT assume a default if scope is not mentioned."
        )
    )
