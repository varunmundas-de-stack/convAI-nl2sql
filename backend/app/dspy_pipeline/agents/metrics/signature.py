import dspy

from app.dspy_pipeline.schemas.agent_outputs import MetricsResult

class ExtractMetrics(dspy.Signature):
    """Extract and validate metrics from classified query."""

    original_query: str = dspy.InputField(desc="Original query text")
    classified_terms: str = dspy.InputField(desc="JSON string containing only the classified terms with role METRIC")
    sales_scope: str = dspy.InputField(desc="Resolved sales scope (PRIMARY/SECONDARY)")
    available_metrics: str = dspy.InputField(desc="JSON list of available metrics with name, label, description")

    metrics_result: MetricsResult = dspy.OutputField(
        desc="""
        Return a list of candidate metrics from the catalog.

        Rules:
        - If NO metric is explicitly specified, return all the available metrics as MULTIPLE candidates.
        - If query clearly maps to ONE metric → return single-item list
        - If query is ambiguous → return MULTIPLE candidate metrics
        - All metrics MUST be from provided catalog
        - Do Not guess if ambiguous — return all plausible matches
        """
    )