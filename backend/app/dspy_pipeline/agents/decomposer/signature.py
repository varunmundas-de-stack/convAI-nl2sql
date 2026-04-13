import dspy
from ...schemas import DecomposedQuery

class DecomposeQuery(dspy.Signature):
    """Identify and split compound analytical queries.

    RULES:
    1. Split when the query involves MULTIPLE INDEPENDENT SCOPES.
       - Scope = fundamentally different data domains (e.g., primary sales, secondary sales, inventory, targets).
       - Example: "Compare primary vs secondary sales" → 2 sub-queries.

    2. Do NOT split when it's just multiple dimensions within SAME scope.
       - Example: "Revenue by zone and product" → 1 query.

    3. Do NOT split simple comparisons within SAME dataset.
       - Example: "Revenue this month vs last month" → 1 query.

    4. Split when:
       - Different scopes
       - Different business entities
       - Different aggregation logic that cannot be answered in a single query cleanly

       CRITICAL RULE:

        Decomposition must produce ONLY independently executable queries.

        DO NOT include:
        - intermediate reasoning steps
        - comparison steps
        - aggregation steps

        If the query is a comparison across scopes:
        - ONLY return the base data queries
        - DO NOT include a separate comparison query

        Example:

        Query: Compare primary vs secondary sales

        Correct:
        [
        "Primary sales",
        "Secondary sales"
        ]

        Incorrect:
        [
        "Primary sales",
        "Secondary sales",
        "Compare primary vs secondary sales"
]
    """

    query: str = dspy.InputField(desc="User query")
    session_context: str = dspy.InputField(desc="Session memory", default="")

    decomposed_query: DecomposedQuery = dspy.OutputField(
        desc="List of independent sub-queries with clear scope separation"
    )
